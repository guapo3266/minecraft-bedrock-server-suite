import os
import sys
import glob
import zipfile
import shutil
import datetime

WORLD_DIR = r"C:\Users\guapo\Downloads\Servidores_Minecraft\Servidor de Guapo\worlds\Bedrock level"
BACKUP_DIR = r"C:\Users\guapo\Downloads\Backups_Minecraft\auto_backups"

def list_and_restore():
    os.system("cls" if os.name == "nt" else "clear")
    print("=" * 60)
    print("      RESTAURAR BACKUP AUTOMÁTICO (ESTILO REALMS)")
    print("=" * 60)
    print()

    if not os.path.exists(BACKUP_DIR):
        print(f"[ERROR] No se encontro la carpeta de backups: {BACKUP_DIR}")
        input("\nPresiona Enter para salir...")
        return

    backups = glob.glob(os.path.join(BACKUP_DIR, "auto_backup_*.zip"))
    backups.sort(key=os.path.getmtime, reverse=True) # Más reciente primero

    if not backups:
        print("No hay copias de seguridad automáticas disponibles.")
        input("\nPresiona Enter para salir...")
        return

    print("Backups disponibles (del más reciente al más antiguo):\n")
    for idx, bpath in enumerate(backups, 1):
        fname = os.path.basename(bpath)
        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(bpath)).strftime("%d/%m/%Y %H:%M:%S")
        size_mb = os.path.getsize(bpath) / (1024 * 1024)
        print(f"  [{idx}] -> Fecha: {mtime} | Archivo: {fname} ({size_mb:.1f} MB)")

    print("\n" + "-" * 60)
    print("  [0] Cancelar y salir")
    print("-" * 60)
    
    choice = input("\nElige el número del backup que deseas restaurar (ejemplo: 1): ").strip()
    
    if choice == "0" or not choice:
        print("Operación cancelada.")
        return

    try:
        idx_chosen = int(choice) - 1
        if idx_chosen < 0 or idx_chosen >= len(backups):
            print("[ERROR] Número invalido.")
            input("\nPresiona Enter para salir...")
            return
        selected_zip = backups[idx_chosen]
    except ValueError:
        print("[ERROR] Por favor ingresa un numero valido.")
        input("\nPresiona Enter para salir...")
        return

    print("\n" + "=" * 60)
    print(f"  ATENCIÓN: Se restaurará el backup:")
    print(f"  {os.path.basename(selected_zip)}")
    print("  El mundo actual será reemplazado con este punto de restauración.")
    print("=" * 60)
    
    confirm = input("\n¿Estás seguro? Escribe 'SI' para confirmar: ").strip().upper()
    if confirm != "SI":
        print("\nOperación cancelada.")
        input("\nPresiona Enter para salir...")
        return

    print("\n[*] Limpiando mundo actual...")
    if os.path.exists(WORLD_DIR):
        try:
            shutil.rmtree(WORLD_DIR)
        except Exception as e:
            print(f"[ERROR] No se pudo borrar el mundo actual. ¿Está el servidor encendido?: {e}")
            input("\nApaga el servidor primero y vuelve a intentarlo. Presiona Enter...")
            return

    os.makedirs(WORLD_DIR, exist_ok=True)

    print(f"[*] Descomprimiendo y restaurando backup...")
    try:
        with zipfile.ZipFile(selected_zip, 'r') as zipf:
            zipf.extractall(WORLD_DIR)
        print("\n=====================================================")
        print("  [OK] ¡MUNDO RESTAURADO EXITOSAMENTE!")
        print("=====================================================")
        print("Ya puedes iniciar el servidor con iniciar_servidor.bat")
    except Exception as e:
        print(f"[ERROR] Falló la descompresión: {e}")

    input("\nPresiona Enter para cerrar...")

if __name__ == "__main__":
    list_and_restore()
