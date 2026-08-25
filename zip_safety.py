"""Guards compartidos anti zip-slip y clasificacion de packs (fuente unica).

Centraliza _is_safe_zip_entry y _pack_dest que estaban duplicados en
auto_backup.py, restore_backup.py y gui_backend/security.py. Los tres
modulos re-exportan estas funciones para compatibilidad (tests y
monkeypatches siguen importando desde ellos) pero la logica vive aqui.

Anti-drift: cambiar la logica aqui afecta automaticamente a los tres
consumidores sin drift silencioso. Tests en test_pbt_properties.py
verifican consenso y que los tres alias apuntan a este modulo.
"""

import os

# Carpetas de nivel servidor incluidas en backups junto al mundo.
SERVER_PACK_DIRS = ("resource_packs", "behavior_packs")
PACK_ZIP_PREFIX = "server_"
# Alias historicos para compatibilidad con restore_backup (nombres con _).
_SERVER_PACK_DIRS = SERVER_PACK_DIRS
_PACK_ZIP_PREFIX = PACK_ZIP_PREFIX


def _is_safe_zip_entry(filename: str) -> bool:
    """True si la entrada del zip es segura para extraer (anti zip-slip).

    Rechaza rutas absolutas, cualquier segmento '..' (traversal), prefijos
    de unidad/ADS tipo 'C:' y nombres con bytes nulos (\\x00) que podrian
    confundir APIs de extraccion o truncar paths en C.
    """
    if not isinstance(filename, str):
        return False
    if "\x00" in filename:
        return False
    norm = filename.replace("\\", "/")
    if norm.startswith("/") or os.path.isabs(norm):
        return False
    segs = norm.split("/")
    if any(s == ".." for s in segs):
        return False
    if segs and ":" in segs[0]:
        return False
    return True


def _pack_dest(entry_filename):
    """Clasifica una entrada del ZIP.

    Si pertenece a un pack de nivel servidor devuelve (kind, folder, rel_path),
    con kind en SERVER_PACK_DIRS, folder = carpeta del pack y rel_path relativo
    a esa carpeta. Devuelve None para entradas del mundo (o entradas de pack
    sin archivo, como directorios vacios).
    """
    norm = entry_filename.replace("\\", "/")
    for kind in SERVER_PACK_DIRS:
        prefix = PACK_ZIP_PREFIX + kind + "/"
        if norm.startswith(prefix):
            rest = norm[len(prefix):]
            if rest.endswith("/") or not rest:
                return None  # entrada de directorio: no se restaura
            parts = rest.split("/")
            if not parts[0]:
                return None
            if len(parts) >= 2:
                return kind, parts[0], "/".join(parts[1:])
            # archivo suelto en la raiz del pack dir (p.ej.
            # server_resource_packs/foo.txt): se restaura a BASE_DIR/<kind>,
            # no al mundo.
            return kind, "", parts[0]
    return None
