"""Ciclo de vida del wrapper: arranque, reinicio y backup en frio.

Unica fuente de esas secuencias: las usan el router de acciones y el
watchdog (gui_backend/services/watchdog.py). Los tests parchean
supervisor._spawn_wrapper_process / supervisor.run_wrapper_thread; aqui se
leen como atributos de modulo en runtime para que esos parches sigan validos.
"""

import os
import threading
import time

import auto_backup
import wrapper_state
from console_lang import L

from gui_backend import config, supervisor
from gui_backend.state import manager


def _estimate_world_bytes():
    """Bytes sin comprimir del proximo backup (los que ve el wrapper al cerrar).

    Costura de tests: tests/conftest.py la fija en 0 para que la suite no
    dependa del tamano del mundo real de la instalacion.
    """
    return auto_backup.estimate_backup_total_bytes()


def wrapper_exit_timeout_sec():
    """Espera de la fase 2 (wrapper completo) para el mundo actual.

    Piso configurable (`config.WRAPPER_EXIT_TIMEOUT_SEC`, holgura incluida) mas
    lo que el tamano del mundo anade al cierre del wrapper: su join del worker
    caliente y su backup final escalan (`wrapper_state.shutdown_extra_sec`, la
    misma escala que usa el wrapper). Con un tope fijo la GUI abortaba una
    actualizacion/reinicio mientras el backup final seguia legitimamente en
    curso. Nunca lanza: un fallo al estimar deja el piso.
    """
    try:
        extra = wrapper_state.shutdown_extra_sec(_estimate_world_bytes())
    except Exception:
        extra = 0
    return config.WRAPPER_EXIT_TIMEOUT_SEC + extra


# Sondeo de la fase 1 mientras el wrapper sigue en su backup inicial.
_PRE_BDS_POLL_SEC = 0.5


def _pre_bds_allowance_sec():
    """Margen maximo para que el wrapper termine su backup inicial y lance BDS.

    El backup inicial empaqueta el mismo mundo + packs que el backup final:
    misma escala (`wrapper_state.scaled_backup_timeout_sec`, piso 240 s).
    Nunca lanza: un fallo al estimar deja el piso.
    """
    try:
        return wrapper_state.scaled_backup_timeout_sec(
            _estimate_world_bytes(), wrapper_state.FINAL_BACKUP_TIMEOUT_SEC)
    except Exception:
        return wrapper_state.FINAL_BACKUP_TIMEOUT_SEC


def _wait_server_stopped():
    """Fase 1 G8: espera a que BDS muera. Devuelve (detenido, segundos esperados).

    El wrapper hace su backup inicial ANTES de lanzar BDS y no lee stdin hasta
    entonces: un 'stop' enviado en esa ventana queda en la tuberia y se aplica
    cuando BDS arranca. Con el tope fijo de SERVER_STOP_TIMEOUT_SEC, un backup
    inicial largo cancelaba el reinicio/actualizacion y despues el stop
    encolado apagaba igual el servidor, ya sin re-arranque porque
    stop_requested quedaba en True (2026-10-20). Mientras el canal NDJSON diga
    que BDS aun no se lanzo (manager.wrapper_pre_bds), el plazo no corre; el
    margen del backup inicial acota esa espera.

    El flag se observa durante la espera, no solo al entrar: un stop pedido
    justo tras arrancar, antes de leer `wrapper_started`, veia el flag aun en
    False y caia en la espera fija aunque el backup inicial empezara despues
    (2026-10-20). Mientras el canal no confirme la sesion (`events_alive`) o
    BDS no se haya lanzado, se sondea; despues es la espera de siempre. Los
    plazos se descuentan con el timeout de cada espera, no con el reloj.
    """
    start = time.monotonic()
    stop_budget = config.SERVER_STOP_TIMEOUT_SEC
    pre_bds_budget = None
    while manager.is_running and (manager.wrapper_pre_bds or not manager.events_alive):
        pre_bds = manager.wrapper_pre_bds
        if pre_bds and pre_bds_budget is None:
            pre_bds_budget = _pre_bds_allowance_sec()
        if pre_bds and pre_bds_budget > 0:
            # BDS aun no se lanzo: el plazo de la fase 1 vuelve a estar entero.
            stop_budget = config.SERVER_STOP_TIMEOUT_SEC
            step = min(_PRE_BDS_POLL_SEC, pre_bds_budget)
            pre_bds_budget -= step
        else:
            if stop_budget <= 0:
                return False, time.monotonic() - start
            step = min(_PRE_BDS_POLL_SEC, stop_budget)
            stop_budget -= step
        if manager.server_stopped_event.wait(timeout=step):
            return True, time.monotonic() - start
    stopped = manager.server_stopped_event.wait(timeout=max(0.0, stop_budget))
    return stopped, time.monotonic() - start


