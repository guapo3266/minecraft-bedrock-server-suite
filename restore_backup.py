import os
import glob
import datetime

try:
    import psutil
except ImportError:
    psutil = None  # H3: sin psutil no se puede probar BDS parado -> fail-closed

import restore_core
import console_lang
from zip_safety import CORRUPT_MARKERS

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
# Instantanea del mundo resuelto AL IMPORTAR: distingue un monkeypatch de
# tests (WORLD_DIR != este valor) de un WORLD_DIR stale si server.properties
# cambio durante la sesion (misma heuristica H3 que auto_backup).
_IMPORT_TIME_WORLD_DIR = WORLD_DIR
# Marcadores canonicos centralizados en zip_safety (GUI y CLI coinciden)
_CORRUPT_MARKERS = CORRUPT_MARKERS


def get_world_dir(base_dir=None):
    """Resuelve la ruta del mundo activo dinámicamente según server.properties.

    Misma heuristica que auto_backup.get_world_dir: con global distinto al
    valor de import se respeta el monkeypatch de tests; si no, se relee
    server.properties (un mundo stale no debe recibir la restauracion).
    """
    bdir = base_dir or BASE_DIR
    if bdir == BASE_DIR and "WORLD_DIR" in globals():
        current_global = globals()["WORLD_DIR"]
        if current_global != _IMPORT_TIME_WORLD_DIR:
            return current_global  # monkeypatch de tests: respetar
    return os.path.join(bdir, "worlds", _world_name(bdir))


def get_backup_dir(base_dir=None):
    """Resuelve el directorio de backups dinámicamente."""
    bdir = base_dir or BASE_DIR
    if bdir == BASE_DIR and "BACKUP_DIR" in globals():
        current_global = globals()["BACKUP_DIR"]
        if current_global != _resolve_backup_dir(BASE_DIR):
            return current_global
    return _resolve_backup_dir(bdir)



def _list_backup_files(backup_dir):
    """Devuelve solo backups aptos para ofrecerlos en la CLI."""
    return [
        path for path in glob.glob(os.path.join(backup_dir, "auto_backup_*.zip"))
        if not any(marker in os.path.basename(path) for marker in _CORRUPT_MARKERS)
    ]



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

    # La CLI es es-only (prompts hardcodeados en español): fija el idioma del
    # proceso para los mensajes de restore_core y lo restaura al salir (los
    # tests corren en el mismo proceso y no deben heredar el cambio).
    previo = os.environ.get("WRAPPER_LANG")
    console_lang.set_lang("es")
    try:
        restore_core.restore_from_zip(selected_zip, BASE_DIR, get_world_dir())
    except Exception as e:
        print(f"[ERROR] Falló la restauración: {e}. El mundo original NO fue modificado.")
        input("\nPresiona Enter para salir...")
        return
    finally:
        if previo is None:
            os.environ.pop("WRAPPER_LANG", None)
        else:
            os.environ["WRAPPER_LANG"] = previo

    print("\n=====================================================")
    print("  [OK] MUNDO RESTAURADO EXITOSAMENTE!")
    print("=====================================================")
    print("Ya puedes iniciar el servidor con iniciar_servidor.bat")

    input("\nPresiona Enter para cerrar...")


if __name__ == "__main__":
    list_and_restore()
