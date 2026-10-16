"""Actualización de la suite, separada de las actualizaciones de Minecraft/BDS."""

import os
import platform

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StrictBool
from starlette.concurrency import run_in_threadpool

from gui_backend.security import _ensure_local, _check_origin
from gui_backend.services import suite_update as service
from suite_version import VERSION

router = APIRouter()


@router.get("/api/suite_update")
async def check(request: Request, refresh: bool = False):
    _ensure_local(request.client.host if request.client else "")
    return await run_in_threadpool(service.check_release, refresh)


@router.get("/api/suite_update/progress")
async def progress(request: Request):
    _ensure_local(request.client.host if request.client else "")
    return await run_in_threadpool(service.last_progress)


@router.get("/api/suite_update/health")
async def health(request: Request):
    _ensure_local(request.client.host if request.client else "")
    service.release_handoff_guard()
    return {"version": VERSION, "boot_token": os.environ.get("SUITE_UPDATE_BOOT_TOKEN"),
            "python_version": platform.python_version(), "pid": os.getpid()}


class UpdateConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: StrictBool


@router.post("/api/suite_update")
async def install(body: UpdateConfirmation, request: Request):
    _ensure_local(request.client.host if request.client else "")
    _check_origin(request)
    if body.confirmed is not True:
        raise HTTPException(status_code=400, detail="confirmation_required")
    try:
        service.start_update()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "preparing"}
