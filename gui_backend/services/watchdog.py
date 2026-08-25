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
# Rate-limit del log de errores internos del tick: un fallo persistente (p. ej.
# disco ilegible al leer la config) no debe inundar el historial de la GUI.
_last_error_log_at = 0.0
_ERROR_LOG_MIN_INTERVAL_SEC = 60.0


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
    global _last_error_log_at
    crash_restarts = 0
    last_crash_restart_at = 0.0
    last_daily_restart_date = None
    last_daily_cold_backup_date = None
    _gui_state_loaded = False
    _last_error_log_at = 0.0


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


def _log_watchdog_error(rama, exc, now):
    """Log de un fallo interno del tick, rate-limitado (1 mensaje/60s).

    Antes el loop se tragaba cualquier excepcion en silencio: si una rama
    fallaba de forma persistente nadie lo veia jamas en la GUI. El reloj es
    el `now` inyectado del tick para que los tests sean deterministas.
    """
    global _last_error_log_at
    if now - _last_error_log_at < _ERROR_LOG_MIN_INTERVAL_SEC:
        return
    _last_error_log_at = now
    try:
        manager.add_log(
            L(f"[Watchdog] Error interno en la rama {rama}: {exc}",
              f"[Watchdog] Internal error in branch {rama}: {exc}"),
            "error",
        )
    except Exception:
        pass  # ni el log de errores puede tumbar al watchdog


def _watchdog_tick(now=None):
    """Una iteracion del ciclo. `now` inyectable para tests.

    Cada rama corre aislada: un excepcion en auto-restart no debe saltarse el
    reinicio diario ni el backup en frio programado. Los fallos se loguean con
    rate-limit; watchdog_loop mantiene su try/except como ultima red.
    """
    if not _gui_state_loaded:
        _load_gui_state()
    now = time.time() if now is None else now
    cfg = schedule_config_service.load()
    if not (cfg["auto_restart_on_crash"] or cfg["daily_restart_time"] or cfg["daily_backup_time"]):
        return
    if cfg["auto_restart_on_crash"]:
        try:
            _tick_crash_restart(now)
        except Exception as exc:
            _log_watchdog_error("auto_restart_on_crash", exc, now)
    if cfg["daily_restart_time"]:
        try:
            _tick_daily_restart(cfg, now)
        except Exception as exc:
            _log_watchdog_error("daily_restart", exc, now)
    if cfg["daily_backup_time"]:
        try:
            _tick_daily_cold_backup(cfg, now)
        except Exception as exc:
            _log_watchdog_error("daily_cold_backup", exc, now)


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
    try:
        status, _detalle = lifecycle_service.start_wrapper()
    except Exception as exc:
        # Fallo inesperado en la propia ruta de arranque (p. ej. sonda de
        # instancias lanzando): cuenta como intento fallido para que el
        # backoff evite martillear start_wrapper en cada poll (5s).
        crash_restarts += 1
        last_crash_restart_at = now
        try:
            manager.add_log(
                L(f"[Watchdog] Re-arranque #{crash_restarts} falló con excepción ({exc}); se reintentará con backoff.",
                  f"[Watchdog] Restart #{crash_restarts} failed with exception ({exc}); will retry with backoff."),
                "error",
            )
        except Exception:
            pass
        return
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
