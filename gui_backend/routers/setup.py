"""Router del setup inicial (first-run wizard)."""

import json
import os
import threading
import time

from fastapi import APIRouter, HTTPException, Request

from console_lang import L
from gui_backend import config
from gui_backend.security import _ensure_local, _check_origin
from gui_backend.services import setup as setup_service
from gui_backend.services import bds_update as bds_update_service
from gui_backend.state import manager

router = APIRouter()


@router.get("/api/setup_status")
async def get_setup_status(request: Request):
    """Estado del setup inicial para el frontend: si hay que mostrar el wizard."""
    _ensure_local(request.client.host if request.client else "")
    return {
        "required": setup_service._setup_required(),
        "bds_installed": os.path.exists(config.SERVER_EXE),
    }


@router.post("/api/setup/install_bds")
async def setup_install_bds(request: Request):
    """Instala el BDS oficial desde cero (instalacion nueva, sin servidor).

    Reusa el pipeline de actualizacion (_download_and_install_bds) bajo
    op_lock; rechaza con 409 si el servidor esta corriendo y con 'busy' si
    hay otra operacion en curso. El progreso se sigue por los logs ([Setup]).
    """
    _ensure_local(request.client.host if request.client else "")
    _check_origin(request)
    if manager.is_running:
        raise HTTPException(status_code=409, detail="El servidor esta en ejecucion; detenlo antes de instalar")
    if not manager.op_lock.acquire(blocking=False):
        return {"status": "busy", "message": "Operación en curso (actualización/restauración/backup)"}

    def do_install():
        try:
            manager.add_log(L("[Setup] Iniciando instalacion de Bedrock Dedicated Server...", "[Setup] Starting Bedrock Dedicated Server installation..."), "system")
            ok, version = bds_update_service._download_and_install_bds(tag="[Setup]")
            if ok:
                manager.add_log(L(f"[Setup] BDS instalado correctamente (v{version}).", f"[Setup] BDS installed successfully (v{version})."), "system")
            else:
                manager.add_log(L("[Setup] No se pudo completar la instalacion (sin red o descarga invalida). Revisa los mensajes anteriores y reintenta.", "[Setup] The installation could not be completed (no network or invalid download). Check the previous messages and retry."), "error")
        except Exception as e:
            manager.add_log(L(f"[Setup] Error durante la instalacion: {e}", f"[Setup] Error during installation: {e}"), "error")
        finally:
            manager.op_lock.release()

    threading.Thread(target=do_install, daemon=True).start()
    return {"status": "install_dispatched"}


@router.post("/api/setup/complete")
async def complete_setup(request: Request):
    """Marca el setup inicial como completado (escribe el marcador)."""
    _ensure_local(request.client.host if request.client else "")
    _check_origin(request)
    if not os.path.exists(config.SERVER_EXE):
        raise HTTPException(status_code=409, detail="Instala BDS antes de finalizar el setup")
    try:
        os.makedirs(os.path.dirname(config.SETUP_MARKER), exist_ok=True)
        with open(config.SETUP_MARKER, "w", encoding="utf-8") as f:
            json.dump({"completed": True, "at": time.strftime("%Y-%m-%d %H:%M:%S")}, f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No se pudo escribir el marcador de setup: {e}")
    manager.add_log(L("[Setup] Configuracion inicial completada.", "[Setup] Initial setup completed."), "system")
    return {"status": "ok"}
