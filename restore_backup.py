import os
import glob
import zipfile
import shutil
import datetime

WORLD_DIR = r"C:\Users\guapo\Downloads\Servidores_Minecraft\Servidor de Guapo\worlds\Bedrock level"
BACKUP_DIR = r"C:\Users\guapo\Downloads\Backups_Minecraft\auto_backups"


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

    backups = glob.glob(os.path.join(BACKUP_DIR, "auto_backup_*.zip"))
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

    bak_dir = WORLD_DIR + ".bak"
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

    os.makedirs(WORLD_DIR, exist_ok=True)

    print("[*] Descomprimiendo y restaurando backup...")
    try:
        with zipfile.ZipFile(selected_zip, "r") as zipf:
            for entry in zipf.infolist():
                if not _is_safe_zip_entry(entry.filename):
                    raise ValueError(f"Entrada insegura: {entry.filename}")
                zipf.extract(entry, WORLD_DIR)
        if os.path.exists(bak_dir):
            try:
                shutil.rmtree(bak_dir)
            except Exception:
                print("[AVISO] No se pudo eliminar el resguardo .bak (puedes borrarlo a mano).")
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

    input("\nPresiona Enter para cerrar...")


if __name__ == "__main__":
    list_and_restore()
