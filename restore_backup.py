import os
import glob
import zipfile
import shutil
import datetime

# Rutas RESUELTAS desde la propia ubicacion del script: cada instalacion
# restaura SU mundo. (Antes estaban hardcodeadas a "Servidor de Guapo", de
# modo que ejecutar este script desde otra instalacion sobrescribia el mundo
# de la vecina.)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _world_name():
    """Nombre del nivel desde server.properties (misma regla que auto_backup)."""
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


WORLD_DIR = os.path.join(BASE_DIR, "worlds", _world_name())
BACKUP_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "..", "Backups_Minecraft", "auto_backups"))
_CORRUPT_MARKERS = ("_CORRUPTO", "_EXCEDIDO")


def _is_safe_zip_entry(filename: str) -> bool:
    """True si la entrada del zip es segura para extraer (anti zip-slip).

    Rechaza rutas absolutas, cualquier segmento '..' (traversal) y prefijos
    de unidad/ADS tipo 'C:'. Misma regla que la GUI (server_gui_server.py).
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


def _validate_backup(zip_path: str):
    """Valida el zip ANTES de tocar el mundo. Lanza excepcion si es peligroso o esta corrupto."""
    with zipfile.ZipFile(zip_path, "r") as zipf:
        for entry in zipf.infolist():
            if not _is_safe_zip_entry(entry.filename):
                raise ValueError(f"Entrada insegura en el backup: {entry.filename}")
        bad = zipf.testzip()
        if bad is not None:
            raise ValueError(f"Backup corrupto (CRC fallido): {bad}")


def _list_backup_files(backup_dir):
    """Devuelve solo backups aptos para ofrecerlos en la CLI."""
    return [
        path for path in glob.glob(os.path.join(backup_dir, "auto_backup_*.zip"))
        if not any(marker in os.path.basename(path) for marker in _CORRUPT_MARKERS)
    ]


# Carpetas de nivel servidor que el backup incluye junto al mundo (mods/addons).
# Mismas constantes que auto_backup.py: los zips guardan estas carpetas con
# prefijo propio ("server_resource_packs/...", "server_behavior_packs/...") y
# la restauracion las devuelve a su ubicacion de servidor.
_SERVER_PACK_DIRS = ("resource_packs", "behavior_packs")
_PACK_ZIP_PREFIX = "server_"


def _pack_dest(entry_filename):
    """Clasifica una entrada del ZIP: pack de nivel servidor -> (kind, folder,
    rel_path) con rel_path relativo a la carpeta del pack; None = mundo."""
    norm = entry_filename.replace("\\", "/")
    for kind in _SERVER_PACK_DIRS:
        prefix = _PACK_ZIP_PREFIX + kind + "/"
        if norm.startswith(prefix):
            rest = norm[len(prefix):]
            if rest.endswith("/") or not rest:
                return None  # entrada de directorio: no se restaura
            parts = rest.split("/")
            if len(parts) >= 2 and parts[0]:
                return kind, parts[0], "/".join(parts[1:])
            return None
    return None


def _extract_pack_entry(zipf, entry, base_dir, rel_path):
    """Extrae una entrada de pack a base_dir con doble chequeo anti traversal."""
    segs = rel_path.split("/")
    if any(s == ".." for s in segs) or os.path.isabs(rel_path) or ":" in segs[0]:
        raise ValueError(f"Entrada de pack insegura: {entry.filename}")
    dest = os.path.join(base_dir, *segs)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with zipf.open(entry, "r") as src, open(dest, "wb") as out:
        shutil.copyfileobj(src, out)


def list_and_restore():
    os.system("cls" if os.name == "nt" else "clear")
    print("=" * 60)
    print("      RESTAURAR BACKUP AUTOMATICO (ESTILO REALMS)")
    print("=" * 60)
    print()

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
    print(f"  ATENCION: Se restaurara el backup:")
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

    bak_dir = WORLD_DIR + ".bak"
    pack_baks = []  # (destino, bak) para rollback

    print("[*] Resguardando mundo actual...")
    if os.path.exists(WORLD_DIR):
        if os.path.exists(bak_dir):
            try:
                shutil.rmtree(bak_dir)
            except Exception as e:
                print(f"[ERROR] No se pudo limpiar el resguardo anterior: {e}")
                input("\nPresiona Enter para salir...")
                return
        try:
            os.rename(WORLD_DIR, bak_dir)
        except Exception as e:
            print(f"[ERROR] No se pudo resguardar el mundo actual. Esta el servidor encendido?: {e}")
            input("\nApaga el servidor primero y vuelve a intentarlo. Presiona Enter...")
            return

    print("[*] Descomprimiendo y restaurando backup (mundo + packs de servidor)...")
    try:
        # Resguardar las carpetas de packs afectadas (si existen)
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

        os.makedirs(WORLD_DIR, exist_ok=True)
        with zipfile.ZipFile(selected_zip, "r") as zipf:
            for entry in world_infos:
                zipf.extract(entry, WORLD_DIR)
            for entry, (kind, folder, rel) in pack_infos:
                _extract_pack_entry(zipf, entry, os.path.join(BASE_DIR, kind, folder), rel)
        if os.path.exists(bak_dir):
            try:
                shutil.rmtree(bak_dir)
            except Exception:
                print("[AVISO] No se pudo eliminar el resguardo .bak (puedes borrarlo a mano).")
        for dest, bak in pack_baks:
            if os.path.exists(bak):
                try:
                    shutil.rmtree(bak)
                except Exception:
                    print(f"[AVISO] No se pudo eliminar el resguardo {bak} (puedes borrarlo a mano).")
        print("\n=====================================================")
        print("  [OK] MUNDO RESTAURADO EXITOSAMENTE!")
        print("=====================================================")
        print("Ya puedes iniciar el servidor con iniciar_servidor.bat")
    except Exception as e:
        print(f"[ERROR] Fallo la descompresion: {e}")
        if os.path.exists(bak_dir):
            try:
                shutil.rmtree(WORLD_DIR)
                os.rename(bak_dir, WORLD_DIR)
                print("[RECUPERADO] Se restauro el mundo anterior desde el resguardo.")
            except Exception as e2:
                print(f"[CRITICO] No se pudo recuperar el resguardo: {e2}. El mundo anterior esta en: {bak_dir}")
        for dest, bak in reversed(pack_baks):
            try:
                shutil.rmtree(dest, ignore_errors=True)
                if os.path.exists(bak):
                    os.rename(bak, dest)
                    print(f"[RECUPERADO] Se restauro la carpeta de pack: {dest}")
            except Exception as e2:
                print(f"[CRITICO] No se pudo recuperar el pack: {dest}. Resguardo en: {bak}")

    input("\nPresiona Enter para cerrar...")


if __name__ == "__main__":
    list_and_restore()
