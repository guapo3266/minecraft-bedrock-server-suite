"""Entry point y fachada de compatibilidad del wrapper de BDS.

Mapa de responsabilidades:
  - wrapper_state.py: constantes, locks y estado mutable unico.
  - wrapper_console.py: patrones y parsers puros del log de BDS.
  - wrapper_events.py: canal IPC NDJSON wrapper -> GUI.
  - wrapper_schedule.py: configuracion y helpers de programacion.
  - wrapper_backup.py: ciclo caliente, worker y backup manual.
  - server_wrapper.py: entry point, consola, scheduler, apagado y backup final.

Este archivo sigue siendo el nombre que lanzan los .bat y la GUI. Sus
re-exports son superficie publica de facto para tests y gui_backend; los
accesos canonicos al estado y a los nombres movidos viven en sus modulos.
"""

import json
import subprocess
import threading
import multiprocessing
import sys
import time
import re
import os

import auto_backup
import windows_process_guard as wpg

from console_lang import L

# Superficie publica de facto: tests y gui_backend importan desde aqui.
# No eliminar estos re-exports al reorganizar el wrapper.
from wrapper_console import (
    BDS_PLAYER_CONNECTED,
    BDS_PLAYER_DISCONNECTED,
    BDS_SAVE_READY,
    BDS_PLAYERS_LIST_HEAD,
    _RE_PLAYER_CONNECT,
    _RE_PLAYER_DISCONNECT,
    _RE_PLAYERS_LIST,
    _RE_VERSION,
    _strip_log_prefix,
    parse_save_query_files,
)
from wrapper_events import (
    EVENTS_DIR,
    EVENTS_RETENTION_DAYS,
    _emit_event,
    _reset_events_for_tests,
    _rotate_old_events,
)
import wrapper_schedule
from wrapper_schedule import (
    SCHEDULE_CONFIG_PATH,
    SCHEDULE_STATE_PATH,
    SCHEDULE_DEFAULTS,
    _schedule_cfg_cache,
    last_daily_backup_date,
    _coerce_schedule_value,
    _load_schedule_config,
    _load_last_daily_backup_date,
    _save_last_daily_backup_date,
    _should_start_backup,
    _crossed_daily_time,
)
import wrapper_state as wstate
import wrapper_backup
from wrapper_backup import (
    mark_corrupt_zip,
    _is_snapshot_failure,
    _snapshot_retry_delay,
    _FileCancelEvent,
    _force_kill_compress_process,
    execute_backup_worker,
    _begin_manual_hot_backup,
)
from wrapper_state import (
    BASE_DIR,
    SERVER_EXE,
    WATCHDOG_HOLDING_TIMEOUT_SEC,
    LIST_SYNC_INTERVAL_SEC,
    FINAL_BACKUP_LOCK_WAIT_SEC,
    FINAL_BACKUP_TIMEOUT_SEC,
    WORKER_COMPRESSION_TIMEOUT_SEC,
    WORKER_JOIN_ON_SHUTDOWN_SEC,
    RETRY_BACKOFF_BASE_SEC,
    RETRY_BACKOFF_MAX_SEC,
    MAX_CONSECUTIVE_SNAPSHOT_RETRIES,
    BDS_STOP_TIMEOUT_SEC,
    state_lock,
    stdin_lock,
    backup_ipc_lock,
    players_online,
    backup_in_progress,
    backup_dispatched,
    watchdog_fired,
    shutting_down,
    shutdown_requested_at,
    last_backup_completed_time,
    save_hold_timestamp,
    backup_thread,
    active_compress_process,
    last_save_snapshot,
    save_query_ready_seen,
    backup_cancel_event,
    expecting_list_names,
    last_snapshot_update_time,
    snapshot_retry_count,
    snapshot_retry_at,
    server_process,
)

