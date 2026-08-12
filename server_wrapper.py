"""
server_wrapper.py — Wrapper para Bedrock Dedicated Server con backups en caliente
==================================================================
Wrapper de consola para Bedrock Dedicated Server con backups en caliente.

Que hace:
  - Protocolo Nativo Bedrock: Extrae la lista de archivos y truncados de bytes de `save query`.
  - Estado protegido con lock para evitar race conditions.
  - try/except en hilos principales para evitar que un fallo silencioso cuelgue el wrapper.
  - Intenta cerrar limpiamente incluso con multiples Ctrl+C.
  - Redireccion de logs con manejo de errores de encoding.
"""

import subprocess
import threading
import multiprocessing
import sys
import time
import re
import os

import auto_backup

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
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_EXE = os.path.join(BASE_DIR, "bedrock_server.exe")
BACKUP_INTERVAL_SEC = 30 * 60           # 30 minutos entre backups
WATCHDOG_HOLDING_TIMEOUT_SEC = 60       # Max segundos esperando respuesta de save query
LIST_SYNC_INTERVAL_SEC = 60             # Cada 60s (modo prueba)
FINAL_BACKUP_LOCK_WAIT_SEC = 5          # Espera mínima por el lock (ya no hay proceso activo)
FINAL_BACKUP_TIMEOUT_SEC = 240          # Max segundos para el backup de cierre (espera + compresión)
WORKER_COMPRESSION_TIMEOUT_SEC = 120    # Tiempo máximo para la compresión del backup
WORKER_JOIN_ON_SHUTDOWN_SEC = 135       # Mayor que el timeout del worker para evitar colisión
RETRY_BACKOFF_BASE_SEC = 5              # Backoff inicial entre reintentos de snapshot
RETRY_BACKOFF_MAX_SEC = 60              # Tope del backoff exponencial
MAX_CONSECUTIVE_SNAPSHOT_RETRIES = 10   # Abandono del reintento hasta el proximo intervalo normal
BDS_STOP_TIMEOUT_SEC = 60               # H1: max segundos que BDS tiene para cerrar tras 'stop'
                                        # antes de forzar su terminacion. La GUI espera
                                        # SERVER_STOP_TIMEOUT_SEC (75s) en su fase 1: el
                                        # wrapper siempre actua primero y ella solo observa.

# ═══════════════════════════════════════════════════════════════
# PATRONES DE DETECCION DEL LOG DE BDS (D5)
# ───────────────────────────────────────────────────────────────
# Strings ingleses que BDS imprime en el log. Si Mojang cambia el formato,
# la deteccion falla SILENCIOSAMENTE: se pierden jugadores online y el save
# query (los backups frios siguen funcionando). Centralizados aqui para
# revisarlos en un solo lugar; la GUI los importa de este modulo.
# ═══════════════════════════════════════════════════════════════
BDS_PLAYER_CONNECTED = "Player connected:"
BDS_PLAYER_DISCONNECTED = "Player disconnected:"
BDS_SAVE_READY = "Data saved. Files are now ready to be copied."
BDS_PLAYERS_LIST_HEAD = "players online:"
_RE_PLAYER_CONNECT = re.compile(r"Player\s+connected\s*:\s*(.+?),\s*xuid\s*:", re.IGNORECASE)
_RE_PLAYER_DISCONNECT = re.compile(r"Player\s+disconnected\s*:\s*(.+?),\s*xuid\s*:", re.IGNORECASE)
_RE_PLAYERS_LIST = re.compile(r"There are (\d+)/\d+ players online:(.*)")

# ═══════════════════════════════════════════════════════════════
# ESTADO GLOBAL (protegido por state_lock)
# ═══════════════════════════════════════════════════════════════
state_lock = threading.Lock()           # Protege TODAS las variables de estado
stdin_lock = threading.Lock()           # Protege escrituras al pipe de stdin del servidor

