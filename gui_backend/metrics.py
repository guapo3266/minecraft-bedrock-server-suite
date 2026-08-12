"""Métricas de hardware de la GUI, el wrapper y BDS (RAM, CPU, disco)."""

import os

import psutil

from gui_backend import config

# Caché de objetos psutil.Process por PID. Necesaria para que cpu_percent(interval=None)
# tenga baseline entre muestras (con objeto nuevo SIEMPRE devuelve 0.0). Se recrea el
# objeto si el PID cambia (p. ej. al reiniciar BDS o el wrapper).
_process_cache = {}


def _measure_process_tree():
    """Mide RAM y CPU acumuladas de todo lo relacionado al servidor:
    la propia GUI (server_gui_server.py), el wrapper (server_wrapper.py) y
    bedrock_server.exe (+ cualquier subproceso del wrapper, p. ej. compresión de backups).

    Devuelve (ram_mb_total, raw_cpu_por_nucleo)."""
    # PIDs del árbol: la GUI + todos sus descendientes recursivos (wrapper, BDS, compresión)
    pids = {os.getpid()}
    try:
        for child in psutil.Process(os.getpid()).children(recursive=True):
            try:
                pids.add(child.pid)
            except psutil.NoSuchProcess:
                pass
    except psutil.NoSuchProcess:
        pass

    # Limpiar de la caché los procesos que ya no existen
    for pid in list(_process_cache):
        if pid not in pids:
            _process_cache.pop(pid, None)

    ram_mb = 0.0
    raw_cpu = 0.0
    for pid in pids:
        try:
            proc = _process_cache.get(pid)
            if proc is None:
                proc = psutil.Process(pid)
                _process_cache[pid] = proc
            raw_cpu += proc.cpu_percent(interval=None)
            ram_mb += proc.memory_info().rss / (1024 * 1024)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            _process_cache.pop(pid, None)

    return ram_mb, raw_cpu


def get_hardware_metrics():
    """Mide RAM y CPU de todo lo relacionado al servidor (GUI + wrapper + BDS).
    CPU normalizada como % de la capacidad total de la máquina (igual que el
    Administrador de Tareas de Windows)."""
    sys_mem = psutil.virtual_memory()
    total_ram_gb = round(sys_mem.total / (1024**3), 1)
    system_used_gb = round(sys_mem.used / (1024**3), 1)
    system_available_gb = round(sys_mem.available / (1024**3), 1)
    system_used_pct = round(sys_mem.percent, 1)
    num_cores = psutil.cpu_count() or 1

    ram_mb, raw_cpu = _measure_process_tree()

    bds_ram_mb = round(ram_mb, 1)
    bds_ram_pct = round((ram_mb * 1024 * 1024 / sys_mem.total) * 100, 2)
    # psutil devuelve % por núcleo (puede superar 100); dividir entre núcleos
    # lo normaliza a % de la capacidad total de la máquina.
    bds_cpu_pct = round(raw_cpu / num_cores, 1)

    # Disco: el volumen donde viven el servidor y los backups (C:).
    disk = psutil.disk_usage(config.BASE_DIR)
    disk_total_gb = round(disk.total / (1024**3), 1)
    disk_free_gb = round(disk.free / (1024**3), 1)
    disk_used_pct = round(disk.percent, 1)

    return {
        "ram_mb": bds_ram_mb,
        "ram_pct": bds_ram_pct,
        "cpu_pct": bds_cpu_pct,
        "total_ram_gb": total_ram_gb,
        "system_used_gb": system_used_gb,
        "system_available_gb": system_available_gb,
        "system_used_pct": system_used_pct,
        "disk_total_gb": disk_total_gb,
        "disk_free_gb": disk_free_gb,
        "disk_used_pct": disk_used_pct
    }
