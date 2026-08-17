"""Router de acciones (start/stop/restart/backup/update_bds) y check_update."""

import os
import re
import threading
import time

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

import auto_backup
from console_lang import L
from gui_backend import config, supervisor
from gui_backend.security import _ensure_local, _check_origin
from gui_backend.services import bds_update as bds_update_service
from gui_backend.services import lifecycle as lifecycle_service
from gui_backend.state import manager

router = APIRouter()


@router.post("/api/action/{action_name}")
async def handle_action(action_name: str, request: Request):
    _ensure_local(request.client.host if request.client else "")
    _check_origin(request)
    action = action_name.lower()
    if action == "start":
        status, detalle = lifecycle_service.start_wrapper()
        if status == "external":
            raise HTTPException(
                status_code=409,
                detail="Hay una instancia externa del servidor en ejecución",
            )
        if status == "error":
            return {"status": "error", "message": detalle}
        if status == "busy":
            return {"status": "busy", "message": "Operación en curso (restauración/actualización)"}
        return {"status": status}

    elif action == "stop":
        if not manager.is_running or not manager.wrapper_process:
            return {"status": "not_running"}
        manager.stop_requested = True  # stop deliberado: el watchdog no debe re-lanzar
        try:
            with manager.stdin_lock:
                manager.wrapper_process.stdin.write("stop\n")
                manager.wrapper_process.stdin.flush()
            manager.add_log(L("[GUI Backend] Comando 'stop' enviado...", "[GUI Backend] 'stop' command sent..."), "system")
        except Exception:
            pass
        return {"status": "stopping"}

    elif action == "restart":
        threading.Thread(target=lifecycle_service.restart_wrapper, daemon=True).start()
        return {"status": "restarting"}

    elif action == "backup":
        if not manager.is_running or not manager.wrapper_process:
            # FIX G5: un backup en frio ya en curso -> rechazar con 409
            # (antes cada clic apilaba un hilo y dos backups del mismo
            # segundo podian pisarse por compartir nombre).
            if manager.backup_in_progress:
                return {"status": "busy", "message": L("Ya hay un backup en curso", "A backup is already in progress")}
            threading.Thread(target=lifecycle_service.cold_backup, args=("gui_manual",), daemon=True).start()
            return {"status": "backup_dispatched"}
        else:
            try:
                with manager.stdin_lock:
                    manager.wrapper_process.stdin.write("backup\n")
                    manager.wrapper_process.stdin.flush()
                manager.add_log(L("[GUI Backend] Disparando backup en caliente (comando backup)...", "[GUI Backend] Triggering hot backup (backup command)..."), "backup")
            except Exception as e:
                raise HTTPException(status_code=500, detail=L(f"Error al iniciar backup: {e}", f"Error starting backup: {e}"))
            return {"status": "hot_backup_dispatched"}

    elif action == "update_bds":
        from gui_backend.services import external_probe
        if not manager.is_running:
            is_ext, _ = external_probe.detect_external_bds()
            if is_ext:
                raise HTTPException(
                    status_code=409,
                    detail="Hay una instancia externa del servidor en ejecución",
                )
        # Guard anti doble actualización: dos threads pisándose bds_update.zip corromperían la instalación
        if manager.update_in_progress:
            return {"status": "already_updating"}
        # Flag sincrónico para que el frontend sepa que hay una actualización en curso
        manager.update_in_progress = True
        manager.update_status()

        def do_update():
            # op_lock durante TODO el ciclo de actualizacion (detener el
            # servidor, backup preventivo, descarga, extraccion): un start o
            # restart durante cualquiera de esas fases arrancaria BDS mientras
            # se reemplazan los binarios. El finally libera en todos los caminos.
            manager.op_lock.acquire()
            try:
                manager.add_log(L("[Actualizador BDS] Iniciando proceso de actualización de Mojang...", "[Actualizador BDS] Starting Mojang update process..."), "system")
                # G8/D6: detener y esperar completo antes de tocar binarios;
                # si no se detiene a tiempo, la actualizacion se cancela.
                if not lifecycle_service.stop_and_wait("[Actualizador BDS]"):
                    return

                manager.add_log(L("[Actualizador BDS] Ejecutando backup preventivo de seguridad...", "[Actualizador BDS] Running preventive safety backup..."), "backup")
                backup_ok = False
                try:
                    zip_b = auto_backup.create_backup("pre_update_backup")
                    if zip_b and isinstance(zip_b, str):
                        backup_ok = True
                        manager.add_log(L(f"[Actualizador BDS] Backup de seguridad listo: {os.path.basename(zip_b)}", f"[Actualizador BDS] Safety backup ready: {os.path.basename(zip_b)}"), "backup")
                    else:
                        manager.add_log(L("[Actualizador BDS] Error en backup preventivo: no se pudo crear el archivo.", "[Actualizador BDS] Error in preventive backup: could not create the file."), "error")
                except Exception as e:
                    manager.add_log(L(f"[Actualizador BDS] Error en backup preventivo: {e}", f"[Actualizador BDS] Error in preventive backup: {e}"), "error")

                if not backup_ok:
                    manager.add_log(L("[Actualizador BDS] Actualización cancelada por fallo en el backup preventivo.", "[Actualizador BDS] Update cancelled due to preventive backup failure."), "error")
                    return

                # Descarga + staging + aplicacion con rollback: pipeline
                # compartido con el setup inicial (_download_and_install_bds).
                ok, _downloaded_version = bds_update_service._download_and_install_bds()
                if ok:
                    manager.add_log(L("[Actualizador BDS] ¡Servidor actualizado exitosamente a la versión oficial de Mojang!", "[Actualizador BDS] Server successfully updated to the official Mojang version!"), "system")
            except Exception as e:
                manager.add_log(L(f"[Actualizador BDS] Error al actualizar: {e}", f"[Actualizador BDS] Error updating: {e}"), "error")
            finally:
                manager.op_lock.release()
                manager.update_in_progress = False
                manager.update_status()
                manager.add_log(L("[Actualizador BDS] Proceso de actualización finalizado.", "[Actualizador BDS] Update process finished."), "system")

        threading.Thread(target=do_update, daemon=True).start()
        return {"status": "update_dispatched"}

    elif action == "rollback_bds":
        from gui_backend.services import external_probe
        if not manager.is_running:
            is_ext, _ = external_probe.detect_external_bds()
            if is_ext:
                raise HTTPException(
                    status_code=409,
                    detail="Hay una instancia externa del servidor en ejecución",
                )
        if manager.update_in_progress:
            return {"status": "already_updating"}
        has_previous, _prev_version = bds_update_service.read_previous_version()
        if not has_previous:
            raise HTTPException(
                status_code=409,
                detail="No hay una versión anterior guardada para restaurar",
            )
        # Reusa el flag update_in_progress: el frontend ya tiene wired el
        # flujo de "operación en curso" (modal, cierre automatico).
        manager.update_in_progress = True
        manager.update_status()

        def do_rollback():
            # op_lock durante TODO el ciclo: un start durante la reversión
            # arrancaria BDS mientras se reemplazan los binarios.
            manager.op_lock.acquire()
            try:
                manager.add_log(L("[Rollback BDS] Iniciando reversión a la versión anterior...", "[Rollback BDS] Starting rollback to the previous version..."), "system")
                if not lifecycle_service.stop_and_wait("[Rollback BDS]"):
                    return
                bds_update_service.rollback_bds()
            except Exception as e:
                manager.add_log(L(f"[Rollback BDS] Error al revertir: {e}", f"[Rollback BDS] Error rolling back: {e}"), "error")
            finally:
                manager.op_lock.release()
                manager.update_in_progress = False
                manager.update_status()
                manager.add_log(L("[Rollback BDS] Proceso de reversión finalizado.", "[Rollback BDS] Rollback process finished."), "system")

        threading.Thread(target=do_rollback, daemon=True).start()
        return {"status": "rollback_dispatched"}

    else:
        raise HTTPException(status_code=400, detail="Acción no válida")


