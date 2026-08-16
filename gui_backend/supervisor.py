"""Supervisión del proceso server_wrapper.py y consumo de su stdout.

Este módulo es el ÚNICO dueño del subproceso del wrapper (spawn + hilo lector).
Los routers/servicios nunca lanzan procesos directamente.
"""

import json
import os
import re
import subprocess
import sys
import threading
import time

from console_lang import L
# D5: patrones de deteccion del log de BDS centralizados en server_wrapper
from server_wrapper import _RE_PLAYER_CONNECT, _RE_PLAYER_DISCONNECT, _strip_log_prefix

from gui_backend import config
from gui_backend.state import manager


def _spawn_wrapper_process():
    """Crea el subproceso del wrapper (server_wrapper.py).

    FIX G1: se llama SIEMPRE bajo op_lock desde start/restart, de modo que
    manager.wrapper_process existe antes de liberar el lock: update_bds y
    restore ya no pueden ver is_running=True con wrapper_process=None y
    saltarse la detencion del servidor.
    """
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    # Canal de eventos NDJSON de este boot del wrapper. Solo se computa el
    # path (el wrapper crea el directorio): los tests que ejecutan este spawn
    # real con Popen parcheado no generan efectos en disco.
    events_file = os.path.join(
        config.BASE_DIR, "data", "wrapper_events",
        "be_%d_%s.ndjson" % (int(time.time() * 1000), os.urandom(4).hex()),
    )
    env["WRAPPER_EVENTS_FILE"] = events_file
    process = subprocess.Popen(
        [sys.executable, "-u", os.path.join(config.BASE_DIR, "server_wrapper.py")],
        cwd=config.BASE_DIR,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    # Limpia el estado de salida anterior antes de liberar op_lock. Si no,
    # update_bds puede ver un proceso nuevo pero un evento todavía marcado
    # como terminado y continuar sin esperar su cierre.
    manager.wrapper_exit_event.clear()
    # G8: un wrapper nuevo significa BDS (potencialmente) vivo otra vez.
    manager.server_stopped_event.clear()
    # El wrapper arranca a peticion de alguien: su futura salida solo es
    # crash (para el watchdog) si nadie pidio pararlo.
    manager.stop_requested = False
    # Canal de eventos de la sesion nueva (events_alive lo activa el lector
    # al recibir wrapper_started; hasta entonces rige el parseo de stdout).
    manager.events_file = events_file
    manager.events_alive = False
    return process


def classify_log_line(line_str: str) -> str:
    """Determina el tipo de log ('join', 'leave', 'backup', 'error', 'info') para coloreado en la GUI."""
    clean = _strip_log_prefix(line_str).strip()
    if clean.startswith("<"):
        return "info"
    if _RE_PLAYER_CONNECT.search(clean):
        return "join"
    if _RE_PLAYER_DISCONNECT.search(clean):
        return "leave"
    if any(k in line_str.lower() for k in ("backup", "compres", "save query")):
        # FIX F2: "compres" es el prefijo comun de "compression"/"compresion":
        # no debe excluir la linea del worker ("Starting compression in a
        # separate process...", sin la palabra "backup").
        return "backup"
    if ("ERROR" in line_str or "WARN" in line_str
            or "Exception" in line_str or "Excepcion" in line_str or "Excepción" in line_str):
        return "error"
    return "info"


def run_wrapper_thread(process=None):
    """Hilo que consume el stdout del wrapper y mantiene el estado de la GUI.

    `process` es el subproceso ya creado bajo op_lock (FIX G1); si es None
    (flujo legacy), el hilo lo crea el mismo.
    """

    # Cada arranque debe volver a descubrir la versión del proceso actual.
    manager.installed_version = None
    manager.events_alive = False  # lo activa el lector con wrapper_started
    manager.add_log(L("[GUI Backend] Iniciando wrapper de Minecraft Bedrock...", "[GUI Backend] Starting Minecraft Bedrock wrapper..."), "system")
    manager.wrapper_exit_event.clear()
    manager.server_stopped_event.clear()
    manager.is_running = True
    manager.start_time = time.time()
    manager.update_status()

    try:
        if process is None:
            process = _spawn_wrapper_process()
        manager.wrapper_process = process
        events_file = manager.events_file
        if events_file:
            threading.Thread(target=_tail_events, args=(events_file,), daemon=True, name="wrapper-events").start()

        # Leer stdout en tiempo real
        for line in iter(process.stdout.readline, ''):
            if not line:
                break

            line_str = line.strip()
            if not line_str:
                continue

            # FIX F1: capturar la version instalada real desde el log de BDS
            # ("Version: 1.26.33.2"); se usa en /api/check_update. Con el canal
            # de eventos vivo, la fuente autoritativa es version_captured.
            m_ver = re.search(r"Version:\s*(\d+\.\d+\.\d+\.\d+)", line_str) if not manager.events_alive else None
            if m_ver:
                manager.installed_version = m_ver.group(1)

            # G8: BDS confirmado detenido. El wrapper lo anuncia al empezar su
            # limpieza final; en ese momento el mundo ya está quieto, aunque el
            # proceso del wrapper siga vivo haciendo el backup de cierre.
            # (Marcador bilingue: la consola adapta el texto al idioma GUI.)
            if "BDS stopped" in line_str or "BDS detenido" in line_str:
                manager.server_stopped_event.set()

            # Determinar tipo de log para coloreado en la GUI
            log_type = classify_log_line(line_str)
            clean_str = _strip_log_prefix(line_str).strip()
            is_chat = clean_str.startswith("<")
            m_conn = _RE_PLAYER_CONNECT.search(clean_str) if not is_chat else None
            m_disc = _RE_PLAYER_DISCONNECT.search(clean_str) if not is_chat else None
            if m_conn and not manager.events_alive:
                try:
                    name = m_conn.group(1).strip()
                    if not name:
                        raise ValueError("nombre de jugador ausente")
                    with manager.lock:
                        manager.players_online.add(name)
                        manager.players_xuid[name] = m_conn.group(2)
                    record_player_event(name, m_conn.group(2))
                    for sink in list(manager.player_event_sinks):
                        try:
                            sink(name, m_conn.group(2), True)
                        except Exception:
                            pass
                    manager.update_status()
                except Exception:
                    pass
            elif m_disc and not manager.events_alive:
                try:
                    name = m_disc.group(1).strip()
                    if not name:
                        raise ValueError("nombre de jugador ausente")
                    with manager.lock:
                        manager.players_online.discard(name)
                    record_player_event(name)
                    for sink in list(manager.player_event_sinks):
                        try:
                            sink(name, m_disc.group(2), False)
                        except Exception:
                            pass
                    manager.update_status()
                except Exception:
                    pass

            # La clasificacion vive en classify_log_line (unica fuente de
            # verdad); aqui solo se maneja la maquina de estados de backups.
            # Con el canal de eventos vivo, los flags los mueven los eventos
            # (backup_compress_started/ok/finished); los marcadores de stdout
            # quedan como fallback (wrapper viejo o canal muerto).
            if log_type == "backup" and not manager.events_alive:
                # la cadena debe coincidir EXACTA con la del wrapper (bilingue)
                if ("Starting compression in a separate process" in line_str
                        or "Iniciando compresion de archivos en proceso separado" in line_str):
                    manager.backup_in_progress = True
                    manager.update_status()
                elif ("Compression successful" in line_str or "Compresión exitosa" in line_str
                      or "Backup completed" in line_str or "Backup completado" in line_str):
                    manager.backup_in_progress = False
                    manager.last_backup_time = time.strftime("%H:%M:%S")
                    manager.update_status()
                elif "Backup finished" in line_str or "Backup finalizado" in line_str:
                    # H3: fin incondicional del ciclo de compresion (exito,
                    # fallo, timeout, watchdog o excepcion). Sin este reset el
                    # flag quedaba en True tras un backup fallido y el boton de
                    # backup en frio quedaba bloqueado hasta reiniciar la GUI.
                    manager.backup_in_progress = False
                    manager.update_status()

            manager.add_log(line_str, log_type)

        process.wait()

    except Exception as e:
        manager.add_log(L(f"[GUI Backend] Error en el wrapper: {e}", f"[GUI Backend] Error in the wrapper: {e}"), "error")
    finally:
        manager.is_running = False
        manager.backup_in_progress = False
        manager.wrapper_process = None
        manager.events_alive = False
        with manager.lock:
            manager.players_online.clear()
        manager.wrapper_exit_event.set()
        # G8: respaldo: si el hilo muere, BDS ya no corre.
        manager.server_stopped_event.set()
        manager.add_log(L("[GUI Backend] Servidor de Minecraft detenido.", "[GUI Backend] Minecraft server stopped."), "system")
        manager.update_status()


# ═══════════════════════════════════════════════════════════════
# Canal de eventos NDJSON del wrapper (IPC estructurada)
# ───────────────────────────────────────────────────────────────
# El wrapper escribe eventos JSON en data/wrapper_events/<boot>.ndjson
# (path via env WRAPPER_EVENTS_FILE). Mientras el canal este vivo
# (wrapper_started recibido -> manager.events_alive), estos eventos son
# la fuente AUTORITATIVA del estado y el parseo de stdout queda como
# fallback. Contrato completo: docs/INFORME_IPC_EVENTOS_NDJSON.md
# ═══════════════════════════════════════════════════════════════
def _apply_event(ev):
    """Aplica un evento del canal al estado del manager (nunca lanza)."""
    event = ev.get("event")
    if event == "wrapper_started":
        manager.events_alive = True
    elif event == "version_captured":
        manager.installed_version = ev.get("version")
    elif event == "server_stopped":
        manager.server_stopped_event.set()
    elif event == "shutdown_initiated":
        manager.add_log(L(f"[Wrapper] Apagado iniciado ({ev.get('reason')}).", f"[Wrapper] Shutdown initiated ({ev.get('reason')})."), "system")
    elif event == "player_connected":
        name = str(ev.get("name") or "").strip()
        xuid = str(ev.get("xuid") or "") or None
        if name:
            try:
                with manager.lock:
                    manager.players_online.add(name)
                    if xuid:
                        manager.players_xuid[name] = xuid
                record_player_event(name, xuid)
                for sink in list(manager.player_event_sinks):
                    try:
                        sink(name, xuid, True)
                    except Exception:
                        pass
                manager.update_status()
            except Exception:
                pass
    elif event == "player_disconnected":
        name = str(ev.get("name") or "").strip()
        if name:
            try:
                with manager.lock:
                    manager.players_online.discard(name)
                record_player_event(name)
                for sink in list(manager.player_event_sinks):
                    try:
                        sink(name, None, False)
                    except Exception:
                        pass
                manager.update_status()
            except Exception:
                pass
    elif event == "backup_compress_started":
        manager.backup_in_progress = True
        manager.update_status()
    elif event == "backup_ok":
        manager.backup_in_progress = False
        manager.last_backup_time = time.strftime("%H:%M:%S")
        manager.update_status()
    elif event == "backup_finished":
        # H3: fin incondicional del ciclo (success/failed/timeout/watchdog/
        # launch_error/exception viaja en ev["outcome"])
        manager.backup_in_progress = False
        manager.update_status()
    # eventos desconocidos: ignorados (compatibilidad futura)


def _tail_events(path):
    """Hilo lector del canal NDJSON: consume lineas y las aplica.

    Abre tolerante (el archivo aparece cuando el wrapper arranca), tolerea
    lineas corruptas, drena lo pendiente tras la muerte del wrapper y
    termina cuando wrapper_exit_event esta set y no queda nada por leer.
    """
    handle = None
    try:
        while True:
            if handle is None:
                try:
                    handle = open(path, "r", encoding="utf-8")
                except OSError:
                    if manager.wrapper_exit_event.is_set():
                        return
                    time.sleep(0.2)
                    continue
            line = handle.readline()
            if not line:
                if manager.wrapper_exit_event.is_set():
                    return
                time.sleep(0.2)
                continue
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if isinstance(ev, dict):
                try:
                    _apply_event(ev)
                except Exception:
                    pass
    finally:
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass


# Registro de jugadores conocidos (data/known_players.json): name -> xuid +
# primera/ultima vez visto. Lo alimenta run_wrapper_thread desde los eventos
# de conexion/desconexion; la GUI lo lee en GET /api/players. Es dato propio
# de la instalacion (como setup_done.json), no se sincroniza.
KNOWN_PLAYERS_PATH = os.path.join(config.BASE_DIR, "data", "known_players.json")
_known_players_lock = threading.Lock()


def load_known_players():
    """Lee el registro; ante cualquier problema devuelve {} sin lanzar."""
    try:
        with open(KNOWN_PLAYERS_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def record_player_event(name, xuid=None):
    """Actualiza el registro tras un evento de jugador (escritura atomica)."""
    if not name:
        return
    try:
        with _known_players_lock:
            registry = load_known_players()
            entry = registry.get(name) if isinstance(registry.get(name), dict) else {}
            if not entry:
                entry["first_seen"] = time.strftime("%Y-%m-%d %H:%M:%S")
            if xuid:
                entry["xuid"] = str(xuid)
            entry["last_seen"] = time.strftime("%Y-%m-%d %H:%M:%S")
            registry[name] = entry
            os.makedirs(os.path.dirname(KNOWN_PLAYERS_PATH), exist_ok=True)
            tmp_path = KNOWN_PLAYERS_PATH + ".tmp_" + os.urandom(4).hex()
            try:
                with open(tmp_path, "w", encoding="utf-8", newline="") as f:
                    json.dump(registry, f, indent=2, ensure_ascii=False)
                    f.write("\n")
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, KNOWN_PLAYERS_PATH)
            finally:
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
    except OSError:
        pass