players_online = set()
backup_in_progress = False
backup_dispatched = False
watchdog_fired = False                  # True si el watchdog mandó resume antes que el worker
shutting_down = False
shutdown_requested_at = 0.0             # H1: timestamp del inicio del apagado (tope del stop)
last_backup_completed_time = 0          # Cuándo terminó el último ciclo de backup
save_hold_timestamp = 0                 # Cuándo se envió save hold (para el watchdog)
backup_thread = None                    # Referencia al hilo worker actual
active_compress_process = None          # Referencia al proceso de compresión para aniquilación
backup_ipc_lock = multiprocessing.Lock() # Lock IPC para backups frios del propio wrapper (inicio/cierre);
# el worker subprocess NO lo comparte (usa el lock interno de auto_backup)
last_save_snapshot = []                 # Lista de tuplas (rel_path, byte_length) parseadas de save query
save_query_ready_seen = False           # True si llegó "Data saved" y falta capturar la lista de archivos
backup_cancel_event = None              # Señal cooperativa para cancelar la compresión actual
expecting_list_names = False            # True si se recibió encabezado 'There are X players' y falta leer nombres
last_snapshot_update_time = 0.0         # Timestamp de la última adición a last_save_snapshot
snapshot_retry_count = 0                # Reintentos consecutivos por snapshot incompleto
snapshot_retry_at = 0.0                 # Timestamp del proximo reintento permitido (0 = no programado)

server_process = None

# ═══════════════════════════════════════════════════════════════
# Envio de comandos al servidor
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
    """Renombra un archivo .zip a _POSIBLEMENTE_CORRUPTO si ocurrió una anomalia.

    Idempotente: si el archivo ya lleva el marcador `reason`, no se renombra de
    nuevo (evita nombres _CORRUPTO_CORRUPTO.zip en dobles marcados).
    """
    if zip_filepath and isinstance(zip_filepath, str) and os.path.exists(zip_filepath):
        # Usar rsplit para reemplazar solo la extension final, no .zip intermedios
        base = zip_filepath.rsplit(".zip", 1)[0]
        if base.endswith("_" + reason):
            return
        corrupt_name = f"{base}_{reason}.zip"
        try:
            os.rename(zip_filepath, corrupt_name)
            print(f"[Worker] Backup marcado por desincronización: {os.path.basename(corrupt_name)}")
        except Exception as e:
            print(f"[Worker] No se pudo renombrar el backup {zip_filepath}: {e}")

def parse_save_query_files(line):
    """Extrae pares (ruta_relativa, bytes) de una línea de save query."""
    # Limpia prefijos de log de Bedrock ([YYYY-MM-DD HH:MM:SS:mmm LEVEL] o
    # [LEVEL]) SOLO si van seguidos de espacio. Las rutas de archivo pueden
    # empezar con '[' pero nunca contienen espacios (p.ej. '[/]:0'): el
    # regex anterior comía cualquier '[...]' inicial y las perdía.
    line = re.sub(
        r'^(?:(?:\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}:\d{3} (?:INFO|WARN|ERROR|DEBUG|LOG)\]|\[(?:INFO|WARN|ERROR|DEBUG|LOG)\]) +)+',
        '', line,
    )

    if ":" not in line:
        return []

    parsed = []
    for rel_path, size_str in re.findall(r"([^,\r\n]+?):(\d+)", line):
        clean_rel = rel_path.strip()
        if clean_rel:
            parsed.append((clean_rel, int(size_str)))
    return parsed

def _is_snapshot_failure(error_msg):
    """True si el error del worker merece reintento inmediato del ciclo caliente.

    El worker anota los fallos del modo snapshot con el prefijo "Snapshot:"
    (create_backup en modo snapshot siempre lanza). Se excluyen los fallos
    operativos que un reintento no va a resolver: cancelacion (shutdown en
    curso) y exceso del limite de tamano. El resto de errores (E/S, lock,
    disco) esperan el intervalo normal de backup.
    """
    msg = (error_msg or "").lower()
    if "snapshot" not in msg:
        return False
    if "cancelado" in msg:
        return False
    if "excede el limite" in msg:
        return False
    return True

def _snapshot_retry_delay(attempt):
    """Backoff exponencial entre reintentos de snapshot: 5, 10, 20, ... 60 s tope.

    `attempt` es el numero de reintentos consecutivos ya fallidos (1-based).
    Acota el ciclo cuando BDS responde con snapshots incompletos de forma
    sostenida (el watchdog solo limita cuando BDS NO responde).
    """
    return min(RETRY_BACKOFF_MAX_SEC, RETRY_BACKOFF_BASE_SEC * (2 ** (attempt - 1)))