@router.get("/api/check_update")
async def check_update(request: Request):
    _ensure_local(request.client.host if request.client else "")

    # FIX F1: la version instalada REAL se captura del log de BDS
    # (run_wrapper_thread). Fallback al release-notes.txt (formato antiguo).
    current_ver = manager.installed_version
    if not current_ver:
        release_notes = os.path.join(config.BASE_DIR, "release-notes.txt")
        if os.path.exists(release_notes):
            try:
                with open(release_notes, "r", encoding="utf-8") as f:
                    content = f.read()
                    match = re.search(r"(\d+\.\d+\.\d+\.\d+)", content)
                    if match:
                        current_ver = match.group(1)
            except Exception:
                pass

    latest_ver = None
    download_url = None
    has_update = None  # True/False solo cuando ambas versiones son conocidas
    unavailable = False
    reason = None

    # API oficial que usa la web de Mojang (la pagina HTML ya no expone el zip).
    # requests con timeout de 5s x2 fuentes: fuera del event loop para no
    # congelar la GUI hasta ~10s cuando Mojang no responde.
    download_url, latest_ver = await run_in_threadpool(bds_update_service._fetch_latest_bedrock_download)
    if latest_ver:
        unavailable = False
    else:
        # Se reporta NO DISPONIBLE en vez de mentir con has_update=False.
        unavailable = True
        reason = "la API de Mojang no devolvio el link de descarga de Windows"

    if latest_ver and current_ver:
        # Comparación semántica numérica (evita falsos 'has_update' con versiones más nuevas)
        has_update = bds_update_service._version_tuple(latest_ver) > bds_update_service._version_tuple(current_ver)

    has_previous, previous_version = bds_update_service.read_previous_version()
    return {
        "current_version": current_ver,
        "latest_version": latest_ver,
        "download_url": download_url,
        "has_update": has_update,
        "unavailable": unavailable,
        "reason": reason,
        "has_previous": has_previous,
        "previous_version": previous_version,
    }
