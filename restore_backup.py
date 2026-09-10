import os
import glob
import zipfile
import shutil
import datetime

try:
    import psutil
except ImportError:
    psutil = None  # H3: sin psutil no se puede probar BDS parado -> fail-closed

from zip_safety import (
    _is_safe_zip_entry,
    _pack_dest,
    _extract_pack_entry,
    _quarantine_and_restore,
    _exceeds_expansion_limit,
    CORRUPT_MARKERS,
)
import zip_safety as _zip_safety

# Constantes centralizadas en zip_safety (fuente unica anti-drift)
_SERVER_PACK_DIRS = _zip_safety.SERVER_PACK_DIRS
_PACK_ZIP_PREFIX = _zip_safety.PACK_ZIP_PREFIX

# Rutas RESUELTAS desde la propia ubicacion del script: cada instalacion
# restaura SU mundo. (Antes estaban hardcodeadas a "Servidor de Guapo", de
# modo que ejecutar este script desde otra instalacion sobrescribia el mundo
# de la vecina.)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _world_name(base_dir=None):
    """Nombre del nivel desde server.properties (misma regla que auto_backup)."""
    bdir = base_dir or BASE_DIR
    from server_properties import read_value

    val = read_value(os.path.join(bdir, "server.properties"), "level-name")
    if val:
        return val
    return "Bedrock level"


def _resolve_backup_dir(base_dir):
    return os.path.abspath(os.path.join(
        base_dir, "..", "..", "Backups_Minecraft", "auto_backups",
        os.path.basename(os.path.normpath(base_dir)),
    ))


WORLD_DIR = os.path.join(BASE_DIR, "worlds", _world_name())
SERVER_NAME = os.path.basename(os.path.normpath(BASE_DIR))
BACKUP_DIR = _resolve_backup_dir(BASE_DIR)
# Marcadores canonicos centralizados en zip_safety (GUI y CLI coinciden)
_CORRUPT_MARKERS = CORRUPT_MARKERS


def get_world_dir(base_dir=None):
    """Resuelve la ruta del mundo activo dinámicamente según server.properties."""
    bdir = base_dir or BASE_DIR
    if bdir == BASE_DIR and "WORLD_DIR" in globals():
        current_global = globals()["WORLD_DIR"]
        if current_global != os.path.join(BASE_DIR, "worlds", "Bedrock level") and current_global != os.path.join(BASE_DIR, "worlds", _world_name(BASE_DIR)):
            return current_global
    return os.path.join(bdir, "worlds", _world_name(bdir))


def get_backup_dir(base_dir=None):
    """Resuelve el directorio de backups dinámicamente."""
    bdir = base_dir or BASE_DIR
    if bdir == BASE_DIR and "BACKUP_DIR" in globals():
        current_global = globals()["BACKUP_DIR"]
        if current_global != _resolve_backup_dir(BASE_DIR):
            return current_global
    return _resolve_backup_dir(bdir)



def _validate_backup(zip_path: str):
    """Valida el zip ANTES de tocar el mundo. Lanza excepcion si es peligroso o esta corrupto."""
    with zipfile.ZipFile(zip_path, "r") as zipf:
        for entry in zipf.infolist():
            if not _is_safe_zip_entry(entry.filename):
                raise ValueError(f"Entrada insegura en el backup: {entry.filename}")
        bad = zipf.testzip()
        if bad is not None:
            raise ValueError(f"Backup corrupto (CRC fallido): {bad}")
        if _exceeds_expansion_limit(zipf.infolist()):
            raise ValueError("Backup rechazado: su tamano descomprimido excede el limite de seguridad.")


def _list_backup_files(backup_dir):
    """Devuelve solo backups aptos para ofrecerlos en la CLI."""
    return [
        path for path in glob.glob(os.path.join(backup_dir, "auto_backup_*.zip"))
        if not any(marker in os.path.basename(path) for marker in _CORRUPT_MARKERS)
    ]


# _pack_dest y constantes de packs centralizados en zip_safety (importados arriba)



def _server_is_running():
    """True si bedrock_server.exe DE ESTA INSTALACION esta en ejecucion.

    H3: escopado por la ruta del ejecutable (misma regla que la sonda de la
    GUI en gui_backend/services/external_probe.py): un BDS de otra instalacion
    no debe vetar la restauracion de esta.

    Fail-closed (operacion destructiva):
      - sin psutil no se puede comprobar -> True;
      - si no se puede leer la ruta de un proceso bedrock_server.exe
        (AccessDenied, p. ej. elevado) no se puede descartar que sea el nuestro
        -> True;
      - si el listado de procesos falla -> True.
    """
    if psutil is None:
        return True
    target_exe = os.path.normcase(os.path.abspath(
        os.path.join(BASE_DIR, "bedrock_server.exe")
    ))
    try:
        for p in psutil.process_iter(["name"]):
            try:
                name = (p.info.get("name") or "").lower()
                if name != "bedrock_server.exe":
                    continue
                try:
                    exe = os.path.normcase(os.path.abspath(p.exe()))
                except psutil.AccessDenied:
                    return True  # no se puede descartar que sea el nuestro
                except psutil.NoSuchProcess:
                    continue
                if exe == target_exe:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        return True  # ante la duda, no tocar el mundo
    return False


