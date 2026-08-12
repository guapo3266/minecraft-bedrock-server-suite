"""Router del sistema: favicon, index, estado y envío de comandos."""

import os

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

from console_lang import L
from gui_backend import config
from gui_backend.security import _ensure_local, _check_origin
from gui_backend.state import manager, build_public_status

router = APIRouter()

DIST_DIR = os.path.join(config.BASE_DIR, "gui_frontend", "dist")


@router.get("/favicon.svg")
async def get_favicon():
    favicon_path = os.path.join(config.BASE_DIR, "gui_frontend", "public", "favicon.svg")
    if os.path.exists(favicon_path):
        return FileResponse(favicon_path)
    return FileResponse(os.path.join(config.WEB_DIR, "index.html"))


@router.get("/", response_class=HTMLResponse)
async def serve_index():
    if os.path.exists(DIST_DIR):
        index_path = os.path.join(DIST_DIR, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
    index_path = os.path.join(config.WEB_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("<h1>Cargando GUI...</h1>")


@router.get("/api/status")
async def get_status(request: Request):
    _ensure_local(request.client.host if request.client else "")
    return build_public_status(manager)


class CommandRequest(BaseModel):
    command: str


@router.post("/api/command")
async def send_command(req: CommandRequest, request: Request):
    _ensure_local(request.client.host if request.client else "")
    _check_origin(request)
    cmd = req.command.strip()
    if not cmd:
        return {"status": "ok"}

    if not manager.is_running or not manager.wrapper_process or manager.wrapper_process.poll() is not None:
        manager.add_log(f"> {cmd}", "command")
        manager.add_log(L("[SISTEMA] El servidor de Minecraft está APAGADO. Presiona '▶ Iniciar Servidor' primero.", "[SISTEMA] The Minecraft server is OFF. Press '▶ Start Server' first."), "error")
        return {"status": "offline", "message": "El servidor no está en ejecución"}
    
    try:
        with manager.stdin_lock:
            manager.wrapper_process.stdin.write(cmd + "\n")
            manager.wrapper_process.stdin.flush()
        manager.add_log(f"> {cmd}", "command")
        return {"status": "ok", "command": cmd}
    except Exception as e:
        manager.add_log(L(f"[GUI Backend] Error enviando comando: {e}", f"[GUI Backend] Error sending command: {e}"), "error")
        return {"status": "error", "message": str(e)}
