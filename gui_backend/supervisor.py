"""Supervisión del proceso server_wrapper.py y consumo de su stdout.

Este módulo es el ÚNICO dueño del subproceso del wrapper (spawn + hilo lector).
Los routers/servicios nunca lanzan procesos directamente.
"""

import os
import re
import subprocess
import sys
import time

from console_lang import L
# D5: patrones de deteccion del log de BDS centralizados en server_wrapper
from server_wrapper import _RE_PLAYER_CONNECT, _RE_PLAYER_DISCONNECT

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
    return process


def classify_log_line(line_str: str) -> str:
    """Determina el tipo de log ('join', 'leave', 'backup', 'error', 'info') para coloreado en la GUI."""
    if _RE_PLAYER_CONNECT.search(line_str):
        return "join"
    if _RE_PLAYER_DISCONNECT.search(line_str):
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

        # Leer stdout en tiempo real
        for line in iter(process.stdout.readline, ''):
            if not line:
                break
            
            line_str = line.strip()
            if not line_str:
                continue

            # FIX F1: capturar la version instalada real desde el log de BDS
            # ("Version: 1.26.33.2"); se usa en /api/check_update
            m_ver = re.search(r"Version:\s*(\d+\.\d+\.\d+\.\d+)", line_str)
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
            m_conn = _RE_PLAYER_CONNECT.search(line_str)
            m_disc = _RE_PLAYER_DISCONNECT.search(line_str)
            if m_conn:
                try:
                    name = m_conn.group(1).strip()
                    if not name:
                        raise ValueError("nombre de jugador ausente")
                    with manager.lock:
                        manager.players_online.add(name)
                    manager.update_status()
                except Exception:
                    pass
            elif m_disc:
                try:
                    name = m_disc.group(1).strip()
                    if not name:
                        raise ValueError("nombre de jugador ausente")
                    with manager.lock:
                        manager.players_online.discard(name)
                    manager.update_status()
                except Exception:
                    pass

            # La clasificacion vive en classify_log_line (unica fuente de
            # verdad); aqui solo se maneja la maquina de estados de backups.
            if log_type == "backup":
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
        with manager.lock:
            manager.players_online.clear()
        manager.wrapper_exit_event.set()
        # G8: respaldo: si el hilo muere, BDS ya no corre.
        manager.server_stopped_event.set()
        manager.add_log(L("[GUI Backend] Servidor de Minecraft detenido.", "[GUI Backend] Minecraft server stopped."), "system")
        manager.update_status()
