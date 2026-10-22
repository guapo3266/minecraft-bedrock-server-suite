"""Estado global del wrapper servidor: ServerManager, singleton y helpers.

El WS broadcast vive AQUÍ (registro active_websockets + broadcast) para que
los routers dependan de este módulo y nunca al revés (sin ciclos).
"""

import asyncio
import threading
import time
from typing import Set

from fastapi import WebSocket

from gui_backend.metrics import get_hardware_metrics
from suite_version import VERSION


class ServerManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.wrapper_process = None
        self.is_running = False
        self.players_online = set()
        self.players_xuid = {}  # cache name -> xuid (registry persistente en supervisor)
        self.log_history = []
        self.max_log_history = 500
        self._log_seq = 0  # id secuencial estable para React keys (filtros/streaming)
        self.start_time = None
        self.last_backup_time = "Ninguno"
        # Sube cada vez que la lista de backups pudo cambiar (backup terminado,
        # rotacion, borrado, otra carpeta): el frontend la vuelve a pedir al
        # verlo cambiar. Antes solo la pedia al conectar y tras pulsar un
        # boton, y los backups nuevos o rotados no aparecian (2026-10-21).
        self.backups_revision = 0
        self.backup_in_progress = False
        self.update_in_progress = False
        self.suite_update_in_progress = False
        self.final_backup_result = None
        self.restart_in_progress = False  # guard de reentrada de restart (2026-09-25)
        self.installed_version = None  # FIX F1: version real capturada del log de BDS
        self.wrapper_exit_event = threading.Event()
        self.wrapper_exit_event.set()  # Sin wrapper en ejecución al inicio
        # G8: "BDS murió" separado de "wrapper terminó". Se marca al ver la
        # linea "[Wrapper] BDS detenido..." del wrapper (y como respaldo en el
        # finally del hilo). restart/update lo usan para saber que el mundo
        # quedo quieto sin esperar el backup final de cierre del wrapper.
        self.server_stopped_event = threading.Event()
        self.server_stopped_event.set()  # Sin wrapper: BDS tampoco corre
        self.active_websockets: Set[WebSocket] = set()
        self.loop = None
        # Exclusion mutua de operaciones que tocan servidor/mundo/instalacion:
        # start, restore y update no pueden solaparse (evita lanzar BDS mientras
        # se reemplaza el mundo o los binarios). El start lo toma sin bloqueo
        # (rechaza con 'busy' si hay contención); restore/update lo toman
        # bloqueante dentro de sus hilos.
        self.op_lock = threading.Lock()
        # Exclusion mutua de escrituras al stdin del wrapper (varios hilos:
        # /api/command, WebSocket y las acciones stop/restart/backup/update).
        # TextIOWrapper no es thread-safe: escrituras concurrentes pueden
        # entremezclarse o corromper el buffer del pipe.
        self.stdin_lock = threading.Lock()
        self.external_instance = False
        self.external_instance_reason = None
        # Registros de suscriptores para services que viven ARRIBA en la
        # cadena (state/supervisor no pueden importarlos): history engancha
        # aqui sus escritores en start(). Cada sink se invoca fuera de
        # manager.lock y nunca debe lanzar (add_log lo envuelve en try/except).
        self.log_sinks = []         # sink(entry: dict) — cada add_log
        self.player_event_sinks = []  # sink(name, xuid, online: bool)
        # Canal de eventos NDJSON del wrapper (IPC estructurada): path del
        # archivo que el wrapper escribe esta sesion (lo fija _spawn_wrapper_
        # process) y señal de canal vivo (True tras recibir wrapper_started;
        # con False el parseo de stdout de supervisor sigue siendo autoritativo).
        self.events_file = None
        self.events_alive = False
        # True mientras el wrapper hace su backup inicial ANTES de lanzar BDS
        # (wrapper_started con initial_backup=True y aun sin bds_launched): en
        # esa ventana no lee stdin y un 'stop' espera en la tuberia hasta que
        # BDS arranca. La fase 1 de lifecycle no cuenta su plazo mientras dure.
        self.wrapper_pre_bds = False
        # True = la ausencia del wrapper es esperada (nunca arranco o alguien
        # pidio pararlo). El watchdog solo trata como crash un wrapper muerto
        # con False; _spawn_wrapper_process lo limpia en cada arranque.
        self.stop_requested = True

    def add_log(self, text: str, log_type: str = "info"):
        timestamp = time.strftime("%H:%M:%S")
        with self.lock:
            self._log_seq += 1
            entry = {"id": self._log_seq, "time": timestamp, "text": text.strip(), "type": log_type}
            self.log_history.append(entry)
            if len(self.log_history) > self.max_log_history:
                self.log_history.pop(0)
        
        # Broadcast vía WebSocket en asyncio (best-effort: ver _schedule_broadcast)
        self._schedule_broadcast({"type": "log", "data": entry})
        # Persistencia (history) y otros suscriptores: fuera del lock, y un
        # sink que falle jamas rompe el logging en vivo.
        for sink in list(self.log_sinks):
            try:
                sink(entry)
            except Exception:
                pass

    def note_backups_changed(self):
        """La lista de backups pudo cambiar: sube backups_revision y lo publica."""
        with self.lock:
            self.backups_revision += 1
        self.update_status()

    def update_status(self):
        status_payload = {
            "type": "status",
            "data": build_public_status(self)
        }
        self._schedule_broadcast(status_payload)

    def _schedule_broadcast(self, message: dict):
        """Agenda el broadcast en el loop vivo (best-effort: NUNCA lanza).

        El loop referenciado puede estar CERRADO (apagado de la GUI, teardown
        de un TestClient que dejo el global stale): run_coroutine_threadsafe
        lanza entonces un RuntimeError SINCRONICO — sin guardia propagaria a
        todo llamante de add_log/update_status desde hilos de fondo (watchdog,
        lectores del wrapper) y dejaria la corrutina huerfana (RuntimeWarning
        "never awaited" al pasar el GC). Ni el logging ni el estado publico
        dependen del broadcast en vivo (la fuente autoritativa es history y
        los eventos NDJSON): el fallo de agendado se descarta cerrando la
        corrutina.
        """
        loop = self.loop
        if loop is None or not self.active_websockets:
            return
        coro = self.broadcast(message)
        try:
            asyncio.run_coroutine_threadsafe(coro, loop)
        except Exception:
            coro.close()

    async def broadcast(self, message: dict):
        disconnected = set()
        for ws in list(self.active_websockets):
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.add(ws)
        for ws in disconnected:
            self.active_websockets.discard(ws)


