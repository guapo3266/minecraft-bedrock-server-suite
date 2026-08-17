"""Configuracion y helpers del scheduler de backups del wrapper."""

import json
import os
import re
import time


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCHEDULE_CONFIG_PATH = os.path.join(BASE_DIR, "data", "schedule_config.json")
SCHEDULE_STATE_PATH = os.path.join(BASE_DIR, "data", "schedule_state_wrapper.json")

# Defaults = comportamiento historico. Deben coincidir con DEFAULTS de
# gui_backend/services/schedule_config.py (test anti-drift en tests/).
SCHEDULE_DEFAULTS = {
    "backup_interval_min": 30,
    "backup_only_with_players": True,
    "daily_backup_time": None,
    "auto_restart_on_crash": False,
    "daily_restart_time": None,
}

_schedule_cfg_cache = {"mtime": None, "cfg": dict(SCHEDULE_DEFAULTS)}

# Fecha (YYYY-MM-DD) del ultimo backup diario disparado; persistida para que
# un reinicio del wrapper no lo re-dispare.
last_daily_backup_date = None


def _coerce_schedule_value(key, value):
    """Coercion de tipos por clave para ediciones manuales del JSON."""
    if key == "backup_interval_min":
        if isinstance(value, bool):
            return SCHEDULE_DEFAULTS[key]
        try:
            iv = int(value)
        except (TypeError, ValueError):
            return SCHEDULE_DEFAULTS[key]
        return iv if iv >= 1 else SCHEDULE_DEFAULTS[key]
    if key in ("backup_only_with_players", "auto_restart_on_crash"):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            v = value.strip().lower()
            if v in ("true", "1", "yes", "on"):
                return True
            if v in ("false", "0", "no", "off"):
                return False
        return SCHEDULE_DEFAULTS[key]
    if key in ("daily_backup_time", "daily_restart_time"):
        if isinstance(value, str) and re.match(r"^([01]\d|2[0-3]):[0-5]\d$", value.strip()):
            return value.strip()
        return None
    return SCHEDULE_DEFAULTS[key]


def _load_schedule_config():
    """Lee schedule_config.json y recarga solo cuando cambia el mtime."""
    try:
        mtime = os.stat(SCHEDULE_CONFIG_PATH).st_mtime
    except OSError:
        _schedule_cfg_cache["mtime"] = None
        _schedule_cfg_cache["cfg"] = dict(SCHEDULE_DEFAULTS)
        return dict(SCHEDULE_DEFAULTS)
    if _schedule_cfg_cache["mtime"] == mtime:
        return dict(_schedule_cfg_cache["cfg"])
    cfg = dict(SCHEDULE_DEFAULTS)
    try:
        with open(SCHEDULE_CONFIG_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            for key in SCHEDULE_DEFAULTS:
                if key in raw:
                    cfg[key] = _coerce_schedule_value(key, raw[key])
    except (OSError, ValueError):
        cfg = dict(SCHEDULE_DEFAULTS)
    _schedule_cfg_cache["mtime"] = mtime
    _schedule_cfg_cache["cfg"] = cfg
    return dict(cfg)


def _load_last_daily_backup_date():
    try:
        with open(SCHEDULE_STATE_PATH, encoding="utf-8") as f:
            value = json.load(f).get("last_daily_backup_date")
        return value if isinstance(value, str) else None
    except (OSError, ValueError, AttributeError):
        return None


def _save_last_daily_backup_date(date_str):
    try:
        os.makedirs(os.path.dirname(SCHEDULE_STATE_PATH), exist_ok=True)
        tmp_path = SCHEDULE_STATE_PATH + ".tmp_" + os.urandom(4).hex()
        with open(tmp_path, "w", encoding="utf-8", newline="") as f:
            json.dump({"last_daily_backup_date": date_str}, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, SCHEDULE_STATE_PATH)
    except OSError:
        pass


def _should_start_backup(interval_due, retry_due, daily_due, players_count, cfg):
    """Decision del ciclo periodico en IDLE: 'start', 'skip' o 'no'."""
    if daily_due:
        return "start"
    if not (interval_due or retry_due):
        return "no"
    if players_count > 0 or not cfg["backup_only_with_players"]:
        return "start"
    return "skip"


def _crossed_daily_time(localtime, hhmm, fired_date_str):
    """True si la hora local ya alcanzo hhmm y hoy no se disparo."""
    if not hhmm:
        return False
    today_str = time.strftime("%Y-%m-%d", localtime)
    if fired_date_str == today_str:
        return False
    try:
        fire_h, fire_m = (int(x) for x in hhmm.split(":"))
    except ValueError:
        return False
    return (localtime.tm_hour, localtime.tm_min) >= (fire_h, fire_m)