# ═══════════════════════════════════════════════════════════════
# ADVERTENCIA: Las detecciones de jugadores y save query dependen de
# strings literales en ingles. Si BDS cambia el formato de log o el
# idioma, estas detecciones fallaran silenciosamente.
#   - "Player connected:" / "Player disconnected:" -> players_online
#   - "Data saved. Files are now ready to be copied." -> save_query_ready_seen
#   - "There are X/Y players online:" -> list de jugadores
# Si sospechas que esto fallo, revisa los backups en caliente.
# ═══════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════
# Envio de comandos al servidor
# ═══════════════════════════════════════════════════════════════
def send_command(cmd):
    """Envía un comando al servidor de forma segura ignorando tuberías rotas o stdin cerrado."""
    try:
        with wstate.stdin_lock:
            if wstate.server_process and wstate.server_process.poll() is None and wstate.server_process.stdin:
                wstate.server_process.stdin.write(cmd + "\n")
                wstate.server_process.stdin.flush()
    except (BrokenPipeError, OSError, ValueError):
        pass
    except Exception as e:
        print(L(f"[Wrapper] Error enviando comando '{cmd}': {e}", f"[Wrapper] Error sending command '{cmd}': {e}"))


wrapper_backup.set_command_sender(lambda cmd: send_command(cmd))

# ═══════════════════════════════════════════════════════════════
# Hilo lector de stdout del servidor
# ═══════════════════════════════════════════════════════════════
def read_stdout():
    """Lee la salida del servidor, detecta eventos, parsea save query y despacha worker."""
    lines_waited_for_list = 0

    while True:
        try:
            line = wstate.server_process.stdout.readline()
            if not line:
                break

            # Impresión segura en stdout sin crashear por UnicodeEncodeError
            try:
                sys.stdout.write(line)
                sys.stdout.flush()
            except Exception:
                pass

            # Limpieza de prefijo de log y filtro anti-spoofing de chat (<Jugador>)
            clean_line = _strip_log_prefix(line).strip()
            is_chat = clean_line.startswith("<")

            match_conn = None
            match_disc = None

            if not is_chat:
                # --- Versión del servidor (eco de la línea de arranque de BDS) ---
                m_ver = _RE_VERSION.search(clean_line)
                if m_ver:
                    _emit_event("version_captured", version=m_ver.group(1))

                # --- Detectar conexión de jugador ---
                match_conn = _RE_PLAYER_CONNECT.search(clean_line)
                if match_conn:
                    name = match_conn.group(1).strip()
                    with wstate.state_lock:
                        wstate.players_online.add(name)
                    _emit_event("player_connected", name=name, xuid=match_conn.group(2))

                # --- Detectar desconexión de jugador ---
                match_disc = _RE_PLAYER_DISCONNECT.search(clean_line)
                if match_disc:
                    name = match_disc.group(1).strip()
                    with wstate.state_lock:
                        wstate.players_online.discard(name)
                    _emit_event("player_disconnected", name=name, xuid=match_disc.group(2))

                # --- Sincronización con comando 'list' ---
                with wstate.state_lock:
                    is_expecting_list = (
                        wstate.expecting_list_names and not wstate.backup_in_progress
                    )

                match_list = _RE_PLAYERS_LIST.search(clean_line)
                if match_list:
                    count = int(match_list.group(1))
                    names_str = match_list.group(2).strip()
                    with wstate.state_lock:
                        if count == 0:
                            wstate.players_online.clear()
                            wstate.expecting_list_names = False
                        elif names_str:
                            parsed_names = {n.strip() for n in names_str.split(",") if n.strip()}
                            if parsed_names:
                                wstate.players_online.clear()
                                wstate.players_online.update(parsed_names)
                                lines_waited_for_list = 0
                            wstate.expecting_list_names = False
                        else:
                            wstate.expecting_list_names = True
                            lines_waited_for_list = 0
                elif is_expecting_list:
                    lines_waited_for_list += 1
                    if lines_waited_for_list > 10:
                        with wstate.state_lock:
                            wstate.expecting_list_names = False
                    else:
                        if line.strip().startswith("["):
                            pass
                        else:
                            stripped = clean_line
                            if stripped and stripped.lower() not in ("quit correctly",):
                                parsed_names = {n.strip() for n in stripped.split(",") if n.strip()}
                                if parsed_names:
                                    with wstate.state_lock:
                                        wstate.players_online.clear()
                                        wstate.players_online.update(parsed_names)
                                        wstate.expecting_list_names = False
                                    lines_waited_for_list = 0

            # --- Detectar respuesta exitosa de save query ---
            save_ready_in_line = (BDS_SAVE_READY in clean_line) if not is_chat else False

            # --- Parsear líneas de respuesta de 'save query' (Archivos y truncado de bytes) ---
            parsed_files = parse_save_query_files(clean_line) if not is_chat else []

            if save_ready_in_line or parsed_files or wstate.save_query_ready_seen:
                with wstate.state_lock:
                    is_waiting = wstate.backup_in_progress and not wstate.backup_dispatched

                    if is_waiting and save_ready_in_line:
                        wstate.save_query_ready_seen = True
                        wstate.last_save_snapshot = []
                        wstate.last_snapshot_update_time = time.time()

                    # Fix: nunca tratar una línea de conexión/desconexión de jugador
                    # como parte del listado de archivos de 'save query' (puede
                    # coincidir con el patrón "texto:numero" si el log no trae
                    # espacio tras "xuid:").
                    if is_waiting and parsed_files and wstate.save_query_ready_seen and not match_conn and not match_disc:
                        existing_paths = {path for path, _ in wstate.last_save_snapshot}
                        for item in parsed_files:
                            if item[0] not in existing_paths:
                                wstate.last_save_snapshot.append(item)
                                existing_paths.add(item[0])
                        wstate.last_snapshot_update_time = time.time()

        except Exception as e:
            try:
                print(L(f"[Wrapper] [WARN] Error en read_stdout: {type(e).__name__}: {e}", f"[Wrapper] [WARN] Error in read_stdout: {type(e).__name__}: {e}"))
            except Exception:
                pass

