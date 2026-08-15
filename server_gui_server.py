"""
server_gui_server.py — Punto de entrada de la GUI Bedrock Wrapper
=================================================================
Crea la app FastAPI (create_app), monta estáticos, arranca el lifespan
(recuperación de actualizaciones + métricas) y sirve por Uvicorn en loopback.

Los endpoints y el protocolo WebSocket viven en gui_backend/routers/;
la lógica de dominio en gui_backend/services/ y el estado/locks en
gui_backend/state.py. Este módulo conserva solo los re-exports que los
tests/herramientas aún importan desde aquí (ver docs/ARCHITECTURE.md).
"""

import asyncio
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import uvicorn

import auto_backup
from console_lang import L

from gui_backend import config
from gui_backend.config import BASE_DIR
from gui_backend.security import _ensure_local, _is_allowed_origin, _is_safe_zip_entry
from gui_backend.metrics import get_hardware_metrics
from gui_backend.state import manager
from gui_backend.services import external_probe as external_probe_service
from gui_backend.services import bds_update as bds_update_service
from gui_backend.routers import system, properties, setup, actions, backups, websocket


async def hardware_metrics_loop():
    while True:
        try:
            external_probe_service.update_external_instance_state()
            manager.update_status()
        except Exception:
            pass
        await asyncio.sleep(2.0)

@asynccontextmanager
async def lifespan(app: FastAPI):
    manager.loop = asyncio.get_running_loop()
    try:
        auto_backup.recover_interrupted_restores(config.BASE_DIR)
    except Exception as exc:
        manager.add_log(L(f"[Backups] Error en recuperación de restauraciones: {exc}", f"[Backups] Error in restore recovery: {exc}"), "error")
    try:
        bds_update_service.recover_interrupted_updates()
    except Exception as exc:
        manager.add_log(L(f"[Actualizador BDS] No se pudo revisar una actualizacion interrumpida: {exc}", f"[Actualizador BDS] Could not check for an interrupted update: {exc}"), "error")
    task = asyncio.create_task(hardware_metrics_loop())
    yield
    task.cancel()


def create_app() -> FastAPI:
    """Construye la app: lifespan, estáticos y todos los routers."""
    app = FastAPI(title="ReactBits Minecraft Bedrock Wrapper GUI", lifespan=lifespan)

    DIST_DIR = os.path.join(config.BASE_DIR, "gui_frontend", "dist")
    STATIC_TARGET = DIST_DIR if os.path.exists(DIST_DIR) else config.WEB_DIR

    if not os.path.exists(STATIC_TARGET):
        os.makedirs(STATIC_TARGET)

    if os.path.exists(DIST_DIR):
        app.mount("/assets", StaticFiles(directory=os.path.join(DIST_DIR, "assets")), name="assets")

    app.mount("/static", StaticFiles(directory=config.WEB_DIR), name="static")

    app.include_router(system.router)
    app.include_router(properties.router)
    app.include_router(setup.router)
    app.include_router(actions.router)
    app.include_router(backups.router)
    app.include_router(websocket.router)

    return app


app = create_app()


def _puerto_libre(puerto: int) -> bool:
    """Comprueba si un puerto local está disponible para enlazar.

    Sin SO_REUSEADDR a propósito: uvicorn no lo usa, y en Windows ese flag
    permite a un socket "hijackear" un puerto ya ocupado (falso positivo).
    """
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", puerto))
            return True
        except OSError:
            return False


if __name__ == "__main__":
    import webbrowser

    try:
        puerto = int(os.environ.get("GUI_PORT", "8000"))
        if not (1 <= puerto <= 65535):
            raise ValueError
    except ValueError:
        print("[AVISO] GUI_PORT no es un puerto válido. Usando 8000.")
        puerto = 8000

    # Si el puerto pedido está ocupado (p. ej. SillyTavern en 8000),
    # saltar al siguiente puerto libre para no chocar con la otra app.
    while not _puerto_libre(puerto):
        print(f"[AVISO] El puerto {puerto} ya está en uso. Probando el siguiente libre...")
        puerto += 1

    url = f"http://127.0.0.1:{puerto}"
    print("=================================================================")
    print("  MINECRAFT BEDROCK WRAPPER GUI - REACTBITS DASHBOARD")
    print(f"  Abriendo en: {url}")
    print("=================================================================")
    try:
        webbrowser.open(url)
    except Exception:
        pass  # sin navegador disponible no es crítico
    try:
        uvicorn.run("server_gui_server:app", host="127.0.0.1", port=puerto, reload=False, log_level="info")
    except OSError:
        print(f"\n[AVISO] El puerto {puerto} se ocupó justo al abrir. Reintentando en el siguiente libre...")
        time.sleep(2)
        uvicorn.run("server_gui_server:app", host="127.0.0.1", port=puerto + 1, reload=False, log_level="info")
