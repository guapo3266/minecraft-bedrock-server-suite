"""
server_wrapper.py — V5.0 PRODUCCIÓN ROBUSTA & ATÓMICA
==================================================================
Wrapper de consola para Bedrock Dedicated Server con backups en caliente.

Mejoras V5.0:
  - Protocolo Nativo Bedrock: Extrae la lista de archivos y truncados de bytes de `save query`.
  - Concurrencia Atómica: Evaluaciones y transiciones de estado 100% thread-safe (anti-TOCTOU).
  - Inmunidad contra Muerte Silenciosa: Bloques try-except globales en hilos maestros.
  - Shutdown Protegido: Resiliente a múltiples Ctrl+C durante la fase de limpieza.
  - Anti-Unicode Crash: Redirección segura de logs a stdout.
"""

import subprocess
import threading
import sys
import time
import re
import os

import auto_backup

# ═══════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_EXE = os.path.join(BASE_DIR, "bedrock_server.exe")
BACKUP_INTERVAL_SEC = 30 * 60           # 30 minutos entre backups
WATCHDOG_HOLDING_TIMEOUT_SEC = 60       # Max segundos esperando respuesta de save query
LIST_SYNC_INTERVAL_SEC = 5 * 60         # Cada 5 min, sincronizar jugadores con 'list'
FINAL_BACKUP_TIMEOUT_SEC = 60           # Max segundos para el backup de cierre
WORKER_COMPRESSION_TIMEOUT_SEC = 120    # Tiempo máximo para la compresión del backup
WORKER_JOIN_ON_SHUTDOWN_SEC = 120       # Alineado con timeout de compresión

# ═══════════════════════════════════════════════════════════════
# ESTADO GLOBAL SINCRONIZADO
# ═══════════════════════════════════════════════════════════════
state_lock = threading.Lock()           # Protege TODAS las variables de estado
stdin_lock = threading.Lock()           # Protege escrituras al pipe de stdin del servidor

players_online = set()
backup_in_progress = False
backup_dispatched = False
watchdog_fired = False                  # True si el watchdog mandó resume antes que el worker
shutting_down = False
last_backup_completed_time = 0          # Cuándo terminó el último ciclo de backup
save_hold_timestamp = 0                 # Cuándo se envió save hold (para el watchdog)
backup_thread = None                    # Referencia al hilo worker actual
last_save_snapshot = []                 # Lista de tuplas (rel_path, byte_length) parseadas de save query
save_query_ready_seen = False           # True si llegó "Data saved" y falta capturar la lista de archivos
backup_cancel_event = None              # Señal cooperativa para cancelar la compresión actual

server_process = None


# ═══════════════════════════════════════════════════════════════
# FUNCIÓN AUXILIAR: Envío de comandos seguro
# ═══════════════════════════════════════════════════════════════
def send_command(cmd):
    """Envía un comando al servidor de forma segura ignorando tuberías rotas o stdin cerrado."""
    try:
        with stdin_lock:
            if server_process and server_process.poll() is None and server_process.stdin:
                server_process.stdin.write(cmd + "\n")
                server_process.stdin.flush()
    except (BrokenPipeError, OSError, ValueError):
        pass
    except Exception as e:
        print(f"[Wrapper] Error enviando comando '{cmd}': {e}")


def mark_corrupt_zip(zip_filepath, reason="CORRUPTO"):
    """Renombra un archivo .zip a _POSIBLEMENTE_CORRUPTO si ocurrió una anomalia."""
    if zip_filepath and isinstance(zip_filepath, str) and os.path.exists(zip_filepath):
        corrupt_name = zip_filepath.replace(".zip", f"_{reason}.zip")
        try:
            os.rename(zip_filepath, corrupt_name)
            print(f"[Worker] Backup marcado por desincronización: {os.path.basename(corrupt_name)}")
        except Exception as e:
            print(f"[Worker] No se pudo renombrar el backup {zip_filepath}: {e}")


