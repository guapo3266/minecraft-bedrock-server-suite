"""Router de backups: listado, restauración, descarga, borrado y verificación."""

import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

import auto_backup
from console_lang import L
from gui_backend.security import _ensure_local, _check_origin
from zip_safety import is_safe_backup_name
from gui_backend.services import backups as backups_service
from gui_backend.state import manager

router = APIRouter()


@router.get("/api/backups")
async def list_backups(request: Request):
    _ensure_local(request.client.host if request.client else "")
    return {"backups": backups_service.list_backup_info(auto_backup.get_backup_dir())}


@router.get("/api/backups/location")
async def get_backup_location(request: Request):
    """Carpeta donde se guardan los backups de esta instalacion."""
    _ensure_local(request.client.host if request.client else "")
    return await run_in_threadpool(backups_service.backup_location_info)


@router.post("/api/backups/location")
async def set_backup_location(request: Request):
    """Cambia la carpeta raiz de los backups ({"root": ruta | null}).

    Errores con codigo estable en detail (la GUI los traduce): 400 si la ruta
    no sirve, 409 busy/backup_in_progress. Crea la carpeta y prueba a
    escribir en ella (puede ser un disco de red lento: threadpool).
    """
    _ensure_local(request.client.host if request.client else "")
    _check_origin(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Cuerpo JSON invalido")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="cuerpo debe ser un objeto")
    result = await run_in_threadpool(backups_service.set_backup_location, manager, body.get("root"))
    nueva = result["location"]["backup_dir"]
    manager.add_log(L(f"[GUI] Carpeta de backups: {nueva}", f"[GUI] Backup folder: {nueva}"), "backup")
    manager.note_backups_changed()  # la lista pasa a ser la de la carpeta nueva
    return {"status": "ok", **result}


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
    # Un cuerpo valido que no es objeto ([1], "x", 5) daba 500 (AttributeError).
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="cuerpo debe ser un objeto")
    filename = body.get("filename", "")

    if not is_safe_backup_name(filename):
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

    # Restaurar no crea ningun backup: "ultimo backup" no cambia (antes pasaba
    # a la hora actual y aparentaba un backup reciente del mundo restaurado).
    manager.add_log(L(f"[GUI] Backup restaurado: {os.path.basename(restored_path)}", f"[GUI] Backup restored: {os.path.basename(restored_path)}"), "backup")
    return {"status": "ok", "backup": filename}


@router.get("/api/backups/{filename}/download")
async def download_backup(filename: str, request: Request):
    """Descarga un backup ZIP ya existente en el directorio de backups.

    Misma validacion de nombre que /api/restore (solo basename, sin
    traversal): el archivo debe estar dentro de BACKUP_DIR.
    """
    _ensure_local(request.client.host if request.client else "")
    _check_origin(request)
    sec_fetch_site = request.headers.get("sec-fetch-site", "").lower()
    if sec_fetch_site == "cross-site":
        raise HTTPException(status_code=403, detail="Descarga cross-site rechazada")
    if not is_safe_backup_name(filename):
        raise HTTPException(status_code=400, detail="Nombre de backup invalido")
    full = os.path.join(auto_backup.get_backup_dir(), filename)
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
    if not is_safe_backup_name(filename):
        raise HTTPException(status_code=400, detail="Nombre de backup invalido")
    if manager.backup_in_progress:
        raise HTTPException(
            status_code=409,
            detail="Hay un backup en curso; espera a que termine antes de eliminar",
        )
    full = os.path.join(auto_backup.get_backup_dir(), filename)
    if not os.path.isfile(full):
        raise HTTPException(status_code=404, detail="Backup no encontrado")
    try:
        os.remove(full)
    except OSError as e:
        manager.add_log(L(f"[GUI] Error al eliminar backup {filename}: {e}", f"[GUI] Error deleting backup {filename}: {e}"), "error")
        raise HTTPException(status_code=500, detail=str(e))
    manager.add_log(L(f"[GUI] Backup eliminado: {filename}", f"[GUI] Backup deleted: {filename}"), "backup")
    manager.note_backups_changed()  # otras pestanas abiertas tambien lo ven
    return {"status": "ok", "backup": filename}


@router.post("/api/backups/{filename}/verify")
async def verify_backup(filename: str, request: Request):
    """Verifica la integridad de un backup ZIP (lee y descomprime todas las
    entradas: CRC, deflate y truncado). Lento en zips grandes: corre en el
    threadpool para no bloquear el event loop de los WebSockets.
    """
    _ensure_local(request.client.host if request.client else "")
    _check_origin(request)
    if not is_safe_backup_name(filename):
        raise HTTPException(status_code=400, detail="Nombre de backup invalido")
    full = os.path.join(auto_backup.get_backup_dir(), filename)
    if not os.path.isfile(full):
        raise HTTPException(status_code=404, detail="Backup no encontrado")

    def _verify():
        return backups_service.verify_zip(full)

    try:
        # Cabecera rota, CRC, deflate danado o truncado vuelven como "corrupto"
        # (zip_safety.check_zip_integrity); solo la E/S fallida es un error.
        bad = await run_in_threadpool(_verify)
    except Exception as e:
        manager.add_log(L(f"[GUI] Error al verificar {filename}: {e}", f"[GUI] Error verifying {filename}: {e}"), "error")
        raise HTTPException(status_code=500, detail=str(e))
    if bad:
        manager.add_log(L(f"[GUI] Backup corrupto: {filename} ({bad})", f"[GUI] Corrupt backup: {filename} ({bad})"), "error")
        return {"status": "corrupt", "filename": filename, "entry": bad}
    manager.add_log(L(f"[GUI] Backup verificado: {filename}", f"[GUI] Backup verified: {filename}"), "backup")
    return {"status": "ok", "filename": filename}