def _launch_wrapper():
    """Lanza el wrapper bajo op_lock, SIN sonda de instancia externa.

    Lo llaman start_wrapper (que si sondea antes) y restart_wrapper (que
    acaba de parar su PROPIA instancia: sondear lo bloquearia por un BDS
    ajeno corriendo en otra instalacion de la misma maquina). Devuelve
    (status, detalle): 'starting' | 'already_running' | 'busy' | 'error'.

    El subproceso se crea BAJO op_lock (FIX G1): wrapper_process existe antes
    de liberarlo, de modo que update_bds y restore no pueden ver
    is_running=True con wrapper_process None y saltarse la detencion.
    Chequeo + marcado de estado atomicos (FIX H1): dos llamadas simultaneas
    no pueden ver ambas is_running == False y lanzar dos wrappers.
    """
    if not manager.op_lock.acquire(blocking=False):
        return "busy", ""
    try:
        if manager.is_running:
            return "already_running", ""
        try:
            proc = supervisor._spawn_wrapper_process()
        except Exception as e:
            manager.add_log(L(f"[GUI Backend] Error al iniciar el wrapper: {e}", f"[GUI Backend] Error starting the wrapper: {e}"), "error")
            return "error", str(e)
        # FIX G2: asignado bajo el lock (el hilo lo reafirma al arrancar):
        # tras volver de start, /stop nunca ve is_running=True con proceso None.
        # La apertura de sesion es atomica con el cierre del hilo lector
        # (run_wrapper_thread usa el mismo manager.lock en su finally): sin
        # esto, un finally concurrente de la sesion anterior podria marcar
        # como muerta la sesion recien lanzada. _spawn_wrapper_process ya
        # limpio los eventos; se re-limpian aqui para que el set/clear quede
        # serializado con el cierre.
        with manager.lock:
            manager.wrapper_process = proc
            manager.is_running = True
            # El hilo lector lo reafirma; fijarlo ya evita que un tick del
            # watchdog vea is_running=True con el start_time de la sesion
            # anterior (decide el reinicio diario por el arranque, 2026-10-20).
            manager.start_time = time.time()
            manager.wrapper_exit_event.clear()
            manager.server_stopped_event.clear()
    finally:
        manager.op_lock.release()
    threading.Thread(target=supervisor.run_wrapper_thread, args=(proc,), daemon=True).start()
    return "starting", ""


def start_wrapper():
    """Sonda de instancia externa + lanzamiento. Devuelve (status, detalle).

    status: 'starting' | 'already_running' | 'busy' | 'external' | 'error'.
    """
    from gui_backend.services import external_probe
    is_ext, _ = external_probe.detect_external_bds()
    if is_ext:
        return "external", ""
    return _launch_wrapper()