def parse_save_query_files(line):
    """Extrae pares (ruta_relativa, bytes) de una línea de save query."""
    if ":" not in line or ("/" not in line and "\\" not in line):
        return []

    parsed = []
    for rel_path, size_str in re.findall(r"([^,\r\n]+?):(\d+)", line):
        clean_rel = rel_path.strip()
        if clean_rel:
            parsed.append((clean_rel, int(size_str)))
    return parsed


# ═══════════════════════════════════════════════════════════════
# HILO WORKER: Compresión de archivos (Snapshot Bedrock Nativo)
# ═══════════════════════════════════════════════════════════════
def execute_backup_worker(file_snapshot=None, cancel_event=None):
    """Hilo efímero que comprime el mundo usando el snapshot de Bedrock."""
    global backup_in_progress, backup_dispatched, watchdog_fired, last_backup_completed_time, save_query_ready_seen, backup_cancel_event

    print("[Worker] Iniciando compresión de archivos en hilo separado...")

    result = {"zip": None, "error": None}

    def _compress():
        try:
            result["zip"] = auto_backup.create_backup(
                "periodico",
                file_snapshot=file_snapshot,
                cancel_event=cancel_event,
            )
        except Exception as e:
            result["error"] = e

    comp_thread = threading.Thread(target=_compress, daemon=True)
    comp_thread.start()
    comp_thread.join(timeout=WORKER_COMPRESSION_TIMEOUT_SEC)

    # --- CASO A: Compresión excedió el tiempo máximo (Timeout interno) ---
    if comp_thread.is_alive():
        print(f"[Worker] [CRITICO] Timeout de compresión ({WORKER_COMPRESSION_TIMEOUT_SEC}s).")
        print("[Worker]          Liberando escritura del servidor para evitar congelamiento...")

        if cancel_event:
            cancel_event.set()

        with state_lock:
            was_watchdog = watchdog_fired
            watchdog_fired = True

        if not was_watchdog:
            send_command("save resume")

        with state_lock:
            backup_in_progress = False
            backup_dispatched = False
            save_query_ready_seen = False
            backup_cancel_event = None
            last_backup_completed_time = time.time()

        def _late_cleanup_watcher():
            try:
                comp_thread.join(timeout=180)
                if comp_thread.is_alive():
                    print("[Worker] [ALERTA] Compresión en segundo plano abandonada definitivamente.")
                elif result["zip"]:
                    mark_corrupt_zip(result["zip"], "TIMEOUT_EXCEDIDO")
            except Exception:
                pass

        threading.Thread(target=_late_cleanup_watcher, daemon=True).start()
        return

    # --- CASO B: Compresión terminó a tiempo ---
    if result["error"]:
        print(f"[Worker] [ERROR] Falló la compresión: {result['error']}")
    elif not result["zip"]:
        print("[Worker] [ERROR] El backup no produjo un ZIP válido.")

    with state_lock:
        was_watchdog = watchdog_fired

    if was_watchdog:
        print("[Worker] El watchdog ya había reanudado escrituras previamente.")
        if result["zip"]:
            mark_corrupt_zip(result["zip"], "POSIBLEMENTE_CORRUPTO")
    else:
        if result["zip"]:
            print("[Worker] Compresión exitosa. Reanudando escritura (save resume)...")
        else:
            print("[Worker] Reanudando escritura tras fallo de backup (save resume)...")
        send_command("save resume")

    with state_lock:
        backup_in_progress = False
        backup_dispatched = False
        watchdog_fired = False
        save_query_ready_seen = False
        backup_cancel_event = None
        last_backup_completed_time = time.time()


