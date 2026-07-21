import os
import sys
import datetime
import zipfile
import glob
import threading

# Configuración dinámicamente resuelta para máxima portabilidad
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WORLD_DIR = os.path.join(BASE_DIR, "worlds", "Bedrock level")
WORLD_PARENT_DIR = os.path.join(BASE_DIR, "worlds")
BACKUP_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "..", "Backups_Minecraft", "auto_backups"))

# Retención de Doble Capa
MAX_RECENT_BACKUPS = 15
DAYS_TO_KEEP_DAILY = 7
_backup_lock = threading.Lock()

def _cancelled(cancel_event):
    return cancel_event is not None and cancel_event.is_set()


def _resolve_snapshot_path(rel_path):
    clean_rel_path = rel_path.replace("/", os.sep).replace("\\", os.sep)
    world_name = os.path.basename(os.path.abspath(WORLD_DIR))
    first_part = clean_rel_path.split(os.sep, 1)[0]

    if first_part.lower() == "worlds":
        full_path = os.path.abspath(os.path.normpath(os.path.join(BASE_DIR, clean_rel_path)))
    elif first_part == world_name:
        full_path = os.path.abspath(os.path.normpath(os.path.join(WORLD_PARENT_DIR, clean_rel_path)))
    else:
        full_path = os.path.abspath(os.path.normpath(os.path.join(WORLD_DIR, clean_rel_path)))

    world_root = os.path.abspath(WORLD_DIR)

    if os.path.commonpath([world_root, full_path]) != world_root:
        raise ValueError(f"Ruta fuera del mundo rechazada: {rel_path}")

    return clean_rel_path, full_path


def create_backup(trigger_name="auto", file_snapshot=None, cancel_event=None):
    """
    Crea una copia de seguridad comprimida del mundo.
    - file_snapshot: Lista de tuplas (rel_path, byte_count) devueltas por 'save query'.
      Si se provee, SOLO se leen y copian esos archivos hasta esa cantidad exacta de bytes (Protocolo Bedrock Nativo).
      Si es None, se realiza un backup tradicional escaneando WORLD_DIR.
    """
    if not _backup_lock.acquire(blocking=False):
        print("[ERROR] Ya hay un backup ejecutandose; se cancela esta solicitud.")
        return False

    success = False
    zip_filepath = None
    tmp_filepath = None

    try:
        if not os.path.exists(WORLD_DIR):
            print(f"[ERROR] No se encontro la carpeta del mundo: {WORLD_DIR}")
            return False

        os.makedirs(BACKUP_DIR, exist_ok=True)

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        zip_filename = f"auto_backup_{trigger_name}_{timestamp}.zip"
        zip_filepath = os.path.join(BACKUP_DIR, zip_filename)
        tmp_filepath = zip_filepath + ".tmp"

        print(f"[*] Creando copia de seguridad comprimida ({trigger_name})...")

        # Contar archivos físicos existentes en el mundo
        physical_files_count = 0
        for root, dirs, files in os.walk(WORLD_DIR):
            if _cancelled(cancel_event):
                raise RuntimeError("Backup cancelado antes de iniciar compresion.")
            physical_files_count += len(files)

        use_snapshot = file_snapshot is not None
        if use_snapshot:
            if not isinstance(file_snapshot, list) or len(file_snapshot) == 0:
                raise RuntimeError("Snapshot Bedrock vacio o invalido; se aborta backup caliente.")

            # Validación de cobertura: en backup caliente se falla cerrado.
            min_expected = int(physical_files_count * 0.8)
            if physical_files_count > 0 and len(file_snapshot) < min_expected:
                raise RuntimeError(
                    f"Snapshot incompleto o sospechoso ({len(file_snapshot)} de {physical_files_count} archivos)."
                )

        with zipfile.ZipFile(tmp_filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
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
                        raise RuntimeError(f"Archivo de snapshot no encontrado en disco: {clean_rel_path}")

                    with open(full_path, 'rb') as f:
                        data = f.read(byte_length)

                    if len(data) != byte_length:
                        raise RuntimeError(
                            f"Lectura corta en '{clean_rel_path}': {len(data)} de {byte_length} bytes."
                        )

                    zinfo = zipfile.ZipInfo(arcname, date_time=datetime.datetime.now().timetuple()[:6])
                    zinfo.compress_type = zipfile.ZIP_DEFLATED
                    zipf.writestr(zinfo, data)
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

        if _cancelled(cancel_event):
            raise RuntimeError("Backup cancelado antes de publicar ZIP.")

        os.replace(tmp_filepath, zip_filepath)
        size_mb = os.path.getsize(zip_filepath) / (1024 * 1024)
        print(f"[OK] Backup creado exitosamente: {zip_filename} ({size_mb:.2f} MB)")
        success = True

        # Limpieza automatica de rotación
        rotate_backups()
        return zip_filepath
    except Exception as e:
        print(f"[ERROR] No se pudo crear el backup: {e}")
        return False
    finally:
        # Garantía antirresiduos: Si ocurrió un error o la compresión no se completó, borrar ZIP corrupto/incompleto
        for cleanup_path in (tmp_filepath, zip_filepath if not success else None):
            if cleanup_path and os.path.exists(cleanup_path):
                try:
                    os.remove(cleanup_path)
                    print(f"[*] Limpieza de emergencia: eliminado archivo incompleto {os.path.basename(cleanup_path)}")
                except Exception as clean_err:
                    print(f"[WARN] No se pudo eliminar archivo incompleto {cleanup_path}: {clean_err}")
        _backup_lock.release()

def rotate_backups():
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
    now = datetime.datetime.now()
    daily_keepers_found = set()
    
    for b in backup_data:
        days_old = abs((now.date() - b['dt'].date()).days)
        if days_old <= DAYS_TO_KEEP_DAILY:
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

if __name__ == "__main__":
    create_backup("inicio")