# ═══════════════════════════════════════════════════════════════
# PROCESO WORKER: Compresión en E/S aislada
# ═══════════════════════════════════════════════════════════════
class _FileCancelEvent:
    """Sustituto de multiprocessing.Event para la senal de cancelacion.

    La senal via ARCHIVO (no via semaforo compartido): el worker de compresion
    ahora se lanza con subprocess (el spawn de multiprocessing se colgaba
    50-120s en el bootstrap con el wrapper + BDS), y un hijo subprocess no
    puede compartir un Event de multiprocessing. La API es identica a
    multiprocessing.Event (is_set/set/clear), asi que los puntos de
    cancelacion existentes no cambian.
    """
    def __init__(self, path):
        self.path = path
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    def is_set(self):
        return os.path.exists(self.path)

    def set(self):
        try:
            open(self.path, "w").close()
        except Exception:
            pass

    def clear(self):
        try:
            os.remove(self.path)
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════════
# Forzar terminacion del proceso de compresion
# ═══════════════════════════════════════════════════════════════
def _force_kill_compress_process(proc):
    """Fuerza la terminacion de un proceso de compresion y reemplaza el lock IPC por uno nuevo."""
    global backup_ipc_lock, active_compress_process
    if not proc or not proc.is_alive():
        return
        
    with state_lock:
        if active_compress_process is not proc:
            return # Ya fue terminado por otro hilo
            
        try:
            proc.kill()
            proc.join()
        except Exception as e:
            print(f"[Wrapper] Error forzando kill del proceso de compresión: {e}")
            
        # Reemplazar el lock IPC (puede quedar en mal estado tras kill)
        backup_ipc_lock = multiprocessing.Lock()
        active_compress_process = None

        # FIX D4: el worker muerto pudo dejar un .tmp a medias; se limpia ya
        # (antes quedaba huerfano hasta el siguiente backup). Bajo state_lock:
        # no puede haber otro backup escribiendo al mismo tiempo.
        try:
            import glob as _glob
            for orphan in _glob.glob(os.path.join(auto_backup.BACKUP_DIR, "*.tmp")):
                try:
                    os.remove(orphan)
                    print(f"[Wrapper] Limpieza: eliminado {os.path.basename(orphan)} tras kill.")
                except Exception:
                    pass
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════════
# Hilo worker de compresion
# ═══════════════════════════════════════════════════════════════
def execute_backup_worker(file_snapshot=None, cancel_event=None):
    """Hilo efímero que orquesta el proceso de compresión de Bedrock."""
    global backup_in_progress, backup_dispatched, watchdog_fired, last_backup_completed_time, save_query_ready_seen, backup_cancel_event, active_compress_process, backup_ipc_lock, snapshot_retry_count, snapshot_retry_at
    try:

        print("[Worker] Iniciando compresion de archivos en proceso separado (subprocess)...")

        import pickle as _pickle
        _base = os.path.dirname(os.path.abspath(__file__))
        _stamp = int(time.time() * 1000)
        _nonce = os.urandom(4).hex()  # nombre no predecible: el .pkl se deserializa con pickle
        _tmpdir = os.environ.get("TEMP", ".")
        _snap_path = os.path.join(_tmpdir, "bw_snap_%d_%s.pkl" % (_stamp, _nonce))
        _marker = os.path.join(_tmpdir, "bw_cancel_%d_%s.mark" % (_stamp, _nonce))
        _result = os.path.join(_tmpdir, "bw_result_%d_%s.pkl" % (_stamp, _nonce))
        _worker = os.path.join(_base, "backup_worker.py")

        try:
            with open(_snap_path, "wb") as _f:
                _pickle.dump(file_snapshot, _f)
            # Si el evento de cancelacion es el nuevo _FileCancelEvent, usar SU
            # archivo como marker (asi los puntos de cancelacion existentes,
            # que llaman a .set(), cancelan de verdad al worker).
            if cancel_event is not None and hasattr(cancel_event, "path"):
                _marker = cancel_event.path
            comp_proc = subprocess.Popen(
                [sys.executable, "-u", _worker, _snap_path, _marker, _result],
                cwd=_base,
                stdin=subprocess.DEVNULL,
            )
            # Shims para compatibilidad con el codigo existente
            # (_force_kill_compress_process usa is_alive/kill/join).
            comp_proc.is_alive = lambda: comp_proc.poll() is None
            comp_proc.join = lambda timeout=None: comp_proc.wait(timeout=timeout)
        except Exception as e:
            print(f"[Worker] [WARN] No se pudo lanzar el worker: {e}")
            for _p in (_snap_path, _marker, _result):
                try:
                    os.remove(_p)
                except Exception:
                    pass
            with state_lock:
                backup_in_progress = False
                backup_dispatched = False
                save_query_ready_seen = False
                backup_cancel_event = None
                watchdog_fired = True
                last_backup_completed_time = time.time()
                snapshot_retry_count = 0
                snapshot_retry_at = 0.0
            send_command("save resume")
            return

        with state_lock:
            active_compress_process = comp_proc

        comp_proc.join(timeout=WORKER_COMPRESSION_TIMEOUT_SEC)

        # --- CASO A: Compresión excedió el tiempo máximo (Timeout interno) ---
        if comp_proc.is_alive():
            print(f"[Worker] [WARN] Timeout de compresion ({WORKER_COMPRESSION_TIMEOUT_SEC}s).")
            print("[Worker]          Terminando proceso de compresion...")
        
            _force_kill_compress_process(comp_proc)

            with state_lock:
                was_watchdog = watchdog_fired
                watchdog_fired = True

            if cancel_event:
                cancel_event.set()

            if not was_watchdog:
                send_command("save resume")

            with state_lock:
                backup_in_progress = False
                backup_dispatched = False
                save_query_ready_seen = False
                backup_cancel_event = None
                last_backup_completed_time = time.time()
                snapshot_retry_count = 0
                snapshot_retry_at = 0.0

            for _p in (_snap_path, _marker, _result):
                try:
                    os.remove(_p)
                except Exception:
                    pass
            return

        # --- CASO B: Compresión terminó a tiempo ---
        with state_lock:
            active_compress_process = None

        try:
            with open(_result, "rb") as _f:
                result = _pickle.load(_f)
        except Exception:
            result = {"zip": None, "error": "El proceso termino sin devolver un resultado"}
        for _p in (_snap_path, _marker, _result):
            try:
                os.remove(_p)
            except Exception:
                pass
        retry_soon = _is_snapshot_failure(result.get("error"))
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
            if retry_soon:
                # Snapshot incompleto: reintentar con backoff exponencial
                # (5, 10, 20, ... 60 s). Sin backoff, un BDS que responde
                # continuamente con snapshots incompletos repetiria el ciclo
                # cada ~10 s indefinidamente; el watchdog solo limita cuando
                # BDS NO responde. Tras MAX intentos consecutivos se abandona
                # hasta el proximo intervalo normal de 30 min.
                snapshot_retry_count += 1
                if snapshot_retry_count >= MAX_CONSECUTIVE_SNAPSHOT_RETRIES:
                    print(f"[Worker] {snapshot_retry_count} reintentos consecutivos de snapshot fallidos; "
                          "se espera el proximo intervalo normal de backup.")
                    snapshot_retry_count = 0
                    snapshot_retry_at = 0.0
                else:
                    delay = _snapshot_retry_delay(snapshot_retry_count)
                    snapshot_retry_at = time.time() + delay
                    print(f"[Worker] Snapshot incompleto: reintento en {delay}s (intento {snapshot_retry_count}).")
                last_backup_completed_time = time.time()
            else:
                # Exito o fallo operativo: el patron de snapshot termina.
                snapshot_retry_count = 0
                snapshot_retry_at = 0.0
                last_backup_completed_time = time.time()

    except Exception as e:
        print(f"[Worker] [WARN] Excepcion en worker de backup: {type(e).__name__}: {e}")
        print("[Worker]          Limpiando estado del worker...")
        with state_lock:
            backup_in_progress = False
            backup_dispatched = False
            save_query_ready_seen = False
            backup_cancel_event = None
            watchdog_fired = True
            last_backup_completed_time = time.time()
            snapshot_retry_count = 0
            snapshot_retry_at = 0.0
        send_command("save resume")

        with state_lock:
            active_compress_process = None
    finally:
        # H3: marcador de FIN incondicional del ciclo de compresion (exito,
        # fallo, timeout, watchdog o excepcion). La GUI resetea su flag
        # backup_in_progress con esta linea; sin el, un backup fallido dejaba
        # el boton de backup en frio bloqueado ("Ya hay un backup en curso")
        # hasta reiniciar la GUI.
        print("[Worker] Backup finalizado")