def restart_wrapper():
    """Reinicio completo: stop por stdin, espera en dos fases y re-arranque.

    Nunca lanza: los abortos se loguean. El stop es deliberado, asi que marca
    manager.stop_requested para que el watchdog no lo tome por un crash.
    """
    exit_event = manager.wrapper_exit_event
    if manager.is_running and manager.wrapper_process:
        try:
            with manager.stdin_lock:
                manager.wrapper_process.stdin.write("stop\n")
                manager.wrapper_process.stdin.flush()
        except Exception as e:
            manager.add_log(
                L(f"[GUI Backend] Reinicio cancelado: no se pudo enviar 'stop' al wrapper ({e}).",
                  f"[GUI Backend] Restart cancelled: could not send 'stop' to the wrapper ({e})."),
                "error",
            )
            return
        # Solo tras entrega correcta: un fallo no debe marcar la ausencia del
        # wrapper como deliberada mientras el servidor sigue vivo (misma regla
        # que /api/action/stop; si no, el watchdog no re-lanzaria un crash real).
        manager.stop_requested = True
        manager.add_log(L("[GUI Backend] Reiniciando servidor...", "[GUI Backend] Restarting server..."), "system")
        # G8: espera en DOS fases antes de lanzar otro wrapper (evita dobles
        # instancias y pisado de estado):
        #  Fase 1: que BDS muera (evento propio, independiente del cierre del
        #    wrapper). Esperar solo la salida del wrapper con 30s abortaba el
        #    reinicio en mundos grandes: ese evento llega tras el backup final.
        #    Un backup inicial en curso no consume el plazo (_wait_server_stopped).
        stopped, waited = _wait_server_stopped()
        if not stopped:
            waited_s = round(waited)
            manager.add_log(
                L(f"[GUI Backend] El servidor no se detuvo en {waited_s}s. "
                  "Reinicio cancelado.",
                  f"[GUI Backend] The server did not stop within {waited_s}s. "
                  "Restart cancelled."),
                "error",
            )
            return
        #  Fase 2: que el wrapper termine del todo (backup final de cierre
        # incluido) antes de lanzar otro: dos wrappers comprimiendo el mismo
        # mundo pisarian sus copias. El tope escala con el tamano del mundo,
        # igual que los timeouts del wrapper (wrapper_exit_timeout_sec).
        wrapper_exit_timeout = wrapper_exit_timeout_sec()
        if not exit_event.wait(timeout=wrapper_exit_timeout):
            manager.add_log(
                L(f"[GUI Backend] El wrapper no termino en {wrapper_exit_timeout}s "
                  "(incluye el backup final de cierre). Reinicio cancelado; "
                  "inicia el servidor manualmente.",
                  f"[GUI Backend] The wrapper did not finish within {wrapper_exit_timeout}s "
                  "(includes the final shutdown backup). Restart cancelled; "
                  "start the server manually."),
                "error",
            )
            return

    # Re-arranque directo sin sonda: esta instancia acabo de ser detenida por
    # nosotros (semantica original del restart); un BDS ajeno en otra
    # instalacion no debe vetar el reinicio de la propia.
    status, detalle = _launch_wrapper()
    if status == "starting":
        return
    if status == "already_running":
        manager.add_log(L("[GUI Backend] Otro inicio detectado durante el reinicio. Abortando.", "[GUI Backend] Another start detected during the restart. Aborting."), "error")
    elif status == "busy":
        manager.add_log(L("[GUI Backend] Operación en curso (actualización/restauración/backup); reinicio abortado.", "[GUI Backend] Operation in progress (update/restore/backup); restart aborted."), "error")
    else:
        manager.add_log(L(f"[GUI Backend] No se pudo re-iniciar el wrapper ({status}): {detalle}", f"[GUI Backend] Could not restart the wrapper ({status}): {detalle}"), "error")


