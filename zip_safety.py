"""Guards compartidos anti zip-slip y clasificacion de packs (fuente unica).

Centraliza _is_safe_zip_entry y _pack_dest que estaban duplicados en
auto_backup.py, restore_backup.py y gui_backend/security.py. Los tres
modulos re-exportan estas funciones para compatibilidad (tests y
monkeypatches siguen importando desde ellos) pero la logica vive aqui.

Tambien centraliza la recuperacion de restauraciones interrumpidas
(_quarantine_and_restore, _extract_pack_entry) y la lista canonica de
marcadores de backup no restaurable (CORRUPT_MARKERS): antes vivian
duplicadas entre auto_backup.py y restore_backup.py y divergieron (los
backups _CRASH se ocultaban en la GUI pero no en la CLI).

Anti-drift: cambiar la logica aqui afecta automaticamente a los tres
consumidores sin drift silencioso. Tests en test_pbt_properties.py
verifican consenso y que los tres alias apuntan a este modulo.
"""

import os
import shutil

from console_lang import L

# Carpetas de nivel servidor incluidas en backups junto al mundo.
SERVER_PACK_DIRS = ("resource_packs", "behavior_packs")
PACK_ZIP_PREFIX = "server_"
# Alias historicos para compatibilidad con restore_backup (nombres con _).
_SERVER_PACK_DIRS = SERVER_PACK_DIRS
_PACK_ZIP_PREFIX = PACK_ZIP_PREFIX

# Marcadores canonicos de backup NO apto para restaurar ni para las capas
# recientes/diarias de rotacion (evidencia retenida 7 dias). Unico punto de
# verdad para auto_backup.rotate_backups, la lista de la GUI y la CLI: si la
# GUI oculta un marcador, la CLI tambien.
CORRUPT_MARKERS = ("_CORRUPTO", "_EXCEDIDO", "_CRASH", "_crash")
_CORRUPT_MARKERS = CORRUPT_MARKERS


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


def _extract_pack_entry(zipf, entry, base_dir, rel_path):
    """Extrae una entrada de pack a base_dir con doble chequeo anti traversal.

    rel_path proviene de una entrada ya validada con _is_safe_zip_entry y de
    un prefijo fijo, pero se revalida igual: el destino nunca escapa de
    base_dir.
    """
    segs = rel_path.split("/")
    if any(s == ".." for s in segs) or os.path.isabs(rel_path) or ":" in segs[0]:
        raise ValueError(L(f"Entrada de pack insegura: {entry.filename}", f"Unsafe pack entry: {entry.filename}"))
    dest = os.path.join(base_dir, *segs)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with zipf.open(entry, "r") as src, open(dest, "wb") as out:
        shutil.copyfileobj(src, out)


def _quarantine_and_restore(active_path, bak_path, is_dir=True):
    """Garantiza la recuperación del resguardo .bak aislando la ruta activa.

    1. Intenta renombrar active_path a .failed_<nonce> para liberar la ruta y
       hacer os.rename(bak_path, active_path).
    2. Si active_path no existe, hace os.rename(bak_path, active_path).
    3. Si active_path no pudo ser renombrado ni eliminado (p. ej. archivos bloqueados
       por Windows Defender o procesos en segundo plano), copia recursivamente
       el contenido de bak_path sobre active_path y limpia bak_path.
    """
    if not os.path.exists(bak_path):
        return

    restored = False
    if os.path.exists(active_path):
        failed_path = active_path + f".failed_{os.urandom(4).hex()}"
        try:
            os.rename(active_path, failed_path)
        except Exception:
            pass
        else:
            try:
                os.rename(bak_path, active_path)
                restored = True
            except Exception as e_rb:
                print(L(f"[CRITICO] No se pudo restaurar el resguardo {bak_path} -> {active_path}: {e_rb}",
                        f"[CRITICAL] Could not restore backup {bak_path} -> {active_path}: {e_rb}"))
            try:
                if is_dir:
                    shutil.rmtree(failed_path, ignore_errors=True)
                else:
                    os.remove(failed_path)
            except Exception:
                pass

    if not restored and not os.path.exists(active_path):
        try:
            os.rename(bak_path, active_path)
            restored = True
        except Exception as e_rb:
            print(L(f"[CRITICO] No se pudo restaurar el resguardo {bak_path} -> {active_path}: {e_rb}",
                    f"[CRITICAL] Could not restore backup {bak_path} -> {active_path}: {e_rb}"))

    if not restored and is_dir and os.path.isdir(bak_path):
        try:
            for root, dirs, files in os.walk(bak_path):
                rel = os.path.relpath(root, bak_path)
                target_dir = os.path.join(active_path, rel)
                os.makedirs(target_dir, exist_ok=True)
                for f in files:
                    src_f = os.path.join(root, f)
                    dst_f = os.path.join(target_dir, f)
                    try:
                        shutil.copy2(src_f, dst_f)
                    except Exception:
                        pass
            shutil.rmtree(bak_path, ignore_errors=True)
            restored = True
        except Exception as e_fallback:
            print(L(f"[CRITICO] Fallo en recuperacion fallback de resguardo: {e_fallback}",
                    f"[CRITICAL] Fallback backup recovery failed: {e_fallback}"))
