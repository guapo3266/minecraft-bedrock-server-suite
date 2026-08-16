"""Watchdog de la GUI: re-arranque tras crash, reinicio diario y backup diario en frio.

Opt-in: sin data/schedule_config.json (o con todo desactivado) no hace nada.
El ciclo se parte en _watchdog_tick para testearlo sin hilo; el loop real
duerme WATCHDOG_POLL_SEC y nunca lanza.

Reglas de crash: solo cuenta como crash un wrapper muerto con
manager.stop_requested == False (nadie pidio pararlo desde la GUI ni escribio
'stop' en consola). Backoff escalonado que se reinicia tras un uptime estable.
"""

import json
import os
import threading
import time

from console_lang import L
from server_wrapper import _crossed_daily_time

from gui_backend import config
from gui_backend.state import manager
from gui_backend.services import lifecycle as lifecycle_service
from gui_backend.services import schedule_config as schedule_config_service

STATE_PATH = os.path.join(config.BASE_DIR, "data", "schedule_state_gui.json")

_started = threading.Event()

# Estado del ciclo a nivel de modulo (reseteable desde tests).
crash_restarts = 0
last_crash_restart_at = 0.0
last_daily_restart_date = None
last_daily_cold_backup_date = None
_gui_state_loaded = False


def start():
    """Arranca el hilo del watchdog una sola vez (llamado desde el lifespan)."""
    if _started.is_set():
        return
    _started.set()
    _load_gui_state()
    threading.Thread(target=watchdog_loop, daemon=True, name="gui-watchdog").start()


def watchdog_loop():
    while True:
        try:
            _watchdog_tick()
        except Exception:
            pass  # el watchdog nunca debe tumbar la GUI
        time.sleep(config.WATCHDOG_POLL_SEC)


def _reset_state_for_tests():
    global crash_restarts, last_crash_restart_at, last_daily_restart_date, last_daily_cold_backup_date, _gui_state_loaded
    crash_restarts = 0
    last_crash_restart_at = 0.0
    last_daily_restart_date = None
    last_daily_cold_backup_date = None
    _gui_state_loaded = False


def _load_gui_state():
    global last_daily_restart_date, last_daily_cold_backup_date, _gui_state_loaded
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        last_daily_restart_date = raw.get("last_daily_restart_date")
        last_daily_cold_backup_date = raw.get("last_daily_cold_backup_date")
    except (OSError, ValueError, AttributeError):
        pass
    _gui_state_loaded = True


def _save_gui_state():
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        tmp_path = STATE_PATH + ".tmp_" + os.urandom(4).hex()
        with open(tmp_path, "w", encoding="utf-8", newline="") as f:
            json.dump({
                "last_daily_restart_date": last_daily_restart_date,
                "last_daily_cold_backup_date": last_daily_cold_backup_date,
            }, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, STATE_PATH)
    except OSError:
        pass


def _backoff_sec(failures):
    schedule = config.WATCHDOG_BACKOFF_SCHEDULE
    return schedule[min(failures - 1, len(schedule) - 1)] if failures > 0 else 0


def _watchdog_tick(now=None):
    """Una iteracion del ciclo. `now` inyectable para tests."""
    if not _gui_state_loaded:
        _load_gui_state()
    now = time.time() if now is None else now
    cfg = schedule_config_service.load()
    if not (cfg["auto_restart_on_crash"] or cfg["daily_restart_time"] or cfg["daily_backup_time"]):
        return
    if cfg["auto_restart_on_crash"]:
        _tick_crash_restart(now)
    if cfg["daily_restart_time"]:
        _tick_daily_restart(cfg, now)
    if cfg["daily_backup_time"]:
        _tick_daily_cold_backup(cfg, now)


def _tick_crash_restart(now):
    global crash_restarts, last_crash_restart_at
    if manager.is_running:
        if manager.start_time and (now - manager.start_time) >= config.WATCHDOG_STABLE_UPTIME_SEC:
            crash_restarts = 0
        return
    if manager.stop_requested:
        return
    # En backoff: esperar antes del siguiente intento.
    if crash_restarts > 0 and (now - last_crash_restart_at) < _backoff_sec(crash_restarts):
        return
    status, _detalle = lifecycle_service.start_wrapper()
    if status == "already_running":
        return
    crash_restarts += 1
    last_crash_restart_at = now
    if status == "starting":
        manager.add_log(
            L(f"[Watchdog] El wrapper murió inesperadamente; re-arranque #{crash_restarts}.",
              f"[Watchdog] The wrapper died unexpectedly; restart #{crash_restarts}."),
            "error",
        )
    else:
        manager.add_log(
            L(f"[Watchdog] No se pudo re-arrancar el wrapper ({status}); se reintentará con backoff.",
              f"[Watchdog] Could not restart the wrapper ({status}); will retry with backoff."),
            "error",
        )


def _tick_daily_restart(cfg, now):
    global last_daily_restart_date
    if not manager.is_running:
        return
    localtime = time.localtime(now)
    if not _crossed_daily_time(localtime, cfg["daily_restart_time"], last_daily_restart_date):
        return
    last_daily_restart_date = time.strftime("%Y-%m-%d", localtime)
    _save_gui_state()
    manager.add_log(
        L(f"[Watchdog] Reinicio diario programado ({cfg['daily_restart_time']}).",
          f"[Watchdog] Daily scheduled restart ({cfg['daily_restart_time']})."),
        "system",
    )
    # Directo (sin hilo): durante el reinicio no hay nada mas que vigilar, y
    # el ciclo queda determinista.
    lifecycle_service.restart_wrapper()


def _tick_daily_cold_backup(cfg, now):
    global last_daily_cold_backup_date
    if manager.is_running:
        # Con el servidor vivo, el backup diario lo hace el wrapper (en caliente).
        return
    localtime = time.localtime(now)
    if not _crossed_daily_time(localtime, cfg["daily_backup_time"], last_daily_cold_backup_date):
        return
    last_daily_cold_backup_date = time.strftime("%Y-%m-%d", localtime)
    _save_gui_state()
    manager.add_log(
        L(f"[Watchdog] Backup diario programado ({cfg['daily_backup_time']}) con el servidor detenido.",
          f"[Watchdog] Daily scheduled backup ({cfg['daily_backup_time']}) with the server stopped."),
        "backup",
    )
    lifecycle_service.cold_backup("scheduled")
