"""Router de acciones (start/stop/restart/backup/update_bds) y check_update."""

import os
import re
import threading
import time

from fastapi import APIRouter, HTTPException, Request

import auto_backup
from console_lang import L
from gui_backend import config, supervisor
from gui_backend.security import _ensure_local, _check_origin
from gui_backend.services import bds_update as bds_update_service
from gui_backend.state import manager

router = APIRouter()


@router.post("/api/action/{action_name}")
async def handle_action(action_name: str, request: Request):
    _ensure_local(request.client.host if request.client else "")
    _check_origin(request)
    action = action_name.lower()
    if action == "start":
        from gui_backend.services import external_probe
        is_ext, _ = external_probe.detect_external_bds()
        if is_ext:
            raise HTTPException(
                status_code=409,
                detail="Hay una instancia externa del servidor en ejecución",
            )
        # Chequeo + marcado de estado ATOMICOS bajo op_lock (sin bloqueo: si
        # hay una restauracion o actualizacion en curso, se rechaza con 'busy'
        # en vez de esperar). Dos requests simultaneos ya no pueden ver ambos
        # is_running == False y lanzar dos wrappers.
        if not manager.op_lock.acquire(blocking=False):
            return {"status": "busy", "message": "Operación en curso (restauración/actualización)"}
        try:
            if manager.is_running:
                return {"status": "already_running"}
            # FIX G1: el subproceso del wrapper se crea BAJO el lock, de modo
            # que wrapper_process existe antes de liberarlo: update_bds y
            # restore ya no pueden ver is_running=True con wrapper_process
            # None y saltarse la detencion del servidor durante el arranque.
            try:
                proc = supervisor._spawn_wrapper_process()
            except Exception as e:
                manager.add_log(L(f"[GUI Backend] Error al iniciar el wrapper: {e}", f"[GUI Backend] Error starting the wrapper: {e}"), "error")
                return {"status": "error", "message": str(e)}
            # FIX G2: wrapper_process se asigna BAJO el lock (el hilo lo
            # re-afirma al arrancar): tras la respuesta de start, /stop ya
            # nunca ve is_running=True con wrapper_process=None.
            manager.wrapper_process = proc
            manager.is_running = True  # el hilo lo reafirma al arrancar
        finally:
            manager.op_lock.release()
        threading.Thread(target=supervisor.run_wrapper_thread, args=(proc,), daemon=True).start()
        return {"status": "starting"}

    elif action == "stop":
        if not manager.is_running or not manager.wrapper_process:
            return {"status": "not_running"}
        try:
            with manager.stdin_lock:
                manager.wrapper_process.stdin.write("stop\n")
                manager.wrapper_process.stdin.flush()
            manager.add_log(L("[GUI Backend] Comando 'stop' enviado...", "[GUI Backend] 'stop' command sent..."), "system")
        except Exception:
            pass
        return {"status": "stopping"}

    elif action == "restart":
        def do_restart():
            exit_event = manager.wrapper_exit_event
            if manager.is_running and manager.wrapper_process:
                try:
                    with manager.stdin_lock:
                        manager.wrapper_process.stdin.write("stop\n")
                        manager.wrapper_process.stdin.flush()
                except Exception:
                    pass
                manager.add_log(L("[GUI Backend] Reiniciando servidor...", "[GUI Backend] Restarting server..."), "system")
                # G8: espera en DOS fases antes de lanzar otro wrapper (evita
                # dobles instancias y pisado de estado):
                #  Fase 1: que BDS muera (evento propio, independiente del
                #    cierre del wrapper). Antes se esperaba el evento de salida
                #    del wrapper con solo 30s, pero ese evento solo llega tras
                #    el backup final de cierre (tope interno de 240s): con un
                #    mundo grande el reinicio se abortaba siempre aunque el
                #    servidor ya se hubiera detenido.
                if not manager.server_stopped_event.wait(timeout=config.SERVER_STOP_TIMEOUT_SEC):
                    manager.add_log(
                        L(f"[GUI Backend] El servidor no se detuvo en {config.SERVER_STOP_TIMEOUT_SEC}s. "
                          "Reinicio cancelado.",
                          f"[GUI Backend] The server did not stop within {config.SERVER_STOP_TIMEOUT_SEC}s. "
                          "Restart cancelled."),
                        "error",
                    )
                    return
                #  Fase 2: que el wrapper termine del todo (backup final de
                #    cierre incluido) antes de lanzar otro: dos wrappers
                #    comprimiendo el mismo mundo pisarian sus copias.
                if not exit_event.wait(timeout=config.WRAPPER_EXIT_TIMEOUT_SEC):
                    manager.add_log(
                        L(f"[GUI Backend] El wrapper no termino en {config.WRAPPER_EXIT_TIMEOUT_SEC}s "
                          "(incluye el backup final de cierre). Reinicio cancelado; "
                          "inicia el servidor manualmente.",
                          f"[GUI Backend] The wrapper did not finish within {config.WRAPPER_EXIT_TIMEOUT_SEC}s "
                          "(includes the final shutdown backup). Restart cancelled; "
                          "start the server manually."),
                        "error",
                    )
                    return
            # Chequeo + lanzamiento atomicos bajo op_lock: si hay una
            # actualizacion/restauracion/backup en curso, no se re-lanza BDS
            # (arrancar mientras se reemplazan binarios o se copia el mundo
            # corromperia ambos).
            if not manager.op_lock.acquire(blocking=False):
                manager.add_log(L("[GUI Backend] Operación en curso (actualización/restauración/backup); reinicio abortado.", "[GUI Backend] Operation in progress (update/restore/backup); restart aborted."), "error")
                return
            try:
                # Alguien más pudo arrancar el servidor mientras esperábamos; no duplicar
                if manager.is_running:
                    manager.add_log(L("[GUI Backend] Otro inicio detectado durante el reinicio. Abortando.", "[GUI Backend] Another start detected during restart. Aborting."), "error")
                    return
                # FIX G1: crear el subproceso bajo el lock (igual que start)
                proc = supervisor._spawn_wrapper_process()
                # FIX G2: wrapper_process asignado bajo el lock
                manager.wrapper_process = proc
                # H1: marcar en marcha bajo el lock (igual que start). Sin
                # esto, dos restarts simultaneos podian ver is_running=False
                # tras el spawn y lanzar dos wrappers que pisarian el mundo.
                manager.is_running = True
                threading.Thread(target=supervisor.run_wrapper_thread, args=(proc,), daemon=True).start()
            except Exception as e:
                manager.add_log(L(f"[GUI Backend] Error al iniciar el wrapper: {e}", f"[GUI Backend] Error starting the wrapper: {e}"), "error")
            finally:
                manager.op_lock.release()

        threading.Thread(target=do_restart, daemon=True).start()
        return {"status": "restarting"}

    elif action == "backup":
        if not manager.is_running or not manager.wrapper_process:
            # FIX G5: un backup en frio ya en curso -> rechazar con 409
            # (antes cada clic apilaba un hilo y dos backups del mismo
            # segundo podian pisarse por compartir nombre).
            if manager.backup_in_progress:
                return {"status": "busy", "message": L("Ya hay un backup en curso", "A backup is already in progress")}
            def manual_off_backup():
                # op_lock durante TODA la copia: un start inmediato modificaria
                # el mundo mientras se comprime, dando un backup inconsistente.
                with manager.op_lock:
                    # Re-chequeo atomico bajo el lock: `start` pudo ganar la
                    # carrera entre la decision del handler (servidor apagado)
                    # y la adquisicion del lock. Un backup en frio sobre un
                    # mundo vivo seria inconsistente.
                    if manager.is_running:
                        manager.add_log(
                            L("[GUI Backend] El servidor se encendió; backup en frío cancelado (usa el backup en caliente).", "[GUI Backend] The server started; cold backup cancelled (use the hot backup)."),
                            "error",
                        )
                        return
                    # Re-chequeo atomico bajo el lock (FIX G5): dos clics
                    # simultaneos pueden pasar el check del handler; aqui se
                    # descarta el segundo con op_lock ya adquirido.
                    if manager.backup_in_progress:
                        manager.add_log(
                            L("[GUI Backend] Ya hay un backup en frío en curso; solicitud ignorada.", "[GUI Backend] A cold backup is already in progress; request ignored."),
                            "error",
                        )
                        return
                    manager.backup_in_progress = True
                    manager.update_status()
                    manager.add_log(L("[GUI Backend] Ejecutando backup en frío...", "[GUI Backend] Running cold backup..."), "backup")
                    try:
                        zip_path = auto_backup.create_backup("gui_manual")
                        if zip_path:
                            manager.last_backup_time = time.strftime("%H:%M:%S")
                            manager.add_log(L(f"[GUI Backend] Backup exitoso: {os.path.basename(zip_path)}", f"[GUI Backend] Backup successful: {os.path.basename(zip_path)}"), "backup")
                        else:
                            manager.add_log(L("[GUI Backend] Error en backup: no se produjo un ZIP (revisa la consola del servidor).", "[GUI Backend] Backup error: no ZIP was produced (check the server console)."), "error")
                    except Exception as e:
                        manager.add_log(L(f"[GUI Backend] Error en backup: {e}", f"[GUI Backend] Backup error: {e}"), "error")
                    finally:
                        manager.backup_in_progress = False
                        manager.update_status()

            threading.Thread(target=manual_off_backup, daemon=True).start()
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
                if manager.is_running and manager.wrapper_process:
                    manager.add_log(L("[Actualizador BDS] Deteniendo servidor de Minecraft...", "[Actualizador BDS] Stopping Minecraft server..."), "system")
                    try:
                        with manager.stdin_lock:
                            manager.wrapper_process.stdin.write("stop\n")
                            manager.wrapper_process.stdin.flush()
                    except Exception:
                        pass
                    # G8: espera en DOS fases antes de tocar binarios:
                    #  Fase 1: BDS muerto (evento propio; antes se esperaba la
                    #    salida del wrapper con 30s, que no llega hasta terminar
                    #    el backup final de cierre y abortaba la actualizacion
                    #    con un mensaje enganoso).
                    if not manager.server_stopped_event.wait(timeout=config.SERVER_STOP_TIMEOUT_SEC):
                        # D6: comportamiento intencional (nunca actualizar con el
                        # servidor vivo); el mensaje deja claro el estado y como seguir.
                        # H1: si vencio la fase 1, BDS puede seguir deteniendose:
                        # el mensaje no da por hecho que quedo detenido.
                        manager.add_log(
                            L(f"[Actualizador BDS] El servidor no se detuvo en {config.SERVER_STOP_TIMEOUT_SEC}s. "
                              "Actualización cancelada; "
                              "si el servidor quedó detenido, reinícialo con ▶ Iniciar.",
                              f"[Actualizador BDS] The server did not stop within {config.SERVER_STOP_TIMEOUT_SEC}s. "
                              "Update cancelled; "
                              "if the server ended up stopped, restart it with ▶ Start."),
                            "error",
                        )
                        return
                    #  Fase 2: wrapper completamente terminado (backup final de
                    #    cierre incluido) antes de reemplazar binarios o lanzar
                    #    el backup preventivo.
                    if not manager.wrapper_exit_event.wait(timeout=config.WRAPPER_EXIT_TIMEOUT_SEC):
                        manager.add_log(
                            L(f"[Actualizador BDS] El wrapper no termino en {config.WRAPPER_EXIT_TIMEOUT_SEC}s "
                              "(incluye el backup final de cierre). Actualización cancelada; "
                              "el servidor quedó detenido. Reinícialo con ▶ Iniciar.",
                              f"[Actualizador BDS] The wrapper did not finish within {config.WRAPPER_EXIT_TIMEOUT_SEC}s "
                              "(includes the final shutdown backup). Update cancelled; "
                              "the server ended up stopped. Restart it with ▶ Start."),
                            "error",
                        )
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

    # API oficial que usa la web de Mojang (la pagina HTML ya no expone el zip)
    download_url, latest_ver = bds_update_service._fetch_latest_bedrock_download()
    if latest_ver:
        unavailable = False
    else:
        # Se reporta NO DISPONIBLE en vez de mentir con has_update=False.
        unavailable = True
        reason = "la API de Mojang no devolvio el link de descarga de Windows"

    if latest_ver and current_ver:
        # Comparación semántica numérica (evita falsos 'has_update' con versiones más nuevas)
        has_update = bds_update_service._version_tuple(latest_ver) > bds_update_service._version_tuple(current_ver)

    return {
        "current_version": current_ver,
        "latest_version": latest_ver,
        "download_url": download_url,
        "has_update": has_update,
        "unavailable": unavailable,
        "reason": reason,
    }
