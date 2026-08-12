"""Router del editor de server.properties."""

from fastapi import APIRouter, HTTPException, Request

from gui_backend.security import _ensure_local, _check_origin
from gui_backend.services import properties as properties_service
from gui_backend.state import manager

router = APIRouter()


@router.get("/api/server_properties")
async def get_server_properties(request: Request):
    """Devuelve los valores actuales de los campos editables."""
    _ensure_local(request.client.host if request.client else "")
    return {
        "fields": properties_service._read_props_values(),
        "server_running": manager.is_running,
    }


@router.post("/api/server_properties")
async def set_server_properties(request: Request):
    """Actualiza los campos editables de server.properties (los demas se preservan).

    Los cambios se aplican al REINICIAR el servidor (BDS lee el archivo al
    arrancar); se informa al frontend con 'restart_required'.
    """
    _ensure_local(request.client.host if request.client else "")
    _check_origin(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Cuerpo JSON invalido")
    values = (body or {}).get("values")
    if not isinstance(values, dict) or not values:
        raise HTTPException(status_code=400, detail="No hay campos para guardar")
    for v in values.values():
        if not isinstance(v, str):
            raise HTTPException(status_code=400, detail="Valores deben ser texto")
    ok, detalle = properties_service._validate_props(values)
    if not ok:
        raise HTTPException(status_code=400, detail=detalle)
    written = properties_service._write_props_values(values)
    manager.add_log(f"[GUI] Configuracion actualizada: {', '.join(sorted(written))}", "system")
    return {"status": "ok", "written": written, "restart_required": True}
