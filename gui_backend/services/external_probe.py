"""Sonda pasiva para detección de instancias externas de BDS o del wrapper.

Permite a la GUI detectar si BDS o el wrapper están corriendo por fuera de la GUI
(por ejemplo, lanzado directamente desde consola o por otra ventana).
"""

import os
import time

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


def _wrapper_mutex_held_by_other(mutex_name: str) -> bool:
    """True si OTRO proceso RETIENE el mutex del wrapper.

    El sondeo es por ADQUISICION, no por existencia: el probe por existencia
    (CreateMutexW + ERROR_ALREADY_EXISTS) daba falsos positivos porque
    cualquier otra instancia sondeando el mismo mutex lo tiene abierto un
    instante (p. ej. el loop de metricas de otra GUI de esta misma
    instalacion) y el probe ajeno ve 'ya existe': start/update/restore
    quedaban bloqueados con 409 sin haber wrapper real. El wrapper retiene el
    mutex desde el arranque hasta morir, asi que solo un acquire que sigue
    fallando tras un reintento corto (una colision entre dos probes se
    libera en microsegundos) indica una instancia externa real.
    """
    probe = wpg.NamedMutex(mutex_name)
    try:
        for _attempt in range(2):
            if probe.acquire(timeout_ms=0):
                probe.release()
                return False
            time.sleep(0.05)
        return True
    finally:
        probe.close()


def detect_external_bds(base_dir: str = None) -> tuple[bool, str | None]:
    """Detecta si hay una instancia externa de BDS o del wrapper en ejecución.

    Solo reporta externa si el servidor NO está corriendo bajo control de la GUI
    (`manager.is_running is False`).
    """
    if manager.is_running:
        return False, None

    target_base = base_dir or config.BASE_DIR

    # 1. Comprobar si el NamedMutex del wrapper está retenido por otra instancia
    mutex_name = f"BDS_Wrapper_{wpg.get_installation_hash(target_base)}"
    if _wrapper_mutex_held_by_other(mutex_name):
        return True, "wrapper_mutex"

    # 2. Comprobar vía psutil procesos de bedrock_server DE ESTA INSTALACIÓN
    #    (misma ruta del ejecutable) que no sean descendientes de la GUI.
    #    Antes se reportaba cualquier bedrock_server.exe de la máquina: un BDS
    #    de otra instalación bloqueaba start/update/restore de esta (falso
    #    positivo que lifecycle.restart_wrapper ya tenía que esquivar).
    gui_pid = os.getpid()
    target_exe = os.path.normcase(os.path.abspath(os.path.join(target_base, "bedrock_server.exe")))
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if name in ("bedrock_server.exe", "bedrock_server"):
                p = psutil.Process(proc.info["pid"])
                if p.pid != gui_pid and not _is_descendant(p, gui_pid):
                    try:
                        exe = os.path.normcase(os.path.abspath(p.exe()))
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                    if exe == target_exe:
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
