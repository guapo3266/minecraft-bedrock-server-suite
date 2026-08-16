"""Router de la configuracion de programacion (backups + watchdog)."""

from fastapi import APIRouter, HTTPException, Request

from console_lang import L
from gui_backend.security import _ensure_local, _check_origin
from gui_backend.services import schedule_config as schedule_config_service
from gui_backend.state import manager

router = APIRouter()


@router.get("/api/schedule")
async def get_schedule(request: Request):
    """Config actual (o defaults si nunca se guardo una)."""
    _ensure_local(request.client.host if request.client else "")
    return schedule_config_service.load()


@router.post("/api/schedule")
async def set_schedule(request: Request):
    """Valida y guarda la config; el wrapper la aplica al vuelo (relee por mtime)."""
    _ensure_local(request.client.host if request.client else "")
    _check_origin(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Cuerpo JSON invalido")
    ok, cfg, detalle = schedule_config_service.save(body or {})
    if not ok:
        raise HTTPException(status_code=400, detail=detalle)
    partes = [f"intervalo {cfg['backup_interval_min']} min"]
    if cfg["daily_backup_time"]:
        partes.append(f"diario {cfg['daily_backup_time']}")
    if cfg["auto_restart_on_crash"] or cfg["daily_restart_time"]:
        partes.append("watchdog")
    resumen = ", ".join(partes)
    manager.add_log(L(f"[GUI] Programación actualizada: {resumen}.", f"[GUI] Schedule updated: {resumen}."), "system")
    return {"status": "ok", "config": cfg}
