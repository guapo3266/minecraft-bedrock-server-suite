"""Router de la vista de jugadores (solo lectura; acciones via /api/command)."""

from fastapi import APIRouter, Request

from gui_backend.security import _ensure_local
from gui_backend.services import players as players_service
from gui_backend.state import manager

router = APIRouter()


@router.get("/api/players")
async def get_players(request: Request):
    """Jugadores online + conocidos con permiso/allowlist, para la GUI."""
    _ensure_local(request.client.host if request.client else "")
    with manager.lock:
        online = list(manager.players_online)
    view = players_service.build_players_view(online)
    view["server_running"] = manager.is_running
    return view
