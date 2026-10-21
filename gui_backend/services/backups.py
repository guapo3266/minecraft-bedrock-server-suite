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
from gui_backend import backup_location
import windows_process_guard as wpg
from fastapi import HTTPException
from zip_safety import CORRUPT_MARKERS

# Lista canonica compartida con la rotacion y la CLI (zip_safety, fuente
# unica): lo que la GUI oculta para restaurar, la CLI tambien.
_CORRUPT_MARKERS = CORRUPT_MARKERS


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
    # Un stat por ZIP y tolerante: la rotacion del wrapper (otro proceso)
    # puede borrar uno entre el glob y el stat. Antes el FileNotFoundError
    # convertia GET /api/backups en un 500 (2026-10-20).
    entries = []
    for z in _list_backup_files(backup_dir):
        try:
            st = os.stat(z)
        except OSError:
            continue
        entries.append((st.st_mtime, st.st_size, z))
    entries.sort(key=lambda e: e[0], reverse=True)
    return [
        {
            "filename": os.path.basename(z),
            "size_mb": round(size / (1024 * 1024), 2),
            "date": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime)),
        }
        for mtime, size, z in entries
    ]


def restore_backup_under_lock(manager, filename):
    """Restaura el backup tras re-chequear bajo op_lock (anti TOCTOU).

    Se ejecuta dentro del threadpool (I/O pesada). Si el servidor se encendio
    entre el chequeo del endpoint y la ejecucion real, lanza HTTPException 409
    (el endpoint debe propagarla tal cual, sin convertirla a 500).
    """
    with manager.op_lock:
        # op_lock excluye las operaciones de esta GUI; el mutex de operacion
        # excluye a otros procesos (CLI de restore, otra GUI, el recovery del
        # wrapper) durante TODO el restore. Los chequeos van bajo ambos.
        try:
            with wpg.installation_operation(auto_backup.BASE_DIR):
                if manager.is_running:
                    raise HTTPException(
                        status_code=409,
                        detail="El servidor se encendió durante la restauración; operación cancelada",
                    )
                from gui_backend.services import external_probe
                is_ext, _ = external_probe.detect_external_bds()
                if is_ext:
                    raise HTTPException(
                        status_code=409,
                        detail="Hay una instancia externa del servidor en ejecución; restauración cancelada",
                    )
                return auto_backup.restore_backup(filename)
        except wpg.InstallationBusy as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


def verify_zip(full):
    """testzip del backup: devuelve la entrada corrupta o None."""
    with zipfile.ZipFile(full, "r") as zf:
        bad = zf.testzip()
    return bad


def backup_location_info():
    """Carpeta de backups en uso, la predeterminada y el estado del ajuste."""
    return backup_location.describe(auto_backup.BASE_DIR)


def set_backup_location(manager, root):
    """Guarda la carpeta raiz de los backups (None/"" = predeterminada).

    Bajo op_lock y sin backup en curso: un backup de la GUI a medias o un
    restore leyendo la carpeta vieja no deben ver el cambio. El wrapper lo
    toma en su proximo backup (relee el ajuste). Los backups existentes no se
    mueven: se informa cuantos quedan en la carpeta anterior.
    """
    if manager.backup_in_progress:
        raise HTTPException(status_code=409, detail="backup_in_progress")
    if not manager.op_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="busy")
    try:
        if manager.backup_in_progress:
            raise HTTPException(status_code=409, detail="backup_in_progress")
        previous = backup_location.resolve_backup_dir(auto_backup.BASE_DIR)
        try:
            backup_location.save_root(auto_backup.BASE_DIR, root)
        except backup_location.InvalidBackupRoot as exc:
            raise HTTPException(status_code=400, detail=exc.code) from exc
        info = backup_location.describe(auto_backup.BASE_DIR)
    finally:
        manager.op_lock.release()
    moved = os.path.normcase(previous) != os.path.normcase(info["backup_dir"])
    return {
        "location": info,
        "previous_backup_dir": previous if moved else None,
        "left_behind": len(_list_backup_files(previous)) if moved else 0,
    }