# ═══════════════════════════════════════════════════════════════
# Hilo lector de stdout del servidor
# ═══════════════════════════════════════════════════════════════
def read_stdout():
    """Lee la salida del servidor, detecta eventos, parsea save query y despacha worker."""
    global players_online, backup_dispatched, backup_thread, last_save_snapshot, save_query_ready_seen, backup_cancel_event, expecting_list_names, last_snapshot_update_time

    lines_waited_for_list = 0

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
            match_conn = _RE_PLAYER_CONNECT.search(line)
            if match_conn:
                name = match_conn.group(1).strip()
                with state_lock:
                    players_online.add(name)

            # --- Detectar desconexión de jugador ---
            match_disc = _RE_PLAYER_DISCONNECT.search(line)
            if match_disc:
                name = match_disc.group(1).strip()
                with state_lock:
                    players_online.discard(name)

            # --- Sincronización con comando 'list' ---
            # Fix: 'list' nunca se envía durante un backup, pero si una continuación
            # quedó pendiente justo cuando arrancó un backup, no debe tratarse una línea
            # de save query (p. ej. "Data saved. Files are now ready to be copied.")
            # como si fuera una lista de nombres de jugadores.
            with state_lock:
                is_expecting_list = expecting_list_names and not backup_in_progress

            match_list = _RE_PLAYERS_LIST.search(line)
            if match_list:
                count = int(match_list.group(1))
                names_str = match_list.group(2).strip()
                with state_lock:
                    if count == 0:
                        players_online.clear()
                        expecting_list_names = False
                    elif names_str:
                        parsed_names = {n.strip() for n in names_str.split(",") if n.strip()}
                        if parsed_names:
                            players_online.clear()
                            players_online.update(parsed_names)
                            lines_waited_for_list = 0  # H3: parseo exitoso, contador consistente
                        expecting_list_names = False
                    else:
                        expecting_list_names = True
                        lines_waited_for_list = 0
            elif is_expecting_list:
                lines_waited_for_list += 1
                if lines_waited_for_list > 10:
                    with state_lock:
                        expecting_list_names = False
                else:
                    # Fix: el chequeo debe hacerse sobre la línea ORIGINAL, no sobre
                    # cleaned_line -- cleaned_line ya tiene el prefijo '[...]' removido,
                    # así que 'cleaned_line.startswith("[")' nunca es True para una
                    # línea real de BDS con timestamp, y el ruido (autosave, chunks,
                    # etc.) se colaba como si fueran nombres de jugadores.
                    if line.strip().startswith("["):
                        pass
                    else:
                        cleaned_line = re.sub(r'^(?:\[.*?\]\s*)+', '', line)
                        stripped = cleaned_line.strip()
                        if stripped and stripped.lower() not in ("quit correctly",):
                            parsed_names = {n.strip() for n in stripped.split(",") if n.strip()}
                            if parsed_names:
                                with state_lock:
                                    players_online.clear()
                                    players_online.update(parsed_names)
                                    expecting_list_names = False
                                lines_waited_for_list = 0  # H3: parseo exitoso, contador consistente

            # --- Detectar respuesta exitosa de save query ---
            save_ready_in_line = BDS_SAVE_READY in line

            # --- Parsear líneas de respuesta de 'save query' (Archivos y truncado de bytes) ---
            parsed_files = parse_save_query_files(line)

            if save_ready_in_line or parsed_files or save_query_ready_seen:
                with state_lock:
                    is_waiting = backup_in_progress and not backup_dispatched

                    if is_waiting and save_ready_in_line:
                        save_query_ready_seen = True
                        last_save_snapshot = []
                        last_snapshot_update_time = time.time()

                    # Fix: nunca tratar una línea de conexión/desconexión de jugador
                    # como parte del listado de archivos de 'save query' (puede
                    # coincidir con el patrón "texto:numero" si el log no trae
                    # espacio tras "xuid:").
                    if is_waiting and parsed_files and save_query_ready_seen and not match_conn and not match_disc:
                        existing_paths = {path for path, _ in last_save_snapshot}
                        for item in parsed_files:
                            if item[0] not in existing_paths:
                                last_save_snapshot.append(item)
                                existing_paths.add(item[0])
                        last_snapshot_update_time = time.time()

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
    global backup_in_progress, backup_dispatched, save_hold_timestamp, watchdog_fired, last_backup_completed_time, last_save_snapshot, save_query_ready_seen, backup_cancel_event, backup_thread, expecting_list_names, snapshot_retry_count, snapshot_retry_at

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
                        # Si tenemos archivos recolectados y pasaron >1.5s sin nuevas líneas, despachar worker
                        if save_query_ready_seen and len(last_save_snapshot) > 0 and (now - last_snapshot_update_time) >= 5.0:  # Aumentado de 1.5s a 5s para evitar snapshots incompletos bajo carga
                            snapshot_copy = list(last_save_snapshot)
                            backup_dispatched = True
                            save_query_ready_seen = False
                            backup_cancel_event = _FileCancelEvent(os.path.join(os.environ.get("TEMP", "."), "bw_cancel_%d_%s.mark" % (int(time.time() * 1000), os.urandom(4).hex())))
                            snapshot_len = len(snapshot_copy)
                            worker_to_start = threading.Thread(
                                target=execute_backup_worker,
                                args=(snapshot_copy, backup_cancel_event),
                                daemon=True
                            )
                            backup_thread = worker_to_start
                            print(f"[Wrapper] Despachando worker (vía timeout de resguardo) con snapshot ({snapshot_len} archivos)...")
                            worker_to_start.start()
                        # Estado HOLDING: verificar Watchdog de 60s
                        elif (now - save_hold_timestamp) > WATCHDOG_HOLDING_TIMEOUT_SEC:
                            print("[Wrapper] [WARN] Servidor no respondio a save query en 60s.")
                            print("[Wrapper]          Forzando save resume.")
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
                    # Estado IDLE: evaluar si corresponde iniciar ciclo de backup.
                    # El ciclo normal (30 min) o el reintento programado por
                    # snapshot incompleto (backoff: snapshot_retry_at).
                    retry_due = snapshot_retry_at > 0 and now >= snapshot_retry_at
                    if (now - last_backup_completed_time) > BACKUP_INTERVAL_SEC or retry_due:
                        if len(players_online) > 0:
                            print(f"[Wrapper] Hay {len(players_online)} jugador(es) online. Iniciando backup en caliente...")
                            backup_in_progress = True
                            backup_dispatched = False
                            watchdog_fired = False
                            save_query_ready_seen = False
                            backup_cancel_event = None
                            save_hold_timestamp = now
                            last_save_snapshot = []
                            expecting_list_names = False  # Fix: no dejar una continuación de 'list' pendiente
                            snapshot_retry_at = 0.0  # consumir el disparador del reintento
                            should_send_hold = True
                        else:
                            last_backup_completed_time = now

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
                print(f"[Wrapper] [WARN] Excepción no esperada en backup_scheduler: {e}")
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
    global shutting_down, backup_in_progress, backup_dispatched, save_query_ready_seen, backup_cancel_event, watchdog_fired, shutdown_requested_at

    cancel_worker = None
    should_send_resume = False
    should_send_stop = False

    with state_lock:
        if not shutting_down:
            shutting_down = True
            shutdown_requested_at = time.time()  # H1: arranca el reloj del tope de stop
            print(f"\n[Wrapper] Apagado iniciado ({reason}).")
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
            print(f"\n[Wrapper] Apagado ya en progreso, ignorando ({reason})...")

    if cancel_worker:
        cancel_worker.set()

    if should_send_resume:
        send_command("save resume")

    if should_send_stop:
        print("[Wrapper] Enviando comando 'stop' al servidor...")
        send_command("stop")

