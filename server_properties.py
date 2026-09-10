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
    """
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith(";") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                if k.strip().lower() == key.lower():
                    return v.strip()
    except OSError:
        pass
    return default