# ═══════════════════════════════════════════════════════════════
# HILO scheduler: Reloj maestro, Watchdog ATÓMICO y Sincronización
# ═══════════════════════════════════════════════════════════════
def backup_scheduler():
    """Reloj maestro defensivo con evaluación e intervenciones de estado 100% atómicas."""
    last_list_sync = time.time()
    last_save_query = 0.0
    wrapper_schedule.last_daily_backup_date = wrapper_schedule._load_last_daily_backup_date()

    while True:
        try:
            time.sleep(1)

            if wstate.server_process and wstate.server_process.poll() is not None:
                break

            should_send_list = False
            should_send_resume = False
            should_send_query = False
            should_send_hold = False

            now = time.time()

            # --- EVALUACIÓN DE ESTADO 100% ATÓMICA ---
            with wstate.state_lock:
                if wstate.shutting_down:
                    break

                # Sincronización de jugadores (solo en IDLE)
                if (now - last_list_sync) > wstate.LIST_SYNC_INTERVAL_SEC and not wstate.backup_in_progress:
                    should_send_list = True
                    last_list_sync = now

                if wstate.backup_in_progress:
                    if not wstate.backup_dispatched:
                        # Si tenemos archivos recolectados y pasaron >1.5s sin nuevas líneas, despachar worker
                        if wstate.save_query_ready_seen and len(wstate.last_save_snapshot) > 0 and (now - wstate.last_snapshot_update_time) >= 5.0:  # Aumentado de 1.5s a 5s para evitar snapshots incompletos bajo carga
                            snapshot_copy = list(wstate.last_save_snapshot)
                            wstate.backup_dispatched = True
                            wstate.save_query_ready_seen = False
                            wstate.backup_cancel_event = wrapper_backup._FileCancelEvent(os.path.join(os.environ.get("TEMP", "."), "bw_cancel_%d_%s.mark" % (int(time.time() * 1000), os.urandom(4).hex())))
                            snapshot_len = len(snapshot_copy)
                            worker_to_start = threading.Thread(
                                target=wrapper_backup.execute_backup_worker,
                                args=(snapshot_copy, wstate.backup_cancel_event),
                                daemon=True
                            )
                            wstate.backup_thread = worker_to_start
                            print(L(f"[Wrapper] Despachando worker (vía timeout de resguardo) con snapshot ({snapshot_len} archivos)...", f"[Wrapper] Dispatching worker (via fallback timeout) with snapshot ({snapshot_len} files)..."))
                            worker_to_start.start()
                        # Estado HOLDING: verificar Watchdog de 60s
                        elif (now - wstate.save_hold_timestamp) > wstate.WATCHDOG_HOLDING_TIMEOUT_SEC:
                            print(L("[Wrapper] [WARN] Servidor no respondio a save query en 60s.", "[Wrapper] [WARN] Server did not respond to save query in 60s."))
                            print(L("[Wrapper]          Forzando save resume.", "[Wrapper]          Forcing save resume."))
                            wstate.backup_in_progress = False
                            wstate.backup_dispatched = False
                            wstate.save_query_ready_seen = False
                            wstate.watchdog_fired = True
                            wstate.last_backup_completed_time = now
                            should_send_resume = True
                        else:
                            if not wstate.save_query_ready_seen and (now - last_save_query) >= 3:
                                should_send_query = True
                                last_save_query = now
                else:
                    # Estado IDLE: evaluar si corresponde iniciar ciclo de backup.
                    # Intervalo configurable (data/schedule_config.json), reintento
                    # por snapshot incompleto (backoff: snapshot_retry_at) y hora
                    # fija diaria (dispara aunque no haya jugadores).
                    cfg = wrapper_schedule._load_schedule_config()
                    interval_due = (now - wstate.last_backup_completed_time) > (cfg["backup_interval_min"] * 60)
                    retry_due = wstate.snapshot_retry_at > 0 and now >= wstate.snapshot_retry_at
                    daily_due = wrapper_schedule._crossed_daily_time(
                        time.localtime(now),
                        cfg["daily_backup_time"],
                        wrapper_schedule.last_daily_backup_date,
                    )
                    accion = wrapper_schedule._should_start_backup(
                        interval_due, retry_due, daily_due, len(wstate.players_online), cfg
                    )
                    if accion == "start":
                        if daily_due:
                            wrapper_schedule.last_daily_backup_date = time.strftime("%Y-%m-%d")
                            wrapper_schedule._save_last_daily_backup_date(
                                wrapper_schedule.last_daily_backup_date
                            )
                            print(L(f"[Wrapper] Backup diario programado ({cfg['daily_backup_time']}). Iniciando backup en caliente...",
                                    f"[Wrapper] Daily scheduled backup ({cfg['daily_backup_time']}). Starting hot backup..."))
                        elif len(wstate.players_online) > 0:
                            print(L(f"[Wrapper] Hay {len(wstate.players_online)} jugador(es) online. Iniciando backup en caliente...",
                                    f"[Wrapper] There are {len(wstate.players_online)} player(s) online. Starting hot backup..."))
                        else:
                            print(L("[Wrapper] Intervalo de backup vencido. Iniciando backup en caliente...",
                                    "[Wrapper] Backup interval elapsed. Starting hot backup..."))
                        wstate.backup_in_progress = True
                        wstate.backup_dispatched = False
                        wstate.watchdog_fired = False
                        wstate.save_query_ready_seen = False
                        wstate.backup_cancel_event = None
                        wstate.save_hold_timestamp = now
                        wstate.last_save_snapshot = []
                        wstate.expecting_list_names = False  # Fix: no dejar una continuación de 'list' pendiente
                        wstate.snapshot_retry_at = 0.0  # consumir el disparador del reintento
                        should_send_hold = True
                    elif accion == "skip":
                        wstate.last_backup_completed_time = now

            # --- EJECUCIÓN DE COMANDOS FUERA DEL LOCK ---
            # Sin deadlock: los comandos se ejecutan sin retener state_lock.
            # TOCTOU existe: el estado puede cambiar entre la evaluación y la ejecución.
            #   Esto es seguro porque los comandos aquí despachados son IDEMPOTENTES
            #   (save hold/resume/query, list). No agregar comandos no idempotentes aquí.
            if should_send_list:
                send_command("list")

            if should_send_resume:
                send_command("save resume")

            if should_send_query:
                send_command("save query")

            if should_send_hold:
                send_command("save hold")

        except Exception as e:
            try:
                print(L(f"[Wrapper] [WARN] Excepción no esperada en backup_scheduler: {e}", f"[Wrapper] [WARN] Unexpected exception in backup_scheduler: {e}"))
            except Exception:
                pass