def build_public_status(manager, players=None):
    """Estado público ÚNICO para /api/status, el init del WS y update_status.

    El hardware se muestrea ANTES de tomar manager.lock (psutil es lento y
    no debe bloquear add_log). `players` permite al init del WS compartir el
    MISMO lock con la lectura de logs (snapshot atómico de ambos); si no se
    pasa, se lee aquí bajo manager.lock.
    """
    hw = get_hardware_metrics()
    with manager.lock:
        if players is None:
            players = list(manager.players_online)
        # Snapshot atomico bajo el mismo lock: antes is_running,
        # backup/update flags, tiempos y version se leian sin lock
        # (lecturas rasgadas en cada poll /api/status e init de WS).
        running = manager.is_running
        last_backup = manager.last_backup_time
        backups_rev = manager.backups_revision
        initial_backup = manager.wrapper_pre_bds
        backup_prog = manager.backup_in_progress
        update_prog = manager.update_in_progress
        suite_update_prog = manager.suite_update_in_progress
        ext_inst = manager.external_instance
        ext_reason = manager.external_instance_reason
        start_time = manager.start_time
        installed = manager.installed_version
    return {
        "suite_version": VERSION,
        "running": running,
        "players": players,
        "player_count": len(players),
        "last_backup": last_backup,
        "backups_revision": backups_rev,
        "backup_in_progress": backup_prog,
        # El wrapper hace su backup inicial y aun no lanzo BDS (el auxiliar de
        # actualizacion de la suite no cuenta ese tiempo como arranque fallido).
        "initial_backup_in_progress": initial_backup,
        "update_in_progress": update_prog,
        "suite_update_in_progress": suite_update_prog,
        "external_instance": ext_inst,
        "external_instance_reason": ext_reason,
        "uptime": int(time.time() - start_time) if (running and start_time) else 0,
        "hardware": hw,
        # Version de BDS capturada en el arranque (evento version_captured);
        # None hasta que el wrapper arranque el servidor.
        "installed_version": installed
    }


# Singleton ÚNICO: los routers/servicios importan esta instancia; nunca
# crear ServerManager por petición (fragmentaría locks, eventos y estado).
manager = ServerManager()