def list_and_restore():
    os.system("cls" if os.name == "nt" else "clear")
    print("=" * 60)
    print("      RESTAURAR BACKUP AUTOMATICO (ESTILO REALMS)")
    print("=" * 60)
    print()

    # H3: guard anticipado: restaurar con BDS vivo pisaria un mundo en uso.
    if _server_is_running():
        print("[ERROR] El servidor de Minecraft parece estar corriendo (bedrock_server.exe).")
        print("        Apaga el servidor antes de restaurar un backup.")
        input("\nPresiona Enter para salir...")
        return

    if not os.path.exists(BACKUP_DIR):
        print(f"[ERROR] No se encontro la carpeta de backups: {BACKUP_DIR}")
        input("\nPresiona Enter para salir...")
        return

    backups = _list_backup_files(BACKUP_DIR)
    backups.sort(key=os.path.getmtime, reverse=True)  # Mas reciente primero

    if not backups:
        print("No hay copias de seguridad automaticas disponibles.")
        input("\nPresiona Enter para salir...")
        return

    print("Backups disponibles (del mas reciente al mas antiguo):\n")
    for idx, bpath in enumerate(backups, 1):
        fname = os.path.basename(bpath)
        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(bpath)).strftime("%d/%m/%Y %H:%M:%S")
        size_mb = os.path.getsize(bpath) / (1024 * 1024)
        print(f"  [{idx}] -> Fecha: {mtime} | Archivo: {fname} ({size_mb:.1f} MB)")

    print("\n" + "-" * 60)
    print("  [0] Cancelar y salir")
    print("-" * 60)

    choice = input("\nElige el numero del backup que deseas restaurar (ejemplo: 1): ").strip()

    if choice == "0" or not choice:
        print("Operacion cancelada.")
        return

    try:
        idx_chosen = int(choice) - 1
        if idx_chosen < 0 or idx_chosen >= len(backups):
            print("[ERROR] Numero invalido.")
            input("\nPresiona Enter para salir...")
            return
        selected_zip = backups[idx_chosen]
    except ValueError:
        print("[ERROR] Por favor ingresa un numero valido.")
        input("\nPresiona Enter para salir...")
        return

    print("\n" + "=" * 60)
    print("  ATENCION: Se restaurara el backup:")
    print(f"  {os.path.basename(selected_zip)}")
    print("  El mundo actual sera reemplazado con este punto de restauracion.")
    print("=" * 60)

    confirm = input("\nEstas seguro? Escribe 'SI' para confirmar: ").strip().upper()
    if confirm != "SI":
        print("\nOperacion cancelada.")
        input("\nPresiona Enter para salir...")
        return

    print("\n[*] Validando backup antes de tocar el mundo...")
    try:
        _validate_backup(selected_zip)
    except Exception as e:
        print(f"[ERROR] Backup rechazado: {e}. El mundo NO fue modificado.")
        input("\nPresiona Enter para salir...")
        return

    # Separar entradas del ZIP: mundo vs packs de nivel servidor (mods/addons).
    # _validate_backup ya rechazo traversal y CRC corrupto; aqui solo se
    # clasifica para restaurar cada parte a su destino.
    with zipfile.ZipFile(selected_zip, "r") as zipf:
        world_infos, pack_infos = [], []
        for entry in zipf.infolist():
            parsed = _pack_dest(entry.filename)
            if parsed:
                pack_infos.append((entry, parsed))
            else:
                world_infos.append(entry)

    active_world_dir = get_world_dir()

    nonce = os.urandom(4).hex()
    world_staging = active_world_dir + f".restore_staging_{nonce}"
    pack_dir_stagings = {}   # dest_dir -> staging_dir
    pack_file_stagings = {}  # dest_file -> staging_file

    for _entry, (kind, folder, rel) in pack_infos:
        if folder:
            dest_dir = os.path.normpath(os.path.join(BASE_DIR, kind, folder))
            if dest_dir not in pack_dir_stagings:
                pack_dir_stagings[dest_dir] = dest_dir + f".restore_staging_{nonce}"
        else:
            dest_file = os.path.normpath(os.path.join(BASE_DIR, kind, rel))
            if dest_file not in pack_file_stagings:
                pack_file_stagings[dest_file] = dest_file + f".restore_staging_{nonce}"

    print("[*] Descomprimiendo backup en área temporal (staging)...")
    try:
        os.makedirs(world_staging, exist_ok=True)
        with zipfile.ZipFile(selected_zip, "r") as zipf:
            for entry in world_infos:
                zipf.extract(entry, world_staging)
            for entry, (kind, folder, rel) in pack_infos:
                if folder:
                    dest_dir = os.path.normpath(os.path.join(BASE_DIR, kind, folder))
                    _extract_pack_entry(zipf, entry, pack_dir_stagings[dest_dir], rel)
                else:
                    dest_file = os.path.normpath(os.path.join(BASE_DIR, kind, rel))
                    staging_f = pack_file_stagings[dest_file]
                    os.makedirs(os.path.dirname(staging_f), exist_ok=True)
                    with zipf.open(entry, "r") as src, open(staging_f, "wb") as out:
                        shutil.copyfileobj(src, out)

        if world_infos and not os.path.exists(os.path.join(world_staging, "level.dat")):
            raise RuntimeError("El staging no contiene level.dat válido; restauración abortada sin tocar el mundo.")
    except Exception as e:
        print(f"[ERROR] Falló la descompresión: {e}. El mundo original NO fue modificado.")
        shutil.rmtree(world_staging, ignore_errors=True)
        for s_dir in pack_dir_stagings.values():
            shutil.rmtree(s_dir, ignore_errors=True)
        for s_file in pack_file_stagings.values():
            if os.path.exists(s_file):
                try:
                    os.remove(s_file)
                except Exception:
                    pass
        input("\nPresiona Enter para salir...")
        return

    bak_dir = active_world_dir + f".bak_{nonce}"
    pack_baks = []  # (active_path, bak_path, is_dir)
    swap_success = False

    print("[*] Intercambiando con el mundo y packs activos...")
    try:
        # Resguardar el mundo actual (si existe)
        if os.path.exists(active_world_dir):
            os.rename(active_world_dir, bak_dir)

        # Resguardar packs actuales (si existen)
        for dest_dir in sorted(pack_dir_stagings.keys()):
            if os.path.exists(dest_dir):
                bak = dest_dir + f".bak_{nonce}"
                os.rename(dest_dir, bak)
                pack_baks.append((dest_dir, bak, True))

        for dest_file in sorted(pack_file_stagings.keys()):
            if os.path.exists(dest_file):
                bak = dest_file + f".bak_{nonce}"
                os.rename(dest_file, bak)
                pack_baks.append((dest_file, bak, False))

        # Mover staging a destinos finales
        os.rename(world_staging, active_world_dir)
        for dest_dir, s_dir in pack_dir_stagings.items():
            if os.path.exists(s_dir):
                os.makedirs(os.path.dirname(dest_dir), exist_ok=True)
                os.rename(s_dir, dest_dir)
        for dest_file, s_file in pack_file_stagings.items():
            if os.path.exists(s_file):
                os.makedirs(os.path.dirname(dest_file), exist_ok=True)
                os.rename(s_file, dest_file)

        swap_success = True
        print("\n=====================================================")
        print("  [OK] MUNDO RESTAURADO EXITOSAMENTE!")
        print("=====================================================")
        print("Ya puedes iniciar el servidor con iniciar_servidor.bat")
    except Exception as e:
        print(f"[ERROR] Falló el intercambio: {e}. Iniciando rollback...")
        _quarantine_and_restore(active_world_dir, bak_dir, is_dir=True)

        for active_p, bak_p, is_d in reversed(pack_baks):
            _quarantine_and_restore(active_p, bak_p, is_dir=is_d)

        shutil.rmtree(world_staging, ignore_errors=True)
        for s_dir in pack_dir_stagings.values():
            shutil.rmtree(s_dir, ignore_errors=True)
        for s_file in pack_file_stagings.values():
            if os.path.exists(s_file):
                try:
                    os.remove(s_file)
                except Exception:
                    pass

    # Limpieza de resguardos si todo salió bien
    if swap_success:
        if os.path.exists(bak_dir):
            try:
                shutil.rmtree(bak_dir, ignore_errors=True)
            except Exception:
                pass
        for active_p, bak_p, is_d in pack_baks:
            if os.path.exists(bak_p):
                try:
                    if is_d:
                        shutil.rmtree(bak_p, ignore_errors=True)
                    else:
                        os.remove(bak_p)
                except Exception:
                    pass

    input("\nPresiona Enter para cerrar...")


if __name__ == "__main__":
    list_and_restore()
