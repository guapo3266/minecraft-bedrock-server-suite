"""Lectura tolerante de `server.properties`.

BDS escribe `clave=valor`, pero un archivo editado a mano puede traer
`clave = valor` o espacios alrededor. Antes, cada parser usaba
`line.startswith("clave=")`, de modo que una edición con espacios se ignoraba
en silencio (p. ej. `backup-inicio = false` seguia haciendo el backup inicial).
"""


def read_value(path, key, default=None):
    """Valor de `key` en un .properties, tolerante a espacios y comentarios.

    Compara la clave sin distinguir mayusculas; devuelve `default` si el
    archivo no existe, no se puede leer o la clave no esta.

    Se lee en BYTES y se decodifica linea por linea: un editor de Windows en
    ANSI/cp1252 puede dejar un byte no-UTF-8 (un acento, una `ñ`) en cualquier
    linea. Con decode estricto del archivo entero, ese byte lanzaba
    UnicodeDecodeError desde el propio import de auto_backup (WORLD_NAME) y el
    wrapper no arrancaba con un traceback. Ahora la linea corrupta se salta y
    las demas (casi siempre ASCII) siguen parseandose.
    """
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return default
    for raw_line in raw.splitlines():
        try:
            line = raw_line.decode("utf-8").strip()
        except UnicodeDecodeError:
            continue
        if not line or line.startswith("#") or line.startswith(";") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip().lower() == key.lower():
            return v.strip()
    return default
