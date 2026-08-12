"""Router de backups: listado, restauración, descarga, borrado y verificación."""

import os
import time
import zipfile

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

import auto_backup
from console_lang import L
from gui_backend.security import _ensure_local, _check_origin
from gui_backend.services import backups as backups_service
from gui_backend.state import manager

router = APIRouter()


@router.get("/api/backups")
async def list_backups(request: Request):
    _ensure_local(request.client.host if request.client else "")
    return {"backups": backups_service.list_backup_info(auto_backup.BACKUP_DIR)}


@router.post("/api/restore")
async def restore_backup(request: Request):
    """Restaura un backup al mundo. Rechaza si el servidor esta encendido.

    La restauracion (I/O pesada) se ejecuta en un threadpool para no
    bloquear el event loop de los WebSockets.
    """
    _ensure_local(request.client.host if request.client else "")
    _check_origin(request)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Cuerpo JSON invalido")
    filename = (body or {}).get("filename", "")

    if not filename or os.path.basename(filename) != filename:
        raise HTTPException(status_code=400, detail="Nombre de backup invalido")

    if manager.is_running:
        raise HTTPException(
            status_code=409,
            detail="Debes apagar el servidor antes de reestablecer un backup",
        )

    manager.add_log(L(f"[GUI] Restaurando backup: {filename}", f"[GUI] Restoring backup: {filename}"), "backup")

    try:
        restored_path = await run_in_threadpool(backups_service.restore_backup_under_lock, manager, filename)
    except HTTPException:
        # El guard interno (409 si el servidor se encendio) debe propagarse
        # tal cual; no dejarlo caer en el except Exception -> 500.
        raise
    except FileNotFoundError as e:
        manager.add_log(L(f"[GUI] Error al restaurar {filename}: {e}", f"[GUI] Error restoring {filename}: {e}"), "error")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        manager.add_log(L(f"[GUI] Error al restaurar {filename}: {e}", f"[GUI] Error restoring {filename}: {e}"), "error")
        raise HTTPException(status_code=500, detail=str(e))

    manager.add_log(L(f"[GUI] Backup restaurado: {os.path.basename(restored_path)}", f"[GUI] Backup restored: {os.path.basename(restored_path)}"), "backup")
    manager.last_backup_time = time.strftime("%H:%M:%S")
    return {"status": "ok", "backup": filename}


@router.get("/api/backups/{filename}/download")
async def download_backup(filename: str, request: Request):
    """Descarga un backup ZIP ya existente en el directorio de backups.

    Misma validacion de nombre que /api/restore (solo basename, sin
    traversal): el archivo debe estar dentro de BACKUP_DIR.
    """
    _ensure_local(request.client.host if request.client else "")
    _check_origin(request)
    if not filename or os.path.basename(filename) != filename:
        raise HTTPException(status_code=400, detail="Nombre de backup invalido")
    full = os.path.join(auto_backup.BACKUP_DIR, filename)
    if not os.path.isfile(full):
        raise HTTPException(status_code=404, detail="Backup no encontrado")
    return FileResponse(full, filename=filename, media_type="application/zip")


@router.post("/api/backups/{filename}/delete")
async def delete_backup(filename: str, request: Request):
    """Elimina un backup ZIP.

    Rechaza mientras haya un backup en curso (el archivo podria estar
    escribiendose) y con el mismo filtro de nombre que /api/restore.
    """
    _ensure_local(request.client.host if request.client else "")
    _check_origin(request)
    if not filename or os.path.basename(filename) != filename:
        raise HTTPException(status_code=400, detail="Nombre de backup invalido")
    if manager.backup_in_progress:
        raise HTTPException(
            status_code=409,
            detail="Hay un backup en curso; espera a que termine antes de eliminar",
        )
    full = os.path.join(auto_backup.BACKUP_DIR, filename)
    if not os.path.isfile(full):
        raise HTTPException(status_code=404, detail="Backup no encontrado")
    try:
        os.remove(full)
    except OSError as e:
        manager.add_log(L(f"[GUI] Error al eliminar backup {filename}: {e}", f"[GUI] Error deleting backup {filename}: {e}"), "error")
        raise HTTPException(status_code=500, detail=str(e))
    manager.add_log(L(f"[GUI] Backup eliminado: {filename}", f"[GUI] Backup deleted: {filename}"), "backup")
    return {"status": "ok", "backup": filename}


@router.post("/api/backups/{filename}/verify")
async def verify_backup(filename: str, request: Request):
    """Verifica la integridad de un backup ZIP (testzip: CRC de todas las
    entradas). Lento en zips grandes: corre en el threadpool para no bloquear
    el event loop de los WebSockets.
    """
    _ensure_local(request.client.host if request.client else "")
    _check_origin(request)
    if not filename or os.path.basename(filename) != filename:
        raise HTTPException(status_code=400, detail="Nombre de backup invalido")
    full = os.path.join(auto_backup.BACKUP_DIR, filename)
    if not os.path.isfile(full):
        raise HTTPException(status_code=404, detail="Backup no encontrado")

    def _verify():
        return backups_service.verify_zip(full)

    try:
        bad = await run_in_threadpool(_verify)
    except zipfile.BadZipFile as e:
        # Archivo truncado/cabecera rota: es el resultado "corrupto", no un error
        manager.add_log(L(f"[GUI] Backup corrupto: {filename} ({e})", f"[GUI] Corrupt backup: {filename} ({e})"), "error")
        return {"status": "corrupt", "filename": filename, "entry": str(e)}
    except Exception as e:
        manager.add_log(L(f"[GUI] Error al verificar {filename}: {e}", f"[GUI] Error verifying {filename}: {e}"), "error")
        raise HTTPException(status_code=500, detail=str(e))
    if bad:
        manager.add_log(L(f"[GUI] Backup corrupto: {filename} ({bad})", f"[GUI] Corrupt backup: {filename} ({bad})"), "error")
        return {"status": "corrupt", "filename": filename, "entry": bad}
    manager.add_log(L(f"[GUI] Backup verificado: {filename}", f"[GUI] Backup verified: {filename}"), "backup")
    return {"status": "ok", "filename": filename}
