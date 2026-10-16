"""Lectura tolerante de `server.properties`.

BDS escribe `clave=valor`, pero un archivo editado a mano puede traer
`clave = valor` o espacios alrededor. Antes, cada parser usaba
`line.startswith("clave=")`, de modo que una edición con espacios se ignoraba
en silencio (p. ej. `backup-inicio = false` seguia haciendo el backup inicial).
"""

import os

from console_lang import L
import zip_safety


def _is_world_name(name):
    return (
        isinstance(name, str) and bool(name) and name != "."
        and "/" not in name and "\\" not in name
        and not any(c in name for c in '<>"|?*')
        and not any(ord(c) < 32 for c in name)
        and zip_safety._is_safe_zip_entry(name)
    )


def validate_world_dir(base_dir, world_dir):
    """Exige un hijo directo de worlds/, sin redireccion por enlaces/junctions."""
    root = os.path.abspath(os.path.join(base_dir, "worlds"))
    target = os.path.abspath(world_dir)
    name = os.path.basename(target)
    expected_root = os.path.join(os.path.realpath(base_dir), "worlds")
    if (
        not _is_world_name(name)
        or os.path.normcase(os.path.dirname(target)) != os.path.normcase(root)
        or os.path.normcase(os.path.realpath(root)) != os.path.normcase(expected_root)
        or os.path.normcase(os.path.realpath(target)) != os.path.normcase(os.path.join(expected_root, name))
    ):
        raise ValueError(L(
            "Ruta de mundo insegura: debe ser una carpeta directa dentro de worlds/, sin enlaces ni junctions.",
            "Unsafe world path: it must be a direct folder inside worlds/, without links or junctions.",
        ))
    return target


def resolve_world_dir(base_dir):
    """Resuelve level-name con validacion comun a backup y restauracion GUI/CLI."""
    name = read_value(os.path.join(base_dir, "server.properties"), "level-name") or "Bedrock level"
    if not _is_world_name(name):
        raise ValueError(L(
            "level-name invalido: usa un nombre de carpeta, sin rutas ni alias de Windows.",
            "Invalid level-name: use a folder name, without paths or Windows aliases.",
        ))
    return validate_world_dir(base_dir, os.path.join(base_dir, "worlds", name))


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
