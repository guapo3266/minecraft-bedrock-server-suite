"""Gestión de backups ZIP: listado, restauración bajo guard, verificación.

Funciones puras: reciben rutas/estado por parámetro y no conocen Request,
FastAPI ni decoradores (HTTPException solo como error de dominio). Los logs
los emiten los endpoints/routers.
"""

import glob
import os
import time
import zipfile

import auto_backup
from fastapi import HTTPException

_CORRUPT_MARKERS = ("_CORRUPTO", "_EXCEDIDO")


def _list_backup_files(backup_dir):
    """Zips de backup visibles para restauracion.

    Excluye los marcados como corruptos/excedidos (mismos criterios que
    auto_backup.rotate_backups): restaurar un backup corrupto siempre falla.
    """
    return [
        z for z in glob.glob(os.path.join(backup_dir, "*.zip"))
        if not any(marker in os.path.basename(z) for marker in _CORRUPT_MARKERS)
    ]


def list_backup_info(backup_dir):
    """[{"filename", "size_mb", "date"}] ordenado por mtime desc.

    Devuelve [] si el directorio de backups no existe.
    """
    if not os.path.exists(backup_dir):
        return []
    zips = _list_backup_files(backup_dir)
    backups_info = []
    for z in sorted(zips, key=os.path.getmtime, reverse=True):
        size_mb = round(os.path.getsize(z) / (1024 * 1024), 2)
        mtime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(z)))
        backups_info.append({
            "filename": os.path.basename(z),
            "size_mb": size_mb,
            "date": mtime
        })
    return backups_info


def restore_backup_under_lock(manager, filename):
    """Restaura el backup tras re-chequear bajo op_lock (anti TOCTOU).

    Se ejecuta dentro del threadpool (I/O pesada). Si el servidor se encendio
    entre el chequeo del endpoint y la ejecucion real, lanza HTTPException 409
    (el endpoint debe propagarla tal cual, sin convertirla a 500).
    """
    with manager.op_lock:
        if manager.is_running:
            raise HTTPException(
                status_code=409,
                detail="El servidor se encendió durante la restauración; operación cancelada",
            )
        return auto_backup.restore_backup(filename)


def verify_zip(full):
    """testzip del backup: devuelve la entrada corrupta o None."""
    with zipfile.ZipFile(full, "r") as zf:
        bad = zf.testzip()
    return bad
