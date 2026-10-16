"""
ai.py — Router de endpoints del Asistente IA para Bedrock
=========================================================
Provee endpoints locales para consultar el estado del servidor LM Studio
y proponer comandos traducidos desde lenguaje natural para aprobación humana.
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from gui_backend.security import _ensure_local, _check_origin
from gui_backend.services import ai_assistant
from gui_backend.state import manager

router = APIRouter()


class ProposeRequest(BaseModel):
    prompt: str


@router.post("/api/ai/propose")
async def propose_ai_command(req: ProposeRequest, request: Request):
    """
    Recibe una instrucción en lenguaje natural y propone un comando Bedrock
    utilizando FunctionGemma en LM Studio. No ejecuta nada automáticamente.
    """
    _ensure_local(request.client.host if request.client else "")
    _check_origin(request)

    prompt = req.prompt.strip()
    if not prompt:
        return {"status": "error", "message": "La solicitud no puede estar vacía."}

    with manager.lock:
        online = list(manager.players_online)

    res = await run_in_threadpool(
        ai_assistant.propose_command,
        prompt=prompt,
        online_players=online
    )
    return res


@router.get("/api/ai/status")
async def get_ai_status(request: Request):
    """Verifica si LM Studio está escuchando y qué modelo tiene cargado."""
    _ensure_local(request.client.host if request.client else "")

    is_online, model_info = await run_in_threadpool(ai_assistant.check_lmstudio_health)
    return {
        "status": "ok",
        "online": is_online,
        "model": model_info if is_online else None
    }