# ═══════════════════════════════════════════════════════════════
# Hilo lector de stdin (comandos del usuario)
# ═══════════════════════════════════════════════════════════════
def _begin_manual_hot_backup():
    """Inicia un ciclo de backup en caliente manual (comando 'backup' por stdin).

    Replica EXACTAMENTE el arranque del ciclo periodico de backup_scheduler():
    misma maquina de estados y mismo lock, para que el scheduler tome el relevo
    sin cambios. Devuelve True si el ciclo arranco, False si ya hay uno en curso.
    """
    global backup_in_progress, backup_dispatched, watchdog_fired, save_query_ready_seen
    global backup_cancel_event, save_hold_timestamp, last_save_snapshot, expecting_list_names
    global snapshot_retry_at
    with state_lock:
        if backup_in_progress:
            return False
        backup_in_progress = True
        backup_dispatched = False
        watchdog_fired = False
        save_query_ready_seen = False
        backup_cancel_event = None
        save_hold_timestamp = time.time()
        last_save_snapshot = []
        expecting_list_names = False
        snapshot_retry_at = 0.0  # el ciclo manual consume cualquier reintento pendiente
    return True

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

            if cmd.lower() == "backup":
                started = _begin_manual_hot_backup()
                if started:
                    send_command("save hold")
                    print("[Wrapper] Backup manual solicitado; ciclo caliente iniciado.")
                else:
                    print("[Wrapper] Ya hay un backup en curso; solicitud manual ignorada.")
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
        result = auto_backup.create_backup("cierre", file_snapshot=None, wait_lock_timeout_sec=FINAL_BACKUP_LOCK_WAIT_SEC, external_lock=backup_ipc_lock)
        if not result:
            print("[Wrapper] El backup final no produjo un ZIP válido o abortó por timeout.")
    except Exception as e:
        print(f"[Wrapper] Falló el backup final: {e}")