# ═══════════════════════════════════════════════════════════════
# HILO read_stdout: Lector de la consola del servidor
# ═══════════════════════════════════════════════════════════════
def read_stdout():
    """Lee la salida del servidor, detecta eventos, parsea save query y despacha worker."""
    global players_online, backup_dispatched, backup_thread, last_save_snapshot, save_query_ready_seen, backup_cancel_event

    while True:
        try:
            line = server_process.stdout.readline()
            if not line:
                break

            # Impresión segura en stdout sin crashear por UnicodeEncodeError
            try:
                sys.stdout.write(line)
                sys.stdout.flush()
            except Exception:
                pass

            # --- Detectar conexión de jugador ---
            match_conn = re.search(r"Player connected:\s*(.+?),\s*xuid:", line)
            if match_conn:
                name = match_conn.group(1).strip()
                with state_lock:
                    players_online.add(name)

            # --- Detectar desconexión de jugador ---
            match_disc = re.search(r"Player disconnected:\s*(.+?),\s*xuid:", line)
            if match_disc:
                name = match_disc.group(1).strip()
                with state_lock:
                    players_online.discard(name)

            # --- Sincronización con comando 'list' ---
            match_list = re.search(r"There are (\d+)/\d+ players online:(.*)", line)
            if match_list:
                count = int(match_list.group(1))
                names_str = match_list.group(2).strip()
                with state_lock:
                    if count == 0:
                        players_online.clear()
                    elif names_str:
                        # Extraer lista exacta de nombres devueltos por BDS y actualizar el set in-place
                        parsed_names = {n.strip() for n in names_str.split(",") if n.strip()}
                        if parsed_names:
                            players_online.clear()
                            players_online.update(parsed_names)

            # --- Detectar respuesta exitosa de save query ---
            save_ready_in_line = "Data saved. Files are now ready to be copied." in line

            # --- Parsear líneas de respuesta de 'save query' (Archivos y truncado de bytes) ---
            parsed_files = parse_save_query_files(line)
            worker_to_start = None
            snapshot_len = 0

            if save_ready_in_line or parsed_files:
                with state_lock:
                    is_waiting = backup_in_progress and not backup_dispatched

                    if is_waiting and save_ready_in_line:
                        save_query_ready_seen = True

                    if is_waiting and parsed_files and save_query_ready_seen:
                        last_save_snapshot.extend(parsed_files)

                    should_dispatch = is_waiting and save_query_ready_seen and len(last_save_snapshot) > 0
                    if should_dispatch:
                        snapshot_copy = list(last_save_snapshot)
                        backup_dispatched = True
                        save_query_ready_seen = False
                        backup_cancel_event = threading.Event()
                        snapshot_len = len(snapshot_copy)
                        worker_to_start = threading.Thread(
                            target=execute_backup_worker,
                            args=(snapshot_copy, backup_cancel_event),
                            daemon=True
                        )
                        backup_thread = worker_to_start

            if worker_to_start:
                print(f"[Wrapper] Servidor listo. Despachando worker con snapshot ({snapshot_len} archivos)...")
                worker_to_start.start()

        except Exception as e:
            try:
                print(f"[Wrapper] [WARN] Error en read_stdout: {type(e).__name__}: {e}")
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════
# HILO scheduler: Reloj maestro, Watchdog ATÓMICO y Sincronización
# ═══════════════════════════════════════════════════════════════
def backup_scheduler():
    """Reloj maestro defensivo con evaluación e intervenciones de estado 100% atómicas."""
    global backup_in_progress, backup_dispatched, save_hold_timestamp, watchdog_fired, last_backup_completed_time, last_save_snapshot, save_query_ready_seen, backup_cancel_event

    last_list_sync = time.time()
    last_save_query = 0.0

    while True:
        try:
            time.sleep(1)

            if server_process and server_process.poll() is not None:
                break

            should_send_list = False
            should_send_resume = False
            should_send_query = False
            should_send_hold = False

            now = time.time()

            # --- EVALUACIÓN DE ESTADO 100% ATÓMICA ---
            with state_lock:
                if shutting_down:
                    break

                # Sincronización de jugadores (solo en IDLE)
                if (now - last_list_sync) > LIST_SYNC_INTERVAL_SEC and not backup_in_progress:
                    should_send_list = True
                    last_list_sync = now

                if backup_in_progress:
                    if not backup_dispatched:
                        # Estado HOLDING: verificar Watchdog de 60s
                        if (now - save_hold_timestamp) > WATCHDOG_HOLDING_TIMEOUT_SEC:
                            print("[Wrapper] [PANICO] Servidor no respondió a save query en 60s.")
                            print("[Wrapper]          Forzando save resume de emergencia.")
                            backup_in_progress = False
                            backup_dispatched = False
                            save_query_ready_seen = False
                            watchdog_fired = True
                            last_backup_completed_time = now
                            should_send_resume = True
                        else:
                            if not save_query_ready_seen and (now - last_save_query) >= 3:
                                should_send_query = True
                                last_save_query = now
                else:
                    # Estado IDLE: evaluar si corresponde iniciar ciclo de backup
                    if (now - last_backup_completed_time) > BACKUP_INTERVAL_SEC:
                        if len(players_online) > 0:
                            print(f"[Wrapper] Hay {len(players_online)} jugador(es) online. Iniciando backup en caliente...")
                            backup_in_progress = True
                            backup_dispatched = False
                            watchdog_fired = False
                            save_query_ready_seen = False
                            backup_cancel_event = None
                            save_hold_timestamp = now
                            last_save_snapshot = []
                            should_send_hold = True
                        else:
                            last_backup_completed_time = now

            # --- EJECUCIÓN DE COMANDOS FUERA DEL LOCK (Cero riesgo de deadlock/TOCTOU) ---
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
                print(f"[Wrapper] [WARN] Excepción no esperada en backup_scheduler: {e}")
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════
# HILO read_stdin: Lector de teclado del usuario
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

            with state_lock:
                if shutting_down:
                    break

            send_command(cmd)
            if cmd.lower() == "stop":
                break
        except Exception:
            break


