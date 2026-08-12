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


class ServerManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.wrapper_process = None
        self.is_running = False
        self.players_online = set()
        self.log_history = []
        self.max_log_history = 500
        self._log_seq = 0  # id secuencial estable para React keys (filtros/streaming)
        self.start_time = None
        self.last_backup_time = "Ninguno"
        self.backup_in_progress = False
        self.update_in_progress = False
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

    def add_log(self, text: str, log_type: str = "info"):
        timestamp = time.strftime("%H:%M:%S")
        with self.lock:
            self._log_seq += 1
            entry = {"id": self._log_seq, "time": timestamp, "text": text.strip(), "type": log_type}
            self.log_history.append(entry)
            if len(self.log_history) > self.max_log_history:
                self.log_history.pop(0)
        
        # Broadcast vía WebSocket en asyncio
        if self.loop and self.active_websockets:
            asyncio.run_coroutine_threadsafe(self.broadcast({"type": "log", "data": entry}), self.loop)

    def update_status(self):
        status_payload = {
            "type": "status",
            "data": build_public_status(self)
        }
        if self.loop and self.active_websockets:
            asyncio.run_coroutine_threadsafe(self.broadcast(status_payload), self.loop)

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
    if players is None:
        with manager.lock:
            players = list(manager.players_online)
    return {
        "running": manager.is_running,
        "players": players,
        "player_count": len(players),
        "last_backup": manager.last_backup_time,
        "backup_in_progress": manager.backup_in_progress,
        "update_in_progress": manager.update_in_progress,
        "uptime": int(time.time() - manager.start_time) if (manager.is_running and manager.start_time) else 0,
        "hardware": hw
    }


# Singleton ÚNICO: los routers/servicios importan esta instancia; nunca
# crear ServerManager por petición (fragmentaría locks, eventos y estado).
manager = ServerManager()
