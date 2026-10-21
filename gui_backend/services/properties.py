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
    """{clave: valor} de las lineas activas (no comentadas) de server.properties.

    Delega en server_properties.read_value (fuente unica de tolerancia del
    suite: `clave = valor`, comentarios `#`/`;` y bytes no UTF-8): el parser
    propio de aqui era UTF-8 estricto (500 ante un byte cp1252) e ignoraba
    solo `#` (2026-09-25).
    """
    values = {}
    if os.path.exists(config.PROPS_PATH):
        from server_properties import read_value
        for key in PROPS_FIELDS:
            val = read_value(config.PROPS_PATH, key)
            if val is not None:
                values[key] = val
    return values


def _validate_props(values):
    """Valida {clave: valor} contra PROPS_FIELDS. Devuelve (ok, detalle)."""
    for key, raw in values.items():
        spec = PROPS_FIELDS.get(key)
        if spec is None:
            return False, f"campo desconocido: {key}"
        # Ningun valor puede contener caracteres de control: un \n dentro de
        # server-name inyectaba lineas arbitrarias en server.properties
        # (p. ej. level-name/online-mode escritos sin pasar por la lista de
        # campos editables). El archivo se escribe linea a linea: un solo
        # salto de linea rompe el formato.
        if any(ord(c) < 32 or ord(c) == 127 for c in raw):
            return False, f"{key}: caracteres de control no permitidos"
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
            # Forma canonica: BDS parsea mal " 10", "+10" u "010"; escribir
            # solo lo que int() acepta sin sorpresas.
            if raw != str(n):
                return False, f"{key}: entero sin espacios ni signos: {n}"
            if not (spec["min"] <= n <= spec["max"]):
                return False, f"{key}: rango {spec['min']}-{spec['max']}"
        elif spec["type"] == "string":
            if len(raw) > spec["max"]:
                return False, f"{key}: maximo {spec['max']} caracteres"
    return True, ""


_UTF8_BOM = b"\xef\xbb\xbf"


def _write_props_values(values):
    """Actualiza las claves dadas preservando el resto del archivo de forma atómica bajo lock.

    Las lineas se reconocen con la MISMA regla que el lector
    (server_properties.parse_line: sin distinguir mayusculas, espacios
    alrededor del '=', comentarios #/;). Se reemplazan TODAS las lineas activas
    de cada clave por 'clave=valor', para que la GUI y BDS no lean valores
    distintos; si no hay ninguna (o solo esta comentada), se anade al final.
    El resto se copia byte a byte, con su salto de linea. Antes el archivo se
    leia en UTF-8 estricto (un acento guardado en ANSI daba 500 al guardar) y
    solo se reconocia 'clave=' / 'clave =': con 'Server-Name = X' se anadia
    una linea duplicada que el lector ignoraba (2026-10-20). Si
    server.properties aun no existe (instalacion nueva antes del primer
    boot), se crea con las claves dadas. Devuelve las claves escritas.
    """
    from server_properties import parse_line

    with _props_lock:
        try:
            with open(config.PROPS_PATH, "rb") as f:
                raw = f.read()
        except FileNotFoundError:
            raw = b""
        newline = b"\r\n" if b"\r\n" in raw else b"\n"
        pending = {key.lower(): (key, val) for key, val in values.items()}
        found = set()
        lines = []
        for raw_line in raw.splitlines(keepends=True):
            parsed = parse_line(raw_line)
            if parsed is None or parsed[0] not in pending:
                lines.append(raw_line)
                continue
            key, val = pending[parsed[0]]
            body = raw_line.rstrip(b"\r\n")
            bom = _UTF8_BOM if body.startswith(_UTF8_BOM) else b""
            lines.append(bom + f"{key}={val}".encode("utf-8") + raw_line[len(body):])
            found.add(parsed[0])
        missing = [k for k in pending if k not in found]
        if missing and lines and not lines[-1].endswith((b"\n", b"\r")):
            lines[-1] += newline
        for k in missing:
            key, val = pending[k]
            lines.append(f"{key}={val}".encode("utf-8") + newline)
        written = list(values)

        nonce = os.urandom(4).hex()
        tmp_path = config.PROPS_PATH + f".tmp_{nonce}"
        try:
            with open(tmp_path, "wb") as f:
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