# ═══════════════════════════════════════════════════════════════
# Backup final de cierre (ejecutado en hilo efímero con timeout)
# ═══════════════════════════════════════════════════════════════
def execute_final_backup():
    """Hilo efímero para el backup de cierre."""
    try:
        result = auto_backup.create_backup("cierre", file_snapshot=None)
        if not result:
            print("[Wrapper] El backup final no produjo un ZIP válido.")
    except Exception as e:
        print(f"[Wrapper] Falló el backup final: {e}")


# ═══════════════════════════════════════════════════════════════
# PUNTO DE ENTRADA PRINCIPAL
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=========================================================")
    print("  INICIANDO SERVIDOR CON WRAPPER V5.0 (PRODUCCION ROBUSTA)")
    print("=========================================================")

    # Backup inicial (antes de arrancar el proceso de Bedrock)
    try:
        auto_backup.create_backup("inicio", file_snapshot=None)
    except Exception as e:
        print(f"[Wrapper] Error en backup inicial: {e}")

    with state_lock:
        last_backup_completed_time = time.time()

    # Iniciar BDS con aislamiento de señales (CREATE_NEW_PROCESS_GROUP)
    try:
        server_process = subprocess.Popen(
            [SERVER_EXE],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=BASE_DIR,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    except Exception as e:
        print(f"[Wrapper] Error fatal al iniciar BDS: {e}")
        sys.exit(1)

    # Lanzar hilos de servicio
    threading.Thread(target=read_stdout, daemon=True).start()
    threading.Thread(target=backup_scheduler, daemon=True).start()
    threading.Thread(target=read_stdin, daemon=True).start()

    # --- Loop principal de espera ---
    try:
        while server_process and server_process.poll() is None:
            time.sleep(0.5)

    except KeyboardInterrupt:
        should_send_stop = False
        should_send_resume = False
        cancel_worker = None

        with state_lock:
            if not shutting_down:
                shutting_down = True
                print("\n[Wrapper] Cierre seguro iniciado (Ctrl+C).")
                if backup_in_progress:
                    print("[Wrapper] Cancelando backup caliente en curso antes de detener el servidor...")
                    cancel_worker = backup_cancel_event
                    should_send_resume = True
                    backup_in_progress = False
                    backup_dispatched = False
                    save_query_ready_seen = False
                    backup_cancel_event = None
                    watchdog_fired = True
                should_send_stop = True
            else:
                print("\n[Wrapper] Ignorando Ctrl+C múltiple...")

        if cancel_worker:
            cancel_worker.set()

        if should_send_resume:
            send_command("save resume")

        if should_send_stop:
            print("[Wrapper] Mandando stop...")
            send_command("stop")

        # Esperar cierre del servidor con protección contra doble Ctrl+C
        try:
            if server_process:
                server_process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            print("[Wrapper] [ALERTA] Servidor zombie. Forzando aniquilación...")
            try:
                server_process.kill()
                server_process.wait()
            except Exception:
                pass
        except KeyboardInterrupt:
            print("[Wrapper] Cierre forzado. Matando proceso del servidor...")
            try:
                if server_process:
                    server_process.kill()
                    server_process.wait()
            except Exception:
                pass

    finally:
        # Bloque de apagado ultra-defensivo (inmune a agresiones por Ctrl+C repetidos)
        try:
            with state_lock:
                shutting_down = True
                current_worker = backup_thread

            # ── Paso 1: Esperar al worker de backup si está activo ──
            if current_worker and current_worker.is_alive():
                print(f"[Wrapper] Esperando a que termine el backup en curso (Max {WORKER_JOIN_ON_SHUTDOWN_SEC}s)...")
                try:
                    current_worker.join(timeout=WORKER_JOIN_ON_SHUTDOWN_SEC)
                except KeyboardInterrupt:
                    print("[Wrapper] Interrupción por teclado durante join del worker.")

                if current_worker.is_alive():
                    print("[Wrapper] Worker de compresión excedió el tiempo máximo de cierre. Liberando servidor...")
                    should_send_resume = False
                    cancel_worker = None
                    with state_lock:
                        if backup_in_progress:
                            cancel_worker = backup_cancel_event
                            backup_in_progress = False
                            backup_dispatched = False
                            save_query_ready_seen = False
                            backup_cancel_event = None
                            should_send_resume = True

                    if cancel_worker:
                        cancel_worker.set()

                    if should_send_resume:
                        send_command("save resume")
            else:
                should_send_resume = False
                cancel_worker = None
                with state_lock:
                    if backup_in_progress:
                        print("[Wrapper] Recuperación: enviando save resume residual...")
                        cancel_worker = backup_cancel_event
                        backup_in_progress = False
                        backup_dispatched = False
                        save_query_ready_seen = False
                        backup_cancel_event = None
                        should_send_resume = True

                if cancel_worker:
                    cancel_worker.set()

                if should_send_resume:
                    send_command("save resume")

            # ── Paso 2: Backup final de cierre ──
            if server_process and server_process.returncode is not None and server_process.returncode != 0:
                print("[Wrapper] ADVERTENCIA: El servidor no finalizó con código 0. El backup de cierre puede ser de un estado inconsistente.")

            print("[Wrapper] Creando backup final de cierre...")
            final_thread = threading.Thread(target=execute_final_backup, daemon=True)
            final_thread.start()
            try:
                final_thread.join(timeout=FINAL_BACKUP_TIMEOUT_SEC)
            except KeyboardInterrupt:
                print("[Wrapper] Interrupción por teclado durante backup final.")

            if final_thread.is_alive():
                print(f"[Wrapper] [ALERTA] Backup de cierre excedió los {FINAL_BACKUP_TIMEOUT_SEC}s. Finalizando proceso.")

            print("[Wrapper] Servidor finalizado limpiamente. Adiós.")
        except BaseException as e:
            print(f"[Wrapper] Excepción durante limpieza final: {e}")
