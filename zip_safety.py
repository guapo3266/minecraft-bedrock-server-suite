"""Guards compartidos anti zip-slip y clasificacion de packs (fuente unica).

Centraliza _is_safe_zip_entry y _pack_dest que estaban duplicados en
auto_backup.py, restore_backup.py y gui_backend/security.py. La logica vive
aqui; los consumidores actuales son restore_core.py (pipeline de restore),
gui_backend/security.py (re-export que usa bds_update) y
server_gui_server.py (re-export para tests).

Tambien centraliza la recuperacion de restauraciones interrumpidas
(_quarantine_and_restore, _extract_pack_entry) y la lista canonica de
marcadores de backup no restaurable (CORRUPT_MARKERS): antes vivian
duplicadas entre auto_backup.py y restore_backup.py y divergieron (los
backups _CRASH se ocultaban en la GUI pero no en la CLI).

Anti-drift: cambiar la logica aqui afecta automaticamente a los
consumidores sin drift silencioso. Tests en test_pbt_properties.py
verifican consenso e identidad de los alias.
"""

import os
import shutil

from console_lang import L

# Carpetas de nivel servidor incluidas en backups junto al mundo.
SERVER_PACK_DIRS = ("resource_packs", "behavior_packs")
PACK_ZIP_PREFIX = "server_"

# Marcadores canonicos de backup NO apto para restaurar ni para las capas
# recientes/diarias de rotacion (evidencia retenida 7 dias). Unico punto de
# verdad para auto_backup.rotate_backups, la lista de la GUI y la CLI: si la
# GUI oculta un marcador, la CLI tambien.
CORRUPT_MARKERS = ("_CORRUPTO", "_EXCEDIDO", "_CRASH", "_crash")
_CORRUPT_MARKERS = CORRUPT_MARKERS

# Tope de expansion al RESTAURAR (defensa ante zip-bomb o backup corrupto):
# el limite de creacion (auto_backup.MAX_BACKUP_BYTES) es 10 GB SIN comprimir,
# asi que 20 GB da margen de sobra para mundos legitimos.
MAX_RESTORE_UNCOMPRESSED_BYTES = 20 * 1024**3


def _exceeds_expansion_limit(infos, max_bytes=MAX_RESTORE_UNCOMPRESSED_BYTES):
    """True si la suma declarada de tamaños sin comprimir supera `max_bytes`."""
    total = 0
    for info in infos:
        try:
            total += int(info.file_size)
        except (TypeError, ValueError, AttributeError):
            continue
        if total > max_bytes:
            return True
    return False


def is_safe_backup_name(filename) -> bool:
    """True si `filename` es un nombre de backup valido para operar sobre el.

    Basename puro terminado en .zip, sin caracteres de control, sin '..' ni
    punto/espacio final (alias de normalizacion NTFS). Hardening 2026-09-25:
    basename+isfile ya impedia escapar de BACKUP_DIR, pero nombres alias
    ('foo.zip.', '..') llegaban al filesystem.
    """
    if not isinstance(filename, str) or not filename:
        return False
    if any(ord(c) < 0x20 for c in filename):
        return False
    if os.path.basename(filename) != filename or filename != filename.rstrip(" ."):
        return False
    if filename in (".", ".."):
        return False
    return filename.lower().endswith(".zip")


# Nombres de dispositivo de Windows: extraerlos escribe hacia el device
# (NUL, CON, COM1...) con perdida silenciosa de datos. Se rechazan en
# cualquier segmento, con o sin extension ('db/NUL', 'aux.txt').
_WIN_DEVICE_NAMES = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + ["COM%d" % i for i in range(1, 10)]
    + ["LPT%d" % i for i in range(1, 10)]
)


def _is_safe_zip_entry(filename: str) -> bool:
    """True si la entrada del zip es segura para extraer (anti zip-slip).

    Rechaza rutas absolutas, cualquier segmento '..' (traversal), ':'
    en cualquier segmento (unidades 'C:' y ADS de NTFS como
    'db/foo.ldb:stream'), nombres con bytes nulos (\\x00), nombres de
    dispositivo de Windows (NUL, CON, COM1...) y segmentos con punto o
    espacio final (alias de normalizacion NTFS). La cadena vacia se
    acepta por compatibilidad historica (join degenerado sin escape).
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
    for s in segs:
        if not s:
            continue  # segmento vacio: join degenerado, sin escape (compat "")
        if ":" in s:
            return False
        if s != s.rstrip(" ."):
            return False
        if s.split(".")[0].upper() in _WIN_DEVICE_NAMES:
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
    if not rel_path or not _is_safe_zip_entry(rel_path):
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
       el contenido de bak_path sobre active_path y CONSERVA bak_path: la
       copia sobre una carpeta existente puede dejar archivos adicionales.
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
            # Solo borrar failed_path si el resguardo volvio a su sitio:
            # contiene el mundo activo original y borrarlo en fallo es
            # perdida de datos.
            if restored:
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
            copy_errors = 0
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
                        copy_errors += 1
            # Una copia sin errores no prueba equivalencia del arbol: quedan
            # archivos del intento fallido que no existian en el resguardo.
            # Conservar SIEMPRE el .bak en este fallback permite recuperacion
            # exacta manual cuando Windows libere la carpeta.
            if copy_errors == 0:
                print(L(f"[AVISO] Recuperacion por copia; se conserva {bak_path} para verificar y recuperar el arbol completo.",
                        f"[ADVISORY] Recovery by copy; keeping {bak_path} to verify and recover the complete tree."))
            else:
                print(L(f"[CRITICO] Recuperacion fallback parcial: {copy_errors} archivos fallaron, se conserva {bak_path}",
                        f"[CRITICAL] Partial fallback recovery: {copy_errors} files failed, keeping {bak_path}"))
        except Exception as e_fallback:
            print(L(f"[CRITICO] Fallo en recuperacion fallback de resguardo: {e_fallback}",
                    f"[CRITICAL] Fallback backup recovery failed: {e_fallback}"))