# ═══════════════════════════════════════════════════════════════
# Apagado del servidor
# ═══════════════════════════════════════════════════════════════
def initiate_shutdown(reason="shutdown"):
    """
    Inicia un apagado coordinado y seguro del servidor:
    1. Marca shutting_down = True de forma atómica.
    2. Cancela cualquier backup caliente en curso y libera save hold (save resume).
    3. Envía el comando 'stop' al proceso del servidor si aún sigue vivo.
    """
    cancel_worker = None
    should_send_resume = False
    should_send_stop = False

    with wstate.state_lock:
        if not wstate.shutting_down:
            wstate.shutting_down = True
            wstate.shutdown_requested_at = time.time()  # H1: arranca el reloj del tope de stop
            print(L(f"\n[Wrapper] Apagado iniciado ({reason}).", f"\n[Wrapper] Shutdown initiated ({reason})."))
            _emit_event("shutdown_initiated", reason=str(reason))
            if wstate.backup_in_progress:
                print(L("[Wrapper] Cancelando backup caliente en curso antes de detener el servidor...", "[Wrapper] Cancelling running hot backup before stopping the server..."))
                cancel_worker = wstate.backup_cancel_event
                should_send_resume = True
                wstate.backup_in_progress = False
                wstate.backup_dispatched = False
                wstate.save_query_ready_seen = False
                wstate.backup_cancel_event = None
                wstate.watchdog_fired = True
            should_send_stop = True
        else:
            print(L(f"\n[Wrapper] Apagado ya en progreso, ignorando ({reason})...", f"\n[Wrapper] Shutdown already in progress, ignoring ({reason})..."))

    if cancel_worker:
        cancel_worker.set()

    if should_send_resume:
        send_command("save resume")

    if should_send_stop:
        print(L("[Wrapper] Enviando comando 'stop' al servidor...", "[Wrapper] Sending 'stop' command to the server..."))
        send_command("stop")

