import os
import datetime
import zipfile
import glob
import multiprocessing
import shutil
import re

# Lock por defecto (multiprocessing safe)
_backup_lock = multiprocessing.Lock()

# Configuracion (resuelta dinamicamente)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
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
BACKUP_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "..", "Backups_Minecraft", "auto_backups"))

# Politica de retencion
MAX_RECENT_BACKUPS = 15
DAYS_TO_KEEP_DAILY = 7

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
        raise ValueError(f"Ruta invalida (unidades diferentes?): {rel_path}")
    if common != world_abs:
        raise ValueError(f"Ruta fuera del mundo rechazada: {rel_path}")

    # Check 2: symlink traversal — realpath resuelve symlinks reales
    if os.path.exists(full_path):
        world_real = os.path.realpath(WORLD_DIR)
        real_full = os.path.realpath(full_path)
        try:
            real_common = os.path.commonpath([world_real, real_full])
        except ValueError:
            raise ValueError(f"Symlink escapa del mundo (unidades diferentes): {rel_path}")
        if real_common != world_real:
            raise ValueError(f"Symlink fuera del mundo rechazado: {rel_path}")

    return clean_rel_path, full_path


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
            print(f"[ERROR] Timeout esperando lock de backup ({wait_lock_timeout_sec}s); se cancela esta solicitud.")
            return False
        acquired_lock = True
    else:
        if not lock_to_use.acquire(False):
            print("[ERROR] Ya hay un backup ejecutandose; se cancela esta solicitud.")
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
                    print(f"[*] Limpieza: Eliminado archivo huérfano {os.path.basename(orphan_tmp)}")
                except Exception:
                    pass
        if not os.path.exists(WORLD_DIR):
            print(f"[ERROR] No se encontro la carpeta del mundo: {WORLD_DIR}")
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
        zip_filename = f"auto_backup_{safe_trigger}_{timestamp}_{nonce}.zip"
        zip_filepath = os.path.join(BACKUP_DIR, zip_filename)
        if os.path.abspath(zip_filepath) != os.path.join(
            os.path.abspath(BACKUP_DIR), os.path.basename(zip_filepath)
        ):
            raise RuntimeError(f"Nombre de backup invalido tras saneo: {trigger_name!r}")
        tmp_filepath = zip_filepath + ".tmp"

        print(f"[*] Creando copia de seguridad comprimida ({trigger_name})...")

        use_snapshot = file_snapshot is not None
        
        # Modo tradicional: escanea WORLD_DIR directamente (abajo en el else)
        if use_snapshot:
            if not isinstance(file_snapshot, list) or len(file_snapshot) == 0:
                raise SnapshotDesyncError("Snapshot Bedrock vacio o invalido; se aborta backup caliente.")

            # Validación de cobertura de snapshot: exige el archivo esencial del nivel.
            # (El conteo magico "<4" rechazaba mundos pequeños pero válidos; lo que
            # define un snapshot util es que incluya level.dat, y luego se verifica
            # la cobertura real de db/ contra disco.)
            if not any(os.path.basename(p.replace("\\", "/")) == "level.dat" for p, _ in file_snapshot):
                raise SnapshotDesyncError(
                    "Snapshot sin level.dat; snapshot incompleto o inválido."
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
                        f"Snapshot incompleto: {len(snapshot_db_files)} archivos db/ en snapshot vs {len(real_db_files)} en disco."
                    )

        with zipfile.ZipFile(tmp_filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
            total_bytes = 0
            if use_snapshot:
                print(f"[*] Modo Snapshot Bedrock Nativo: guardando {len(file_snapshot)} archivo(s) congelados...")
                for rel_path, byte_length in file_snapshot:
                    if _cancelled(cancel_event):
                        raise RuntimeError("Backup cancelado durante compresion snapshot.")

                    if not isinstance(byte_length, int) or byte_length < 0:
                        raise RuntimeError(f"Longitud invalida para '{rel_path}': {byte_length}")

                    clean_rel_path, full_path = _resolve_snapshot_path(rel_path)
                    arcname = os.path.relpath(full_path, WORLD_DIR)

                    if not os.path.exists(full_path):
                        raise SnapshotDesyncError(f"Archivo de snapshot no encontrado en disco: {clean_rel_path}")

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
                                    raise RuntimeError("Backup cancelado durante compresion snapshot.")
                                chunk = f.read(min(_CHUNK, remaining))
                                if not chunk:
                                    break
                                zout.write(chunk)
                                copied += len(chunk)
                                remaining -= len(chunk)
                            if copied < byte_length:
                                raise SnapshotDesyncError(
                                    f"Snapshot truncado en '{clean_rel_path}': {copied} < {byte_length} bytes."
                                )
                            if not is_wal and f.read(1):
                                raise SnapshotDesyncError(
                                    f"Desincronizacion de snapshot en '{clean_rel_path}': archivo mas grande que snapshot ({byte_length}+ bytes)."
                                )
                    except FileNotFoundError as fnf:
                        # TOCTOU entre el exists() y el open(): BDS pudo borrar
                        # el archivo en ese intervalo. Es desincronizacion del
                        # snapshot (reintentable), no un error de almacenamiento.
                        raise SnapshotDesyncError(
                            f"Archivo de snapshot desaparecido durante la copia: {clean_rel_path}"
                        ) from fnf

                    total_bytes += copied
                    if total_bytes > MAX_BACKUP_BYTES:
                        raise RuntimeError(
                            f"Backup excede el limite de {MAX_BACKUP_BYTES // (1024**3)} GB "
                            f"(acumulado: {total_bytes / (1024**3):.2f} GB). Abortando."
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
                                            f"Backup excede el limite de {MAX_BACKUP_BYTES // (1024**3)} GB. Abortando."
                                        )
                        else:
                            arc = os.path.relpath(static_path, WORLD_DIR)
                            zipf.write(static_path, arc)
                            total_bytes += os.path.getsize(static_path)
                            if total_bytes > MAX_BACKUP_BYTES:
                                raise RuntimeError(
                                    f"Backup excede el limite de {MAX_BACKUP_BYTES // (1024**3)} GB. Abortando."
                                )
            else:
                # Backup completo tradicional (usado al inicio, apagar o caída por snapshot incompleto)
                for root, dirs, files in os.walk(WORLD_DIR):
                    if _cancelled(cancel_event):
                        raise RuntimeError("Backup cancelado durante escaneo tradicional.")
                    for file in files:
                        if _cancelled(cancel_event):
                            raise RuntimeError("Backup cancelado durante compresion tradicional.")
                        full_path = os.path.join(root, file)
                        arcname = os.path.relpath(full_path, WORLD_DIR)
                        zipf.write(full_path, arcname)
                        total_bytes += os.path.getsize(full_path)
                        if total_bytes > MAX_BACKUP_BYTES:
                            raise RuntimeError(
                                f"Backup excede el limite de {MAX_BACKUP_BYTES // (1024**3)} GB "
                                f"(acumulado: {total_bytes / (1024**3):.2f} GB). Abortando."
                            )

        if _cancelled(cancel_event):
            raise RuntimeError("Backup cancelado antes de publicar ZIP.")

        os.replace(tmp_filepath, zip_filepath)
        size_mb = os.path.getsize(zip_filepath) / (1024 * 1024)
        print(f"[OK] Backup creado exitosamente: {zip_filename} ({size_mb:.2f} MB)")
        success = True
        # Rotacion ejecutada dentro del lock para evitar concurrencia
        try:
            rotate_backups()
        except Exception as e:
            print(f"[WARN] Fallo en rotacion de backups: {e}")
    except Exception as e:
        print(f"[ERROR] No se pudo crear el backup: {e}")
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
                    print(f"[*] Limpieza: archivo parcial '{os.path.basename(cleanup_path)}' eliminado.")
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

    `now` es inyectable para tests deterministas; por defecto usa la hora real.
    """
    if now is None:
        now = datetime.datetime.now()
    excluded_markers = ("_CORRUPTO", "_EXCEDIDO")
    backups = [
        b for b in glob.glob(os.path.join(BACKUP_DIR, "auto_backup_*.zip"))
        if not any(marker in os.path.basename(b) for marker in excluded_markers)
    ]
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
    
    # Capa 1: Retener los N más recientes
    recent_keepers = backup_data[:MAX_RECENT_BACKUPS]
    for b in recent_keepers:
        keepers.add(b['path'])
        
    # Capa 2: Retener 1 por día para los últimos M días
    daily_keepers_found = set()
    
    for b in backup_data:
        date_diff = (now.date() - b['dt'].date()).days
        # Solo retener backups del pasado (date_diff >= 0); ignorar fechas futuras
        if 0 <= date_diff <= DAYS_TO_KEEP_DAILY:
            date_str = b['dt'].date().isoformat()
            if date_str not in daily_keepers_found:
                daily_keepers_found.add(date_str)
                keepers.add(b['path'])
                
    deleted_count = 0
    for b in backup_data:
        if b['path'] not in keepers:
            try:
                os.remove(b['path'])
                deleted_count += 1
                print(f"    - Rotacion: Eliminado {os.path.basename(b['path'])}")
            except Exception as e:
                print(f"    - Error al eliminar {os.path.basename(b['path'])}: {e}")
                
    if deleted_count > 0:
        print(f"[*] Limpieza completada. Backups retenidos: {len(keepers)}.")

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


def restore_backup(filename: str) -> str:
    """Restaura un backup ZIP al mundo. Requiere servidor APAGADO.

    - Valida el ZIP (zip-slip + CRC) ANTES de tocar el mundo.
    - Resguarda el mundo actual en `WORLD_DIR.bak`.
    - Si la extraccion falla, hace rollback automatico del resguardo.
    Devuelve la ruta del backup restaurado.
    """
    if os.path.basename(filename) != filename:
        raise ValueError("Nombre de backup invalido")
    zip_path = os.path.join(BACKUP_DIR, filename)
    if not os.path.isfile(zip_path):
        raise FileNotFoundError("Backup no encontrado")

    # 1. Validar el ZIP antes de tocar el mundo
    with zipfile.ZipFile(zip_path, "r") as zf:
        for entry in zf.infolist():
            if not _is_safe_zip_entry(entry.filename):
                raise ValueError(f"Entrada insegura en el backup: {entry.filename}")
        bad = zf.testzip()
        if bad is not None:
            raise ValueError(f"Backup corrupto (CRC fallido): {bad}")

    bak_dir = WORLD_DIR + ".bak"

    # 2. Resguardar el mundo actual (si existe)
    if os.path.exists(WORLD_DIR):
        if os.path.exists(bak_dir):
            shutil.rmtree(bak_dir, ignore_errors=True)
        os.rename(WORLD_DIR, bak_dir)

    # 3. Extraer con doble chequeo de seguridad.
    # FIX G3: os.makedirs(WORLD_DIR) va DENTRO del try para que el rollback
    # recupere el mundo si la creacion del directorio falla (permisos/espacio).
    try:
        os.makedirs(WORLD_DIR, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            for entry in zf.infolist():
                if not _is_safe_zip_entry(entry.filename):
                    raise ValueError(f"Entrada insegura: {entry.filename}")
                zf.extract(entry, WORLD_DIR)
    except Exception as exc:
        # Rollback: recuperar el mundo anterior
        shutil.rmtree(WORLD_DIR, ignore_errors=True)
        if os.path.exists(bak_dir):
            os.rename(bak_dir, WORLD_DIR)
        raise RuntimeError(f"Fallo la extraccion: {exc}") from exc

    # 4. Limpieza del resguardo si todo salio bien
    if os.path.exists(bak_dir):
        shutil.rmtree(bak_dir, ignore_errors=True)
    return zip_path


if __name__ == "__main__":
    create_backup("inicio")