def stop_and_wait(tag="[Actualizador BDS]"):
    """Detiene el wrapper (si corre) y espera las dos fases G8.

    Marca stop_requested (stop deliberado: el watchdog no re-lanza). Devuelve
    True si el servidor quedo detenido o ya lo estaba; False si aborto por
    timeout — el llamador NO debe tocar la instalacion en ese caso.
    """
    if not (manager.is_running and manager.wrapper_process):
        return True
    try:
        with manager.stdin_lock:
            manager.wrapper_process.stdin.write("stop\n")
            manager.wrapper_process.stdin.flush()
    except Exception as e:
        manager.add_log(
            L(f"{tag} No se pudo enviar 'stop' al wrapper ({e}). Operación cancelada.",
              f"{tag} Could not send 'stop' to the wrapper ({e}). Operation cancelled."),
            "error",
        )
        return False
    # Solo tras entrega correcta (misma regla que /api/action/stop): un fallo no
    # debe inhibir al watchdog mientras el servidor sigue vivo.
    manager.stop_requested = True
    manager.add_log(L(f"{tag} Deteniendo servidor de Minecraft...", f"{tag} Stopping Minecraft server..."), "system")
    # G8: dos fases — BDS muerto primero, despues el wrapper completo
    # (backup final de cierre incluido) antes de tocar binarios o mundos.
    # Un backup inicial en curso no consume el plazo (_wait_server_stopped).
    stopped, waited = _wait_server_stopped()
    if not stopped:
        waited_s = round(waited)
        manager.add_log(
            L(f"{tag} El servidor no se detuvo en {waited_s}s. "
              "Operación cancelada; si el servidor quedó detenido, reinícialo con ▶ Iniciar.",
              f"{tag} The server did not stop within {waited_s}s. "
              "Operation cancelled; if the server ended up stopped, restart it with ▶ Start."),
            "error",
        )
        return False
    wrapper_exit_timeout = wrapper_exit_timeout_sec()
    if not manager.wrapper_exit_event.wait(timeout=wrapper_exit_timeout):
        manager.add_log(
            L(f"{tag} El wrapper no termino en {wrapper_exit_timeout}s "
              "(incluye el backup final de cierre). Operación cancelada.",
              f"{tag} The wrapper did not finish within {wrapper_exit_timeout}s "
              "(includes the final shutdown backup). Operation cancelled."),
            "error",
        )
        return False
    return True


def cold_backup(trigger="gui_manual"):
    """Backup con el servidor apagado, bajo op_lock durante TODA la copia.

    Un start inmediato modificaria el mundo mientras se comprime, dando un
    backup inconsistente. Re-chequeos atomicos bajo el lock: `start` pudo
    ganar la carrera entre la decision del llamador y la adquisicion, y dos
    solicitudes simultaneas se descartan aqui (FIX G5).
    """
    with manager.op_lock:
        if manager.is_running:
            manager.add_log(
                L("[GUI Backend] El servidor se encendió; backup en frío cancelado (usa el backup en caliente).", "[GUI Backend] The server started; cold backup cancelled (use the hot backup)."),
                "error",
            )
            return
        if manager.backup_in_progress:
            manager.add_log(
                L("[GUI Backend] Ya hay un backup en frío en curso; solicitud ignorada.", "[GUI Backend] A cold backup is already in progress; request ignored."),
                "error",
            )
            return
        # Re-chequeo bajo op_lock (el endpoint ya lo hizo; el watchdog diario
        # llega directo aqui): con un servidor externo vivo el mundo se esta
        # escribiendo y un backup en frio lo copiaria a medias (2026-10-21).
        from gui_backend.services import external_probe
        is_ext, _reason = external_probe.detect_external_bds()
        if is_ext:
            manager.add_log(
                L("[GUI Backend] Hay una instancia externa del servidor en ejecución; backup en frío cancelado (ese servidor hace sus propios backups).",
                  "[GUI Backend] An external server instance is running; cold backup cancelled (that server makes its own backups)."),
                "error",
            )
            return
        manager.backup_in_progress = True
        manager.update_status()
        manager.add_log(L("[GUI Backend] Ejecutando backup en frío...", "[GUI Backend] Running cold backup..."), "backup")
        try:
            zip_path = auto_backup.create_backup(trigger)
            if zip_path:
                manager.last_backup_time = time.strftime("%H:%M:%S")
                manager.add_log(L(f"[GUI Backend] Backup exitoso: {os.path.basename(zip_path)}", f"[GUI Backend] Backup successful: {os.path.basename(zip_path)}"), "backup")
            else:
                manager.add_log(L("[GUI Backend] Error en backup: no se produjo un ZIP (revisa la consola del servidor).", "[GUI Backend] Backup error: no ZIP was produced (check the server console)."), "error")
        except Exception as e:
            manager.add_log(L(f"[GUI Backend] Error en backup: {e}", f"[GUI Backend] Backup error: {e}"), "error")
        finally:
            manager.backup_in_progress = False
            manager.note_backups_changed()
