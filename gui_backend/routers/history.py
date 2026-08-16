"""Router del historial persistente (solo lectura)."""

from fastapi import APIRouter, HTTPException, Request

from gui_backend.security import _ensure_local
from gui_backend.services import history as history_service

router = APIRouter()


@router.get("/api/history/metrics")
async def get_history_metrics(request: Request, hours: int = 24):
    _ensure_local(request.client.host if request.client else "")
    if hours not in (1, 6, 24):
        raise HTTPException(status_code=400, detail="hours debe ser 1, 6 o 24")
    return {"points": history_service.query_metrics(hours)}


@router.get("/api/history/logs")
async def get_history_logs(request: Request, limit: int = 500):
    _ensure_local(request.client.host if request.client else "")
    if not (1 <= limit <= 1000):
        raise HTTPException(status_code=400, detail="limit debe estar entre 1 y 1000")
    return {"logs": history_service.query_logs(limit)}


@router.get("/api/history/sessions")
async def get_history_sessions(request: Request, days: int = 7):
    _ensure_local(request.client.host if request.client else "")
    if not (1 <= days <= 90):
        raise HTTPException(status_code=400, detail="days debe estar entre 1 y 90")
    return history_service.query_sessions(days)
