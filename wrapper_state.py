"""Estado compartido y constantes de ejecucion del wrapper."""

import multiprocessing
import os
import threading


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_EXE = os.path.join(BASE_DIR, "bedrock_server.exe")
WATCHDOG_HOLDING_TIMEOUT_SEC = 60
LIST_SYNC_INTERVAL_SEC = 60
FINAL_BACKUP_LOCK_WAIT_SEC = 5
FINAL_BACKUP_TIMEOUT_SEC = 240
WORKER_COMPRESSION_TIMEOUT_SEC = 120
# Escala de timeouts de backup segun el tamano SIN comprimir (H1-2026-09-25):
# los valores base estaban calibrados para mundos pequenos y un mundo de
# varios GB no comprime en 120s (el worker se mataba en cada ciclo) ni cierra
# en 240s (el backup de cierre, en hilo daemon, se perdia al salir el
# proceso). El timeout efectivo NUNCA baja de los valores base historicos.
BACKUP_TIMEOUT_SEC_PER_GB = 120
BACKUP_TIMEOUT_MAX_SEC = 3600


def scaled_backup_timeout_sec(total_bytes, base_sec, sec_per_gb=None):
    """Timeout de backup proporcional al tamano sin comprimir, con piso y tope.

    Fuente unica de la escala: la usan el wait del worker de compresion
    (wrapper_backup.execute_backup_worker) y el join del backup de cierre
    (server_wrapper). Con tamano desconocido (<=0) devuelve el base.
    """
    if sec_per_gb is None:
        sec_per_gb = BACKUP_TIMEOUT_SEC_PER_GB
    if not isinstance(total_bytes, int) or total_bytes <= 0:
        return base_sec
    extra = int((total_bytes / float(1024 ** 3)) * sec_per_gb)
    return min(max(base_sec, base_sec + extra), BACKUP_TIMEOUT_MAX_SEC)


# Join del worker caliente al cerrar: su PROPIO timeout + margen, para que el
# worker procese siempre su "suicidio" (CASO A de execute_backup_worker) antes
# que la red de seguridad del cierre maestro (dos rutas matando el mismo proceso
# a la vez era la carrera de DOCUMENTACION_ARQUITECTURA_V5 §3). 135 es el PISO
# (120 + 15); con un snapshot grande el timeout del worker escala y el join debe
# escalar con el (worker_join_timeout_sec), no quedarse en el fijo.
WORKER_JOIN_MARGIN_SEC = 15
WORKER_JOIN_ON_SHUTDOWN_SEC = WORKER_COMPRESSION_TIMEOUT_SEC + WORKER_JOIN_MARGIN_SEC


def worker_join_timeout_sec(worker_timeout_sec=None):
    """Tope del join de cierre para el worker activo (>= WORKER_JOIN_ON_SHUTDOWN_SEC).

    `worker_timeout_sec` es el timeout con el que arranco el worker
    (`active_worker_timeout_sec`); sin worker o con valor invalido, el piso.
    """
    if (not isinstance(worker_timeout_sec, (int, float))
            or isinstance(worker_timeout_sec, bool) or worker_timeout_sec <= 0):
        return WORKER_JOIN_ON_SHUTDOWN_SEC
    return max(WORKER_JOIN_ON_SHUTDOWN_SEC, worker_timeout_sec + WORKER_JOIN_MARGIN_SEC)


def shutdown_extra_sec(total_bytes):
    """Segundos que el tamano del mundo anade, sobre los pisos, al cierre del wrapper.

    Peor caso tras la muerte de BDS: join del worker caliente + backup final.
    Fuente unica de la espera de fase 2 de la GUI
    (gui_backend.services.lifecycle.wrapper_exit_timeout_sec): la GUI suma esto
    a su piso WRAPPER_EXIT_TIMEOUT_SEC para no abortar mientras el wrapper sigue
    dentro de sus propios timeouts escalados. 0 con tamano desconocido o chico.
    """
    join = worker_join_timeout_sec(
        scaled_backup_timeout_sec(total_bytes, WORKER_COMPRESSION_TIMEOUT_SEC))
    final = scaled_backup_timeout_sec(total_bytes, FINAL_BACKUP_TIMEOUT_SEC)
    return (join - WORKER_JOIN_ON_SHUTDOWN_SEC) + (final - FINAL_BACKUP_TIMEOUT_SEC)


# Tope del join tras matar el proceso de compresion (TerminateProcess es
# inmediato; el tope solo evita que un wait colgado retenga state_lock).
WORKER_KILL_JOIN_TIMEOUT_SEC = 10
RETRY_BACKOFF_BASE_SEC = 5
RETRY_BACKOFF_MAX_SEC = 60
MAX_CONSECUTIVE_SNAPSHOT_RETRIES = 10
BDS_STOP_TIMEOUT_SEC = 60


state_lock = threading.Lock()
stdin_lock = threading.Lock()
backup_ipc_lock = multiprocessing.Lock()

players_online = set()
backup_in_progress = False
backup_dispatched = False
watchdog_fired = False
shutting_down = False
shutdown_requested_at = 0.0
last_backup_completed_time = 0
save_hold_timestamp = 0
backup_thread = None
active_compress_process = None
# Timeout efectivo (escalado) del worker caliente en curso; 0 = ninguno. Lo
# publica execute_backup_worker bajo state_lock y el cierre lo lee para el join.
active_worker_timeout_sec = 0
last_save_snapshot = []
save_query_ready_seen = False
backup_cancel_event = None
expecting_list_names = False
last_snapshot_update_time = 0.0
snapshot_retry_count = 0
snapshot_retry_at = 0.0
server_process = None