# ═══════════════════════════════════════════════════════════════
# Hilo lector de stdin (comandos del usuario)
# ═══════════════════════════════════════════════════════════════
def read_stdin():
    """Lee comandos del usuario y los reenvía al servidor."""
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            cmd = line.strip()
            if not cmd:
                continue

            with wstate.state_lock:
                if wstate.shutting_down:
                    break

            if cmd.lower() == "backup":
                started = wrapper_backup._begin_manual_hot_backup()
                if started:
                    send_command("save hold")
                    print(L("[Wrapper] Backup manual solicitado; ciclo caliente iniciado.", "[Wrapper] Manual backup requested; hot cycle started."))
                else:
                    print(L("[Wrapper] Ya hay un backup en curso; solicitud manual ignorada.", "[Wrapper] A backup is already in progress; manual request ignored."))
            elif cmd.lower() == "stop":
                initiate_shutdown("comando 'stop' en consola")
                break
            else:
                send_command(cmd)
        except Exception:
            break

# ═══════════════════════════════════════════════════════════════
# Backup final de cierre
# ═══════════════════════════════════════════════════════════════
def execute_final_backup():
    """Hilo efímero para el backup de cierre."""
    try:
        result = auto_backup.create_backup("cierre", file_snapshot=None, wait_lock_timeout_sec=wstate.FINAL_BACKUP_LOCK_WAIT_SEC, external_lock=wstate.backup_ipc_lock)
        if not result:
            print(L("[Wrapper] El backup final no produjo un ZIP válido o abortó por timeout.", "[Wrapper] The final backup did not produce a valid ZIP or was aborted by timeout."))
    except Exception as e:
        print(L(f"[Wrapper] Falló el backup final: {e}", f"[Wrapper] Final backup failed: {e}"))

