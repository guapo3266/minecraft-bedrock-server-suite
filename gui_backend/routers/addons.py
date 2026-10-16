"""Router del inventario de addons: GET /api/addons (solo lectura).

El analisis vive en `addon_inventory` (compartido con la CLI) y se invoca a
traves de `gui_backend.services.addons`; aqui solo se aplican las guardas HTTP
del proyecto y la validacion de parametros.
"""

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

import addon_inventory
from console_lang import L
from gui_backend.security import _ensure_local
from gui_backend.services import addons as addons_service

router = APIRouter()


@router.get("/api/addons")
async def get_addons(request: Request, world: str = None, kind: str = None):
    """Inventario y diagnosticos de packs, con filtros opcionales de vista."""
    _ensure_local(request.client.host if request.client else "")
    if kind is not None and kind not in addon_inventory.KINDS:
        raise HTTPException(status_code=400, detail=L(
            "kind debe ser 'behavior' o 'resource'",
            "kind must be 'behavior' or 'resource'",
        ))
    # El analizador recorre el arbol de la instalacion (I/O de disco): fuera del
    # event loop para no congelar WebSockets ni el bucle de metricas.
    vista = await run_in_threadpool(addons_service.build_addons_view, world, kind)
    if world is not None and not any(w["name"] == world for w in vista["worlds"]):
        raise HTTPException(status_code=400, detail=L(
            f"Mundo desconocido: {world}",
            f"Unknown world: {world}",
        ))
    return vista
