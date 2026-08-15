import os
import threading

from gui_backend import config

_props_lock = threading.Lock()


PROPS_FIELDS = {
    "server-name": {"type": "string", "max": 128},
    "gamemode": {"type": "enum", "values": ["survival", "creative", "adventure"]},
    "difficulty": {"type": "enum", "values": ["peaceful", "easy", "normal", "hard"]},
    "allow-cheats": {"type": "bool"},
    "max-players": {"type": "int", "min": 1, "max": 999},
    "online-mode": {"type": "bool"},
    "allow-list": {"type": "bool"},
    "server-port": {"type": "int", "min": 1, "max": 65535},
    "view-distance": {"type": "int", "min": 5, "max": 96},
    "tick-distance": {"type": "int", "min": 4, "max": 12},
    "player-idle-timeout": {"type": "int", "min": 0, "max": 10080},
    "default-player-permission-level": {"type": "enum", "values": ["visitor", "member", "operator"]},
}


def _read_props_values():
    """{clave: valor} de las lineas activas (no comentadas) de server.properties."""
    values = {}
    if os.path.exists(config.PROPS_PATH):
        with open(config.PROPS_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                if key in PROPS_FIELDS:
                    values[key] = val.strip()
    return values


def _validate_props(values):
    """Valida {clave: valor} contra PROPS_FIELDS. Devuelve (ok, detalle)."""
    for key, raw in values.items():
        spec = PROPS_FIELDS.get(key)
        if spec is None:
            return False, f"campo desconocido: {key}"
        if spec["type"] == "enum":
            if raw not in spec["values"]:
                return False, f"{key}: valores validos: {', '.join(spec['values'])}"
        elif spec["type"] == "bool":
            if raw not in ("true", "false"):
                return False, f"{key}: debe ser true o false"
        elif spec["type"] == "int":
            try:
                n = int(raw)
            except (TypeError, ValueError):
                return False, f"{key}: debe ser un entero"
            if not (spec["min"] <= n <= spec["max"]):
                return False, f"{key}: rango {spec['min']}-{spec['max']}"
        elif spec["type"] == "string":
            if len(raw) > spec["max"]:
                return False, f"{key}: maximo {spec['max']} caracteres"
    return True, ""


def _write_props_values(values):
    """Actualiza las claves dadas preservando el resto del archivo de forma atómica bajo lock.

    Reemplaza la primera linea activa 'clave=...'; si la clave no existe (o
    solo esta comentada), la anade al final. Si server.properties aun no
    existe (instalacion nueva antes del primer boot), se crea con las claves
    dadas. Devuelve las claves escritas.
    """
    with _props_lock:
        if os.path.exists(config.PROPS_PATH):
            with open(config.PROPS_PATH, encoding="utf-8") as f:
                lines = f.readlines()
        else:
            lines = []
        written = []
        for key, val in values.items():
            replaced = False
            for i, line in enumerate(lines):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if stripped.startswith(key + "=") or stripped.startswith(key + " ="):
                    lines[i] = f"{key}={val}\n"
                    replaced = True
                    break
            if not replaced:
                lines.append(f"{key}={val}\n")
            written.append(key)

        nonce = os.urandom(4).hex()
        tmp_path = config.PROPS_PATH + f".tmp_{nonce}"
        try:
            with open(tmp_path, "w", encoding="utf-8", newline="") as f:
                f.writelines(lines)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, config.PROPS_PATH)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
        return written