def should_run_initial_backup():
    """Lee backup-inicio de server.properties (default: True).

    Permite desactivar el backup inicial en entornos con políticas restrictivas
    donde no sea posible aplicar exclusiones de antivirus.
    """
    props_path = os.path.join(wstate.BASE_DIR, "server.properties")
    if os.path.exists(props_path):
        try:
            with open(props_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("backup-inicio="):
                        val = line.split("=", 1)[1].strip().lower()
                        return val not in ("false", "0", "no", "off")
        except Exception:
            pass
    return True

# ═══════════════════════════════════════════════════════════════
# PUNTO DE ENTRADA PRINCIPAL
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    wrapper_mutex = wpg.NamedMutex(f"BDS_Wrapper_{wpg.get_installation_hash(wstate.BASE_DIR)}")
    if wrapper_mutex.already_exists or not wrapper_mutex.acquire(timeout_ms=100):
        print(L("[Wrapper] [ERROR] Ya hay una instancia del wrapper en ejecución para este servidor. Abortando.",
                "[Wrapper] [ERROR] An instance of the wrapper is already running for this server. Aborting."))
        wrapper_mutex.close()
        sys.exit(1)

    bds_job = None
    print("=========================================================")
    print(L("  INICIANDO SERVIDOR CON WRAPPER", "  STARTING SERVER WITH WRAPPER"))
    print("=========================================================")

    # Recuperación de restauraciones interrumpidas (.bak o .restore_staging_*)
    try:
        auto_backup.recover_interrupted_restores(wstate.BASE_DIR)
    except Exception as e:
        print(L(f"[Wrapper] [WARN] Error en recuperación de restauraciones: {e}", f"[Wrapper] [WARN] Error in restore recovery: {e}"))

    # Canal de eventos: rotar viejos y anunciar el boot (la GUI usa este
    # evento como señal de "canal vivo" y pasa a consumir eventos como
    # fuente autoritativa; sin el, mantiene su parseo de logs).
    _rotate_old_events()
    _emit_event("wrapper_started", pid=os.getpid(), initial_backup=should_run_initial_backup())

    # Backup inicial (antes de arrancar el proceso de Bedrock)
    if should_run_initial_backup():
        t_start_initial_backup = time.time()
        try:
            auto_backup.create_backup("inicio", file_snapshot=None, external_lock=wstate.backup_ipc_lock)
        except Exception as e:
            print(L(f"[Wrapper] Error en backup inicial: {e}", f"[Wrapper] Error in initial backup: {e}"))
        initial_backup_duration = time.time() - t_start_initial_backup
        if initial_backup_duration > 30.0:
            print(L(
                f"[Wrapper] [AVISO] El backup inicial tardó {initial_backup_duration:.1f} s (lo normal son ~6 s).\n"
                "          Posible firma de antivirus (Defender MAPS) en el primer acceso tras descargar o sincronizar archivos.\n"
                "          Para optimizarlo, ejecuta como Administrador:\n"
                "          powershell -ExecutionPolicy Bypass -File tools\\setup_defender_exclusions.ps1\n"
                "          (o ejecuta configurar_antivirus.bat / configura backup-inicio=false en server.properties)",
                f"[Wrapper] [ADVISORY] Initial backup took {initial_backup_duration:.1f} s (~6 s is normal).\n"
                "          Possible antivirus real-time scan overhead (Defender MAPS) on first access after sync/download.\n"
                "          To optimize, run as Administrator:\n"
                "          powershell -ExecutionPolicy Bypass -File tools\\setup_defender_exclusions.ps1\n"
                "          (or run configurar_antivirus.bat / set backup-inicio=false in server.properties)",
            ))
    else:
        print(L("[Wrapper] Backup inicial omitido por configuración (backup-inicio=false).", "[Wrapper] Initial backup skipped by configuration (backup-inicio=false)."))

    with wstate.state_lock:
        wstate.last_backup_completed_time = time.time()

    # Iniciar BDS con aislamiento de señales (CREATE_NEW_PROCESS_GROUP)
    try:
        wstate.server_process = subprocess.Popen(
            [wstate.SERVER_EXE],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=wstate.BASE_DIR,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        if sys.platform == "win32":
            bds_job = wpg.create_job_object_for_process(wstate.server_process.pid)
            if not bds_job:
                print(L("[Wrapper] [ERROR] No se pudo configurar el Job Object de Windows para BDS. Abortando.",
                        "[Wrapper] [ERROR] Could not configure Windows Job Object for BDS. Aborting."))
                try:
                    wstate.server_process.kill()
                    wstate.server_process.wait()
                except Exception:
                    pass
                wrapper_mutex.close()
                sys.exit(1)
    except Exception as e:
        print(L(f"[Wrapper] Error al iniciar BDS: {e}", f"[Wrapper] Error starting BDS: {e}"))
        wrapper_mutex.close()
        sys.exit(1)

    # Lanzar hilos de servicio
    threading.Thread(target=read_stdout, daemon=True).start()
    threading.Thread(target=backup_scheduler, daemon=True).start()
    threading.Thread(target=read_stdin, daemon=True).start()

    # --- Loop principal de espera ---
    try:
        while wstate.server_process and wstate.server_process.poll() is None:
            # H1: la ruta normal de 'stop' tambien tiene tope: si BDS cuelga en
            # el apagado, el wrapper no se queda esperandolo para siempre
            # (antes solo la ruta Ctrl+C forzaba la terminacion). El kill
            # efectivo ocurre en el finally, antes del backup final.
            with wstate.state_lock:
                stop_timeout_exceeded = (
                    wstate.shutting_down
                    and (time.time() - wstate.shutdown_requested_at) > wstate.BDS_STOP_TIMEOUT_SEC
                )
            if stop_timeout_exceeded:
                break
            time.sleep(0.5)

    except KeyboardInterrupt:
        initiate_shutdown("Ctrl+C")

        # Esperar cierre del servidor con protección contra doble Ctrl+C
        try:
            if wstate.server_process:
                wstate.server_process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            print(L("[Wrapper] [WARN] Servidor no respondio al cierre. Forzando terminacion...", "[Wrapper] [WARN] Server did not respond to shutdown. Forcing termination..."))
            try:
                wstate.server_process.kill()
                wstate.server_process.wait()
            except Exception:
                pass
        except KeyboardInterrupt:
            print(L("[Wrapper] Terminando proceso del servidor...", "[Wrapper] Terminating server process..."))
            try:
                if wstate.server_process:
                    wstate.server_process.kill()
                    wstate.server_process.wait()
            except Exception:
                pass

    finally:
        # H1: si BDS seguia vivo al salir del loop (tope de stop vencido o
        # ruta Ctrl+C), forzarlo ANTES de la limpieza: el backup final de
        # cierre debe correr sobre un mundo quieto. Idempotente: si BDS ya
        # cerro, poll() no es None y no se toca nada.
        if wstate.server_process is not None and wstate.server_process.poll() is None:
            print(L("[Wrapper] [WARN] BDS no cerro tras el tope de apagado; forzando terminacion...", "[Wrapper] [WARN] BDS did not close after the shutdown timeout; forcing termination..."))
            try:
                wstate.server_process.kill()
                wstate.server_process.wait()
            except Exception:
                pass

        # Limpieza final (intenta completar aunque haya Ctrl+C)
        # G8: marcador legible por la GUI que separa "BDS murió" de "wrapper
        # terminó". La GUI (server_gui_server) espera esta linea para saber que
        # el mundo quedo quieto; NO espera la salida del proceso (que tarda el
        # backup final de cierre, hasta 240s).
        print(L("[Wrapper] BDS detenido. Iniciando limpieza final de cierre...", "[Wrapper] BDS stopped. Starting final shutdown cleanup..."))
        _emit_event("server_stopped", returncode=(wstate.server_process.returncode if wstate.server_process else None))
        try:
            with wstate.state_lock:
                wstate.shutting_down = True
                current_worker = wstate.backup_thread

            # ── Paso 1: Esperar al worker de backup si está activo ──
            if current_worker and current_worker.is_alive():
                print(L(f"[Wrapper] Esperando a que termine el backup en curso (Max {wstate.WORKER_JOIN_ON_SHUTDOWN_SEC}s)...", f"[Wrapper] Waiting for the running backup to finish (Max {wstate.WORKER_JOIN_ON_SHUTDOWN_SEC}s)..."))
                try:
                    current_worker.join(timeout=wstate.WORKER_JOIN_ON_SHUTDOWN_SEC)
                except KeyboardInterrupt:
                    print(L("[Wrapper] Interrupción por teclado durante join del worker.", "[Wrapper] Keyboard interrupt during worker join."))

                if current_worker.is_alive():
                    print(L("[Wrapper] Worker de compresion no termino a tiempo. forzando terminacion del proceso de compresion...", "[Wrapper] Compression worker did not finish in time. Forcing termination of the compression process..."))
                    
                    with wstate.state_lock:
                        proc_to_kill = wstate.active_compress_process
                    if proc_to_kill:
                        wrapper_backup._force_kill_compress_process(proc_to_kill)
                            
                    should_send_resume = False
                    cancel_worker = None
                    with wstate.state_lock:
                        if wstate.backup_in_progress:
                            cancel_worker = wstate.backup_cancel_event
                            wstate.backup_in_progress = False
                            wstate.backup_dispatched = False
                            wstate.save_query_ready_seen = False
                            wstate.backup_cancel_event = None
                            should_send_resume = True

                    if cancel_worker:
                        cancel_worker.set()

                    if should_send_resume:
                        send_command("save resume")
            else:
                should_send_resume = False
                cancel_worker = None
                with wstate.state_lock:
                    if wstate.backup_in_progress:
                        print(L("[Wrapper] Recuperación: enviando save resume residual...", "[Wrapper] Recovery: sending residual save resume..."))
                        cancel_worker = wstate.backup_cancel_event
                        wstate.backup_in_progress = False
                        wstate.backup_dispatched = False
                        wstate.save_query_ready_seen = False
                        wstate.backup_cancel_event = None
                        should_send_resume = True

                if cancel_worker:
                    cancel_worker.set()

                if should_send_resume:
                    send_command("save resume")

            # ── Paso 2: Backup final de cierre ──
            if wstate.server_process and wstate.server_process.returncode is not None and wstate.server_process.returncode != 0:
                print(L(f"[Wrapper] ADVERTENCIA: BDS finalizó con código {wstate.server_process.returncode} (crash/anormal). Creando backup de emergencia...",
                        f"[Wrapper] WARNING: BDS exited with code {wstate.server_process.returncode} (crash/abnormal). Creating emergency backup..."))
                final_thread = threading.Thread(target=lambda: auto_backup.create_backup("cierre_crash"), daemon=True)
            else:
                print(L("[Wrapper] Creando backup final de cierre...", "[Wrapper] Creating final shutdown backup..."))
                final_thread = threading.Thread(target=execute_final_backup, daemon=True)

            final_thread.start()
            try:
                final_thread.join(timeout=wstate.FINAL_BACKUP_TIMEOUT_SEC)
            except KeyboardInterrupt:
                print(L("[Wrapper] Interrupción por teclado durante backup final.", "[Wrapper] Keyboard interrupt during final backup."))

            if final_thread.is_alive():
                print(L(f"[Wrapper] [WARN] Backup de cierre excedio los {wstate.FINAL_BACKUP_TIMEOUT_SEC}s. Finalizando proceso.", f"[Wrapper] [WARN] Shutdown backup exceeded {wstate.FINAL_BACKUP_TIMEOUT_SEC}s. Finalizando proceso."))

            print(L("[Wrapper] Servidor finalizado limpiamente. Adiós.", "[Wrapper] Server finished cleanly. Goodbye."))
        except BaseException as e:
            print(L(f"[Wrapper] Excepción durante limpieza final: {e}", f"[Wrapper] Exception during final cleanup: {e}"))

        wpg.close_job_object(bds_job)
        wrapper_mutex.close()