# ═══════════════════════════════════════════════════════════════
# PUNTO DE ENTRADA PRINCIPAL
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=========================================================")
    print("  INICIANDO SERVIDOR CON WRAPPER")
    print("=========================================================")

    # Backup inicial (antes de arrancar el proceso de Bedrock)
    try:
        auto_backup.create_backup("inicio", file_snapshot=None, external_lock=backup_ipc_lock)
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
        print(f"[Wrapper] Error al iniciar BDS: {e}")
        sys.exit(1)

    # Lanzar hilos de servicio
    threading.Thread(target=read_stdout, daemon=True).start()
    threading.Thread(target=backup_scheduler, daemon=True).start()
    threading.Thread(target=read_stdin, daemon=True).start()

    # --- Loop principal de espera ---
    try:
        while server_process and server_process.poll() is None:
            # H1: la ruta normal de 'stop' tambien tiene tope: si BDS cuelga en
            # el apagado, el wrapper no se queda esperandolo para siempre
            # (antes solo la ruta Ctrl+C forzaba la terminacion). El kill
            # efectivo ocurre en el finally, antes del backup final.
            with state_lock:
                stop_timeout_exceeded = (
                    shutting_down
                    and (time.time() - shutdown_requested_at) > BDS_STOP_TIMEOUT_SEC
                )
            if stop_timeout_exceeded:
                break
            time.sleep(0.5)

    except KeyboardInterrupt:
        initiate_shutdown("Ctrl+C")

        # Esperar cierre del servidor con protección contra doble Ctrl+C
        try:
            if server_process:
                server_process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            print("[Wrapper] [WARN] Servidor no respondio al cierre. Forzando terminacion...")
            try:
                server_process.kill()
                server_process.wait()
            except Exception:
                pass
        except KeyboardInterrupt:
            print("[Wrapper] Terminando proceso del servidor...")
            try:
                if server_process:
                    server_process.kill()
                    server_process.wait()
            except Exception:
                pass

    finally:
        # H1: si BDS seguia vivo al salir del loop (tope de stop vencido o
        # ruta Ctrl+C), forzarlo ANTES de la limpieza: el backup final de
        # cierre debe correr sobre un mundo quieto. Idempotente: si BDS ya
        # cerro, poll() no es None y no se toca nada.
        if server_process is not None and server_process.poll() is None:
            print("[Wrapper] [WARN] BDS no cerro tras el tope de apagado; forzando terminacion...")
            try:
                server_process.kill()
                server_process.wait()
            except Exception:
                pass

        # Limpieza final (intenta completar aunque haya Ctrl+C)
        # G8: marcador legible por la GUI que separa "BDS murió" de "wrapper
        # terminó". La GUI (server_gui_server) espera esta linea para saber que
        # el mundo quedo quieto; NO espera la salida del proceso (que tarda el
        # backup final de cierre, hasta 240s).
        print("[Wrapper] BDS detenido. Iniciando limpieza final de cierre...")
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
                    print("[Wrapper] Worker de compresion no termino a tiempo. forzando terminacion del proceso de compresion...")
                    
                    with state_lock:
                        proc_to_kill = active_compress_process
                    if proc_to_kill:
                        _force_kill_compress_process(proc_to_kill)
                            
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
                print(f"[Wrapper] [WARN] Backup de cierre excedio los {FINAL_BACKUP_TIMEOUT_SEC}s. Finalizando proceso.")

            print("[Wrapper] Servidor finalizado limpiamente. Adiós.")
        except BaseException as e:
            print(f"[Wrapper] Excepción durante limpieza final: {e}")
