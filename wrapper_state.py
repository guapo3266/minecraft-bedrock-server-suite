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
WORKER_JOIN_ON_SHUTDOWN_SEC = 135
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
last_save_snapshot = []
save_query_ready_seen = False
backup_cancel_event = None
expecting_list_names = False
last_snapshot_update_time = 0.0
snapshot_retry_count = 0
snapshot_retry_at = 0.0
server_process = None
