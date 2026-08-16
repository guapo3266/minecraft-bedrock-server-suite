"""Router del sistema: favicon, index, estado y envío de comandos."""

import os
import re
import socket
import time

import requests
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

from console_lang import L
from gui_backend import config
from gui_backend.security import _ensure_local, _check_origin
from gui_backend.services.properties import _read_props_values
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


# --- Conectividad: IP local/publica para invitar jugadores ---
# La IP publica se consulta con cadena de fallback y se cachea 5 minutos:
# este endpoint se llama una sola vez al cargar la GUI (no en cada poll de
# status). ?refresh=1 fuerza la consulta (boton de la tarjeta).
_PUBLIC_IP_SERVICES = (
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
    "https://icanhazip.com",
)
_PUBLIC_IP_CACHE_SEC = 300
_conn_cache = {"at": 0.0, "public_ip": None}


def _get_lan_ip():
    """IP local de la interfaz de salida (no envia paquetes reales)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        return "127.0.0.1"


def _fetch_public_ip():
    """IP publica con cadena de fallback (ipify -> ifconfig.me -> icanhazip)."""
    for url in _PUBLIC_IP_SERVICES:
        try:
            r = requests.get(url, timeout=4)
            if r.status_code == 200:
                candidate = r.text.strip()
                if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", candidate):
                    return candidate
        except Exception:
            continue
    return None


def _get_public_ip_cached(force=False):
    now = time.time()
    if (force or _conn_cache["public_ip"] is None
            or now - _conn_cache["at"] > _PUBLIC_IP_CACHE_SEC):
        _conn_cache["public_ip"] = _fetch_public_ip()
        _conn_cache["at"] = now
    return _conn_cache["public_ip"]


@router.get("/api/connectivity")
async def get_connectivity(request: Request, refresh: bool = False):
    _ensure_local(request.client.host if request.client else "")
    props = _read_props_values()
    return {
        "lan_ip": _get_lan_ip(),
        "public_ip": _get_public_ip_cached(force=refresh),
        "port": props.get("server-port", "19132"),
    }


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
    
    # 'stop' en consola apaga el wrapper entero (lo intercepta el wrapper,
    # no BDS): es un stop deliberado y el watchdog no debe re-lanzarlo.
    if cmd.lower() == "stop":
        manager.stop_requested = True

    try:
        with manager.stdin_lock:
            manager.wrapper_process.stdin.write(cmd + "\n")
            manager.wrapper_process.stdin.flush()
        manager.add_log(f"> {cmd}", "command")
        return {"status": "ok", "command": cmd}
    except Exception as e:
        manager.add_log(L(f"[GUI Backend] Error enviando comando: {e}", f"[GUI Backend] Error sending command: {e}"), "error")
        return {"status": "error", "message": str(e)}
