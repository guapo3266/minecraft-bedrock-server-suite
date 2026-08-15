"""Sonda pasiva para detección de instancias externas de BDS o del wrapper.

Permite a la GUI detectar si BDS o el wrapper están corriendo por fuera de la GUI
(por ejemplo, lanzado directamente desde consola o por otra ventana).
"""

import os
import psutil
from console_lang import L
import windows_process_guard as wpg
from gui_backend import config
from gui_backend.state import manager


def _is_descendant(proc: psutil.Process, parent_pid: int) -> bool:
    """Verifica recursivamente si `proc` es hijo o descendiente de `parent_pid`."""
    try:
        curr = proc.parent()
        while curr is not None:
            if curr.pid == parent_pid:
                return True
            curr = curr.parent()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return False


def detect_external_bds(base_dir: str = None) -> tuple[bool, str | None]:
    """Detecta si hay una instancia externa de BDS o del wrapper en ejecución.

    Solo reporta externa si el servidor NO está corriendo bajo control de la GUI
    (`manager.is_running is False`).
    """
    if manager.is_running:
        return False, None

    target_base = base_dir or config.BASE_DIR

    # 1. Comprobar si el NamedMutex del wrapper ya está tomado por otra instancia
    mutex_name = f"BDS_Wrapper_{wpg.get_installation_hash(target_base)}"
    probe_mutex = wpg.NamedMutex(mutex_name)
    already_exists = probe_mutex.already_exists
    probe_mutex.close()

    if already_exists:
        return True, "wrapper_mutex"

    # 2. Comprobar vía psutil procesos de bedrock_server que no sean descendientes de la GUI
    gui_pid = os.getpid()
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if name in ("bedrock_server.exe", "bedrock_server"):
                p = psutil.Process(proc.info["pid"])
                if p.pid != gui_pid and not _is_descendant(p, gui_pid):
                    return True, f"bedrock_server_pid_{p.pid}"
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    return False, None


def update_external_instance_state():
    """Actualiza el estado de external_instance en el manager singleton."""
    is_ext, reason = detect_external_bds()
    with manager.lock:
        changed = (manager.external_instance != is_ext or manager.external_instance_reason != reason)
        manager.external_instance = is_ext
        manager.external_instance_reason = reason
    if changed:
        manager.update_status()
    return is_ext, reason
