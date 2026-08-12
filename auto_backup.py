import os
import datetime
import zipfile
import glob
import multiprocessing
import shutil
import re

from console_lang import L

# Lock por defecto (multiprocessing safe)
_backup_lock = multiprocessing.Lock()

# Configuracion (resuelta dinamicamente)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# H3: nombre de la instalacion (carpeta del servidor). Cada servidor escribe
# sus backups en su propia subcarpeta de Backups_Minecraft; sin esto todos
# compartian una sola carpeta y un restore cruzado pisaba el mundo de otro
# servidor (mismo level-name por defecto).
SERVER_NAME = os.path.basename(os.path.normpath(BASE_DIR))

def get_world_name():
    props_path = os.path.join(BASE_DIR, "server.properties")
    if os.path.exists(props_path):
        try:
            with open(props_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("level-name="):
                        return line.split("=", 1)[1].strip()
        except Exception:
            pass
    return "Bedrock level"

WORLD_NAME = get_world_name()
WORLD_DIR = os.path.join(BASE_DIR, "worlds", WORLD_NAME)
WORLD_PARENT_DIR = os.path.join(BASE_DIR, "worlds")


def _resolve_backup_dir(base_dir):
    """Backups por instalacion: Backups_Minecraft\\auto_backups\\<servidor> (H3)."""
    return os.path.abspath(os.path.join(
        base_dir, "..", "..", "Backups_Minecraft", "auto_backups",
        os.path.basename(os.path.normpath(base_dir)),
    ))


BACKUP_DIR = _resolve_backup_dir(BASE_DIR)

# Politica de retencion
MAX_RECENT_BACKUPS = 15
DAYS_TO_KEEP_DAILY = 7
# H1: ventana de retencion de backups marcados (_CORRUPTO/_EXCEDIDO): se
# conservan como evidencia estos dias y luego se rotan (antes quedaban para
# siempre: fuga de disco indefinida).
CORRUPT_BACKUP_RETENTION_DAYS = 7

# Limite de seguridad: tamaño maximo total del backup comprimido (10 GB default)
MAX_BACKUP_BYTES = 10 * 1024**3  # 10,737,418,240 bytes

# Tamano de chunk para la copia en streaming de archivos de snapshot:
# el pico de RAM es constante (~2x chunk), no proporcional al archivo.
_CHUNK = 8 * 1024 * 1024


class SnapshotDesyncError(RuntimeError):
    """Snapshot desincronizado o incompleto.

    Es la UNICA categoria de fallo del modo snapshot que merece reintento:
    un nuevo `save query` puede producir un snapshot consistente. Los errores
    de almacenamiento (disco lleno, permisos, creacion del ZIP) NO se resuelven
    reintentando y quedan fuera de esta clase.
    """

def _cancelled(cancel_event):
    return cancel_event is not None and cancel_event.is_set()


def _resolve_snapshot_path(rel_path):
    clean_rel_path = rel_path.replace("/", os.sep).replace("\\", os.sep)
    world_name = os.path.basename(os.path.abspath(WORLD_DIR))
    first_part = clean_rel_path.split(os.sep, 1)[0]

    if first_part.lower() == "worlds":
        full_path = os.path.abspath(os.path.normpath(os.path.join(BASE_DIR, clean_rel_path)))
    elif first_part.lower() == world_name.lower():
        full_path = os.path.abspath(os.path.normpath(os.path.join(WORLD_PARENT_DIR, clean_rel_path)))
    else:
        full_path = os.path.abspath(os.path.normpath(os.path.join(WORLD_DIR, clean_rel_path)))

    # Check 1: basic path traversal (.., rutas absolutas) — abspath basta
    world_abs = os.path.abspath(WORLD_DIR)
    try:
        common = os.path.commonpath([world_abs, full_path])
    except ValueError:
        raise ValueError(L(f"Ruta invalida (unidades diferentes?): {rel_path}", f"Invalid path (different drives?): {rel_path}"))
    if common != world_abs:
        raise ValueError(L(f"Ruta fuera del mundo rechazada: {rel_path}", f"Path outside the world rejected: {rel_path}"))

    # Check 2: symlink traversal — realpath resuelve symlinks reales
    if os.path.exists(full_path):
        world_real = os.path.realpath(WORLD_DIR)
        real_full = os.path.realpath(full_path)
        try:
            real_common = os.path.commonpath([world_real, real_full])
        except ValueError:
            raise ValueError(L(f"Symlink escapa del mundo (unidades diferentes): {rel_path}", f"Symlink escapes the world (different drives): {rel_path}"))
        if real_common != world_real:
            raise ValueError(L(f"Symlink fuera del mundo rechazado: {rel_path}", f"Symlink outside the world rejected: {rel_path}"))

    return clean_rel_path, full_path


# Carpetas de nivel servidor que se incluyen en los backups junto al mundo:
# contienen los mods/addons (resource_packs y behavior_packs). Se guardan con
# prefijo propio ("server_resource_packs/...", "server_behavior_packs/...")
# para que la restauracion las devuelva a su ubicacion de servidor y no se
# confundan con packs embebidos dentro de la carpeta del mundo.
SERVER_PACK_DIRS = ("resource_packs", "behavior_packs")
_PACK_ZIP_PREFIX = "server_"


def _write_server_packs(zipf, total_bytes, cancel_event):
    """Agrega los packs de nivel servidor (mods/addons) al ZIP en curso.

    Devuelve total_bytes actualizado. Lanza RuntimeError si se excede
    MAX_BACKUP_BYTES o si el backup fue cancelado.
    """
    for pack_dir in SERVER_PACK_DIRS:
        src_dir = os.path.join(BASE_DIR, pack_dir)
        if not os.path.isdir(src_dir):
            continue
        prefix = _PACK_ZIP_PREFIX + pack_dir + "/"
        for root, dirs, files in os.walk(src_dir):
            for fname in files:
                if _cancelled(cancel_event):
                    raise RuntimeError(L("Backup cancelado durante compresion de packs.", "Backup cancelled during pack compression."))
                full_f = os.path.join(root, fname)
                arc = prefix + os.path.relpath(full_f, src_dir).replace(os.sep, "/")
                zipf.write(full_f, arc)
                total_bytes += os.path.getsize(full_f)
                if total_bytes > MAX_BACKUP_BYTES:
                    raise RuntimeError(
                        L(f"Backup excede el limite de {MAX_BACKUP_BYTES // (1024**3)} GB. Abortando.", f"Backup exceeds the {MAX_BACKUP_BYTES // (1024**3)} GB limit. Aborting.")
                    )
    return total_bytes


def create_backup(trigger_name="auto", file_snapshot=None, cancel_event=None, wait_lock_timeout_sec=0, external_lock=None):
    """
    Crea una copia de seguridad comprimida del mundo.
    - file_snapshot: Lista de tuplas (rel_path, byte_count) devueltas por 'save query'.
      Si se provee, SOLO se leen y copian esos archivos hasta esa cantidad exacta de bytes (Protocolo Bedrock Nativo).
      Si es None, se realiza un backup tradicional escaneando WORLD_DIR.
    - wait_lock_timeout_sec: Segundos a esperar si ya hay un backup en curso antes de abortar.
    - external_lock: Instancia IPC de lock (multiprocessing.Lock) compartida con el proceso principal.
    """
    lock_to_use = external_lock if external_lock is not None else _backup_lock
    acquired_lock = False

    if wait_lock_timeout_sec > 0:
        if not lock_to_use.acquire(timeout=wait_lock_timeout_sec):
            print(L(f"[ERROR] Backup lock wait timed out ({wait_lock_timeout_sec}s); se cancela esta solicitud.", f"[ERROR] Backup lock wait timed out ({wait_lock_timeout_sec}s); cancelling this request."))
            return False
        acquired_lock = True
    else:
        if not lock_to_use.acquire(False):
            print(L("[ERROR] Ya hay un backup ejecutandose; se cancela esta solicitud.", "[ERROR] Ya hay un backup ejecutandose; cancelling this request."))
            return False
        acquired_lock = True

    success = False
    zip_filepath = None
    tmp_filepath = None

    try:
        # Limpiar .tmp huerfanos (solo con el lock adquirido)
        if os.path.exists(BACKUP_DIR):
            for orphan_tmp in glob.glob(os.path.join(BACKUP_DIR, "*.tmp")):
                try:
                    os.remove(orphan_tmp)
                    print(L(f"[*] Limpieza: Eliminado archivo huérfano {os.path.basename(orphan_tmp)}", f"[*] Cleanup: removed orphan file {os.path.basename(orphan_tmp)}"))
                except Exception:
                    pass
        if not os.path.exists(WORLD_DIR):
            print(L(f"[ERROR] No se encontro la carpeta del mundo: {WORLD_DIR}", f"[ERROR] World folder not found: {WORLD_DIR}"))
            return False

        os.makedirs(BACKUP_DIR, exist_ok=True)

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        # FIX F4: trigger_name puede venir de cualquier origen; se sanea para
        # que el ZIP nunca escape de BACKUP_DIR (separadores, '..', etc.)
        safe_trigger = re.sub(r"[^A-Za-z0-9_-]", "_", str(trigger_name))
        # FIX G5: nonce aleatorio en el nombre: dos backups lanzados en el
        # mismo segundo ya no comparten nombre (antes el segundo os.replace
        # pisaba silenciosamente al primero).
        nonce = os.urandom(3).hex()
        zip_filename = f"auto_backup_{SERVER_NAME}_{safe_trigger}_{timestamp}_{nonce}.zip"
        zip_filepath = os.path.join(BACKUP_DIR, zip_filename)
        if os.path.abspath(zip_filepath) != os.path.join(
            os.path.abspath(BACKUP_DIR), os.path.basename(zip_filepath)
        ):
            raise RuntimeError(L(f"Nombre de backup invalido after sanitizing: {trigger_name!r}", f"Invalid backup name after sanitizing: {trigger_name!r}"))
        tmp_filepath = zip_filepath + ".tmp"

        print(L(f"[*] Creando copia de seguridad comprimida ({trigger_name})...", f"[*] Creating compressed backup ({trigger_name})..."))

        use_snapshot = file_snapshot is not None
        
        # Modo tradicional: escanea WORLD_DIR directamente (abajo en el else)
        if use_snapshot:
            if not isinstance(file_snapshot, list) or len(file_snapshot) == 0:
                raise SnapshotDesyncError(L("Snapshot Bedrock vacio o invalido; se aborta backup caliente.", "Empty or invalid Bedrock snapshot; aborting hot backup."))

            # Validación de cobertura de snapshot: exige el archivo esencial del nivel.
            # (El conteo magico "<4" rechazaba mundos pequeños pero válidos; lo que
            # define un snapshot util es que incluya level.dat, y luego se verifica
            # la cobertura real de db/ contra disco.)
            if not any(os.path.basename(p.replace("\\", "/")) == "level.dat" for p, _ in file_snapshot):
                raise SnapshotDesyncError(
                    L("Snapshot sin level.dat; snapshot incompleto o inválido.", "Snapshot missing level.dat; incomplete or invalid snapshot.")
                )

            # Validacion cruzada contra disco: si el snapshot tiene < 70% de los archivos
            # reales en WORLD_DIR/db, esta probablemente incompleto.
            # FIX D8: el umbral se redondea a entero (int) para que mundos
            # pequenos no den falso positivo (p.ej. 2 de 3 archivos db: antes
            # 2 < 2.1 lanzaba desync aunque el snapshot era valido; reproducido
            # en vivo con BDS real).
            if os.path.exists(os.path.join(WORLD_DIR, "db")):
                real_db_files = set()
                for root, dirs, files in os.walk(os.path.join(WORLD_DIR, "db")):
                    for fname in files:
                        real_db_files.add(os.path.relpath(os.path.join(root, fname), WORLD_DIR).replace("\\", "/"))
                snapshot_db_files = {p for p, _ in file_snapshot if p.startswith("db/") or p.startswith("db\\") or "/db/" in p or "\\db\\" in p}
                min_expected = max(1, int(len(real_db_files) * 0.70))
                if len(real_db_files) > 0 and len(snapshot_db_files) < min_expected:
                    raise SnapshotDesyncError(
                        L(f"Snapshot incompleto: {len(snapshot_db_files)} archivos db/ en snapshot vs {len(real_db_files)} en disco.", f"Incomplete snapshot: {len(snapshot_db_files)} db/ files in snapshot vs {len(real_db_files)} on disk.")
                    )

        with zipfile.ZipFile(tmp_filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
            total_bytes = 0
            if use_snapshot:
                print(L(f"[*] Modo Snapshot Bedrock Nativo: guardando {len(file_snapshot)} archivo(s) congelados...", f"[*] Native Bedrock Snapshot mode: saving {len(file_snapshot)} archivo(s) congelados..."))
                for rel_path, byte_length in file_snapshot:
                    if _cancelled(cancel_event):
                        raise RuntimeError(L("Backup cancelado durante compresion snapshot.", "Backup cancelled during snapshot compression."))

                    if not isinstance(byte_length, int) or byte_length < 0:
                        raise RuntimeError(L(f"Longitud invalida para '{rel_path}': {byte_length}", f"Invalid length for '{rel_path}': {byte_length}"))

                    clean_rel_path, full_path = _resolve_snapshot_path(rel_path)
                    arcname = os.path.relpath(full_path, WORLD_DIR)

                    if not os.path.exists(full_path):
                        raise SnapshotDesyncError(L(f"Archivo de snapshot no encontrado en disco: {clean_rel_path}", f"Snapshot file not found on disk: {clean_rel_path}"))

                    # FIX F3: copia en streaming por chunks (pico de RAM
                    # constante ~2x chunk); antes se leia el archivo entero en
                    # memoria. Misma semantica que el codigo anterior:
                    #  - archivo mas corto que el snapshot -> truncado (desync)
                    #  - archivo mas largo (no-WAL) -> desync
                    #  - .log/MANIFEST (WAL) pueden crecer: se cortan en
                    #    byte_length, como hacia f.read(byte_length).
                    is_wal = clean_rel_path.endswith('.log') or 'MANIFEST-' in clean_rel_path
                    zinfo = zipfile.ZipInfo(arcname, date_time=datetime.datetime.now().timetuple()[:6])
                    zinfo.compress_type = zipfile.ZIP_DEFLATED
                    try:
                        with open(full_path, 'rb') as f, zipf.open(zinfo, 'w') as zout:
                            remaining = byte_length
                            copied = 0
                            while remaining > 0:
                                if _cancelled(cancel_event):
                                    raise RuntimeError(L("Backup cancelado durante compresion snapshot.", "Backup cancelled during snapshot compression."))
                                chunk = f.read(min(_CHUNK, remaining))
                                if not chunk:
                                    break
                                zout.write(chunk)
                                copied += len(chunk)
                                remaining -= len(chunk)
                            if copied < byte_length:
                                raise SnapshotDesyncError(
                                    L(f"Snapshot truncado en '{clean_rel_path}': {copied} < {byte_length} bytes.", f"Snapshot truncated at '{clean_rel_path}': {copied} < {byte_length} bytes.")
                                )
                            if not is_wal and f.read(1):
                                raise SnapshotDesyncError(
                                    L(f"Desincronizacion de snapshot en '{clean_rel_path}': file larger than snapshot ({byte_length}+ bytes).", f"Snapshot desync at '{clean_rel_path}': file larger than snapshot ({byte_length}+ bytes).")
                                )
                    except FileNotFoundError as fnf:
                        # TOCTOU entre el exists() y el open(): BDS pudo borrar
                        # el archivo en ese intervalo. Es desincronizacion del
                        # snapshot (reintentable), no un error de almacenamiento.
                        raise SnapshotDesyncError(
                            L(f"Archivo de snapshot desaparecido durante la copia: {clean_rel_path}", f"Snapshot file disappeared during copy: {clean_rel_path}")
                        ) from fnf

                    total_bytes += copied
                    if total_bytes > MAX_BACKUP_BYTES:
                        raise RuntimeError(
                            f"Backup excede el limite de {MAX_BACKUP_BYTES // (1024**3)} GB "
                            f"(accumulated: {total_bytes / (1024**3):.2f} GB). Aborting."
                        )

                # Bedrock 'save query' omite la configuracion de shaders/addons y el icono del mundo.
                # Debemos empacarlos manualmente en el ZIP del backup en caliente.
                static_includes = ["world_resource_packs.json", "world_behavior_packs.json", "world_icon.jpeg", "resource_packs", "behavior_packs"]
                for static_name in static_includes:
                    static_path = os.path.join(WORLD_DIR, static_name)
                    if os.path.exists(static_path):
                        if os.path.isdir(static_path):
                            for root, dirs, files in os.walk(static_path):
                                for static_file in files:
                                    full_f = os.path.join(root, static_file)
                                    arc = os.path.relpath(full_f, WORLD_DIR)
                                    zipf.write(full_f, arc)
                                    total_bytes += os.path.getsize(full_f)
                                    if total_bytes > MAX_BACKUP_BYTES:
                                        raise RuntimeError(
                                            L(f"Backup excede el limite de {MAX_BACKUP_BYTES // (1024**3)} GB. Abortando.", f"Backup exceeds the {MAX_BACKUP_BYTES // (1024**3)} GB limit. Aborting.")
                                        )
                        else:
                            arc = os.path.relpath(static_path, WORLD_DIR)
                            zipf.write(static_path, arc)
                            total_bytes += os.path.getsize(static_path)
                            if total_bytes > MAX_BACKUP_BYTES:
                                raise RuntimeError(
                                    L(f"Backup excede el limite de {MAX_BACKUP_BYTES // (1024**3)} GB. Abortando.", f"Backup exceeds the {MAX_BACKUP_BYTES // (1024**3)} GB limit. Aborting.")
                                )

                # Packs de nivel servidor (mods/addons) tambien van al backup,
                # con prefijo propio para que la restauracion los devuelva a
                # resource_packs/behavior_packs (no a la carpeta del mundo).
                total_bytes = _write_server_packs(zipf, total_bytes, cancel_event)
            else:
                # Backup completo tradicional (usado al inicio, apagar o caída por snapshot incompleto)
                for root, dirs, files in os.walk(WORLD_DIR):
                    if _cancelled(cancel_event):
                        raise RuntimeError(L("Backup cancelado durante escaneo tradicional.", "Backup cancelled during traditional scan."))
                    for file in files:
                        if _cancelled(cancel_event):
                            raise RuntimeError(L("Backup cancelado durante compresion tradicional.", "Backup cancelled during traditional compression."))
                        full_path = os.path.join(root, file)
                        arcname = os.path.relpath(full_path, WORLD_DIR)
                        zipf.write(full_path, arcname)
                        total_bytes += os.path.getsize(full_path)
                        if total_bytes > MAX_BACKUP_BYTES:
                            raise RuntimeError(
                                f"Backup excede el limite de {MAX_BACKUP_BYTES // (1024**3)} GB "
                                f"(accumulated: {total_bytes / (1024**3):.2f} GB). Aborting."
                            )

                # Packs de nivel servidor (mods/addons) tambien van al backup
                total_bytes = _write_server_packs(zipf, total_bytes, cancel_event)

        if _cancelled(cancel_event):
            raise RuntimeError(L("Backup cancelado antes de publicar ZIP.", "Backup cancelled before publishing ZIP."))

        os.replace(tmp_filepath, zip_filepath)
        # H1: el ZIP ya esta publicado: success se marca ANTES de cualquier
        # operacion que pueda fallar (getsize, print). Antes, si getsize/print
        # lanzaba (p.ej. antivirus bloqueando el archivo recien escrito), el
        # finally borraba un backup integro recien publicado (perdida de datos).
        success = True
        size_mb = os.path.getsize(zip_filepath) / (1024 * 1024)
        print(L(f"[OK] Backup creado exitosamente: {zip_filename} ({size_mb:.2f} MB)", f"[OK] Backup created successfully: {zip_filename} ({size_mb:.2f} MB)"))
        # Rotacion ejecutada dentro del lock para evitar concurrencia
        try:
            rotate_backups()
        except Exception as e:
            print(L(f"[WARN] Fallo en rotacion de backups: {e}", f"[WARN] Backup rotation failed: {e}"))
    except Exception as e:
        print(L(f"[ERROR] No se pudo crear el backup: {e}", f"[ERROR] Could not create the backup: {e}"))
        if isinstance(e, SnapshotDesyncError):
            # Snapshot desincronizado/incompleto: merece reintento (un nuevo
            # save query puede dar un snapshot consistente). Se propaga para
            # que el worker lo anote y el wrapper lo reintente con backoff.
            # Cualquier otro error en modo snapshot (disco lleno, permisos,
            # creacion del ZIP, cancelacion, limite de tamano) NO se resuelve
            # reintentando: devuelve False y el wrapper espera el intervalo
            # normal. El finally (limpieza + release del lock) corre igual.
            raise
        return False
    finally:
        # Limpiar archivos parciales o corruptos
        for cleanup_path in (tmp_filepath, zip_filepath if not success else None):
            if cleanup_path and os.path.exists(cleanup_path):
                try:
                    os.remove(cleanup_path)
                    print(L(f"[*] Limpieza: archivo parcial '{os.path.basename(cleanup_path)}' eliminado.", f"[*] Limpieza: partial file '{os.path.basename(cleanup_path)}' eliminado."))
                except Exception:
                    pass
        
        if lock_to_use and acquired_lock:
            try:
                lock_to_use.release()
            except Exception:
                pass
                
    if success:
        return zip_filepath
    return False

def rotate_backups(now=None):
    """Politica de retencion: 15 recientes + 1 por dia (ultimos 7 dias).

    Los backups marcados (_CORRUPTO/_EXCEDIDO) no compiten por las capas
    recientes/diarias: se conservan como evidencia CORRUPT_BACKUP_RETENTION_DAYS
    dias y luego se rotan. (H1: antes quedaban para siempre, fuga de disco.)

    `now` es inyectable para tests deterministas; por defecto usa la hora real.
    """
    if now is None:
        now = datetime.datetime.now()
    excluded_markers = ("_CORRUPTO", "_EXCEDIDO")
    backups = glob.glob(os.path.join(BACKUP_DIR, "auto_backup_*.zip"))
    if not backups:
        return

    backup_data = []
    for b in backups:
        try:
            mtime = os.path.getmtime(b)
            dt = datetime.datetime.fromtimestamp(mtime)
            backup_data.append({'path': b, 'mtime': mtime, 'dt': dt})
        except Exception:
            pass

    backup_data.sort(key=lambda x: x['mtime'], reverse=True)

    keepers = set()

    # Solo los backups NO marcados compiten por las capas 1 y 2.
    unmarked = [
        b for b in backup_data
        if not any(marker in os.path.basename(b['path']) for marker in excluded_markers)
    ]

    # Capa 1: Retener los N más recientes
    recent_keepers = unmarked[:MAX_RECENT_BACKUPS]
    for b in recent_keepers:
        keepers.add(b['path'])

    # Capa 2: Retener 1 por día para los últimos M días
    daily_keepers_found = set()

    for b in unmarked:
        date_diff = (now.date() - b['dt'].date()).days
        # Solo retener backups del pasado (date_diff >= 0); ignorar fechas futuras
        if 0 <= date_diff <= DAYS_TO_KEEP_DAILY:
            date_str = b['dt'].date().isoformat()
            if date_str not in daily_keepers_found:
                daily_keepers_found.add(date_str)
                keepers.add(b['path'])

    # Capa 3 (H1): backups marcados (corruptos/excedidos) se conservan como
    # evidencia dentro de la ventana de retencion; fuera de ella se rotan.
    # Las fechas futuras (age negativo) tambien se conservan, igual que en
    # la capa 2.
    for b in backup_data:
        if any(marker in os.path.basename(b['path']) for marker in excluded_markers):
            age_days = (now.date() - b['dt'].date()).days
            if age_days < CORRUPT_BACKUP_RETENTION_DAYS:
                keepers.add(b['path'])

    deleted_count = 0
    for b in backup_data:
        if b['path'] not in keepers:
            try:
                os.remove(b['path'])
                deleted_count += 1
                print(L(f"    - Rotacion: Eliminado {os.path.basename(b['path'])}", f"    - Rotation: removed {os.path.basename(b['path'])}"))
            except Exception as e:
                print(L(f"    - Error al eliminar {os.path.basename(b['path'])}: {e}", f"    - Error deleting {os.path.basename(b['path'])}: {e}"))

    if deleted_count > 0:
        print(L(f"[*] Limpieza completada. Backups retenidos: {len(keepers)}.", f"[*] Cleanup complete. Backups kept: {len(keepers)}."))

def _is_safe_zip_entry(filename: str) -> bool:
    """True si la entrada del zip es segura para extraer (anti zip-slip).

    Rechaza rutas absolutas, cualquier segmento '..' (traversal) y prefijos
    de unidad/ADS tipo 'C:'.
    """
    norm = filename.replace("\\", "/")
    if norm.startswith("/") or os.path.isabs(norm):
        return False
    segs = norm.split("/")
    if any(s == ".." for s in segs):
        return False
    if ":" in segs[0]:
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
        prefix = _PACK_ZIP_PREFIX + kind + "/"
        if norm.startswith(prefix):
            rest = norm[len(prefix):]
            if rest.endswith("/") or not rest:
                return None  # entrada de directorio: no se restaura
            parts = rest.split("/")
            if not parts[0]:
                return None
            if len(parts) >= 2:
                return kind, parts[0], "/".join(parts[1:])
            # H3: archivo suelto en la raiz del pack dir (p.ej.
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


def restore_backup(filename: str) -> str:
    """Restaura un backup ZIP al mundo y a los packs de nivel servidor.
    Requiere servidor APAGADO.

    - Valida el ZIP (zip-slip + CRC) ANTES de tocar el mundo.
    - Resguarda el mundo actual en `WORLD_DIR.bak` y cada carpeta de pack
      afectada en `<carpeta>.bak`.
    - Si la extraccion falla, hace rollback automatico de los resguardos.
    Devuelve la ruta del backup restaurado.
    """
    if os.path.basename(filename) != filename:
        raise ValueError(L("Nombre de backup invalido", "Invalid backup name"))
    zip_path = os.path.join(BACKUP_DIR, filename)
    if not os.path.isfile(zip_path):
        raise FileNotFoundError(L("Backup no encontrado", "Backup not found"))

    # 1. Validar el ZIP antes de tocar el mundo y separar entradas:
    #    packs de servidor (server_resource_packs/..., server_behavior_packs/...)
    #    vs entradas del mundo.
    with zipfile.ZipFile(zip_path, "r") as zf:
        world_infos, pack_infos = [], []
        for entry in zf.infolist():
            if not _is_safe_zip_entry(entry.filename):
                raise ValueError(L(f"Entrada insegura en el backup: {entry.filename}", f"Unsafe entry in the backup: {entry.filename}"))
            parsed = _pack_dest(entry.filename)
            if parsed:
                pack_infos.append((entry, parsed))
            else:
                world_infos.append(entry)
        bad = zf.testzip()
        if bad is not None:
            raise ValueError(L(f"Backup corrupto (CRC fallido): {bad}", f"Corrupt backup (CRC failed): {bad}"))

    bak_dir = WORLD_DIR + ".bak"
    pack_baks = []  # (destino, bak) para rollback

    # 2. Resguardar el mundo actual (si existe)
    if os.path.exists(WORLD_DIR):
        if os.path.exists(bak_dir):
            shutil.rmtree(bak_dir, ignore_errors=True)
        os.rename(WORLD_DIR, bak_dir)

    try:
        # 2b. Resguardar las carpetas de packs afectadas (si existen)
        pack_dests = set()
        for _entry, (kind, folder, _rel) in pack_infos:
            pack_dests.add(os.path.join(BASE_DIR, kind, folder))
        for dest in sorted(pack_dests):
            if os.path.exists(dest):
                bak = dest + ".bak"
                if os.path.exists(bak):
                    shutil.rmtree(bak, ignore_errors=True)
                os.rename(dest, bak)
                pack_baks.append((dest, bak))

        # 3. Extraer con doble chequeo de seguridad.
        # FIX G3: os.makedirs(WORLD_DIR) va DENTRO del try para que el rollback
        # recupere el mundo si la creacion del directorio falla (permisos/espacio).
        os.makedirs(WORLD_DIR, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            for entry in world_infos:
                zf.extract(entry, WORLD_DIR)
            for entry, (kind, folder, rel) in pack_infos:
                _extract_pack_entry(zf, entry, os.path.join(BASE_DIR, kind, folder), rel)
    except Exception as exc:
        # Rollback: recuperar el mundo y los packs anteriores
        shutil.rmtree(WORLD_DIR, ignore_errors=True)
        if os.path.exists(bak_dir):
            os.rename(bak_dir, WORLD_DIR)
        for dest, bak in reversed(pack_baks):
            shutil.rmtree(dest, ignore_errors=True)
            if os.path.exists(bak):
                os.rename(bak, dest)
        raise RuntimeError(L(f"Fallo la extraccion: {exc}", f"Extraction failed: {exc}")) from exc

    # 4. Limpieza de los resguardos si todo salio bien
    if os.path.exists(bak_dir):
        shutil.rmtree(bak_dir, ignore_errors=True)
    for dest, bak in pack_baks:
        if os.path.exists(bak):
            shutil.rmtree(bak, ignore_errors=True)
    return zip_path


if __name__ == "__main__":
    create_backup("inicio")
