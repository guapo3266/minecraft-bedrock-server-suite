"""Config de programacion (backups programables + watchdog) en data/schedule_config.json.

El wrapper lee este archivo directamente (releo por mtime en cada tick de su
scheduler); la GUI lo escribe atomico. Sin archivo o corrupto -> defaults
(= comportamiento historico: intervalo 30 min, solo con jugadores, sin
watchdog). Es dato de instalacion: NO se sincroniza a los destinos.
"""

import json
import os
import re
import threading

from gui_backend import config

_lock = threading.Lock()

SCHEDULE_PATH = os.path.join(config.BASE_DIR, "data", "schedule_config.json")

MIN_INTERVAL_MIN = 5
MAX_INTERVAL_MIN = 24 * 60

DEFAULTS = {
    "backup_interval_min": 30,
    "backup_only_with_players": True,
    "daily_backup_time": None,   # "HH:MM" o None
    "auto_restart_on_crash": False,
    "daily_restart_time": None,  # "HH:MM" o None
}

_RE_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def is_valid_time(value):
    return value is None or (isinstance(value, str) and _RE_HHMM.match(value))


def validate(cfg):
    """Devuelve (cfg_normalizado, detalle). detalle != "" si hay error."""
    if not isinstance(cfg, dict):
        return None, "cuerpo debe ser un objeto"
    out = dict(DEFAULTS)
    out.update({k: v for k, v in cfg.items() if k in DEFAULTS})

    try:
        interval = int(out["backup_interval_min"])
    except (TypeError, ValueError):
        return None, "backup_interval_min debe ser entero"
    if not (MIN_INTERVAL_MIN <= interval <= MAX_INTERVAL_MIN):
        return None, f"backup_interval_min debe estar entre {MIN_INTERVAL_MIN} y {MAX_INTERVAL_MIN}"
    out["backup_interval_min"] = interval

    if not isinstance(out["backup_only_with_players"], bool):
        return None, "backup_only_with_players debe ser true o false"
    if not isinstance(out["auto_restart_on_crash"], bool):
        return None, "auto_restart_on_crash debe ser true o false"

    for key in ("daily_backup_time", "daily_restart_time"):
        if not is_valid_time(out[key]):
            return None, f"{key} debe ser \"HH:MM\" o null"
    return out, ""


def load():
    """Lee el archivo; ante cualquier problema devuelve defaults sin lanzar."""
    try:
        with open(SCHEDULE_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return dict(DEFAULTS)
    cfg, _detalle = validate(raw)
    return cfg if cfg is not None else dict(DEFAULTS)


def save(cfg):
    """Valida y escribe atomico (tmp + os.replace). Devuelve (ok, cfg, detalle)."""
    cfg, detalle = validate(cfg)
    if cfg is None:
        return False, None, detalle
    with _lock:
        os.makedirs(os.path.dirname(SCHEDULE_PATH), exist_ok=True)
        nonce = os.urandom(4).hex()
        tmp_path = SCHEDULE_PATH + f".tmp_{nonce}"
        try:
            with open(tmp_path, "w", encoding="utf-8", newline="") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, SCHEDULE_PATH)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
    return True, cfg, ""
