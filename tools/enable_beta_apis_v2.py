# -*- coding: utf-8 -*-
"""Habilita los experimentos de APIs beta en el level.dat de un mundo.

Lee la cabecera (version + longitud del payload NBT), inyecta los flags de
experiments con amulet_nbt y reescribe el archivo con resguardo previo y
escritura atomica. Uso: python tools/enable_beta_apis_v2.py <ruta_a_level.dat>
"""
try:
    import amulet_nbt
except ImportError:
    amulet_nbt = None
import io
import shutil
import struct
import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from console_lang import L

def _podar_respaldos(original, conservar, max_respaldos=3):
    """Deja los max_respaldos .respaldo_* mas recientes de `original`.

    Sin poda se acumulan y cada backup del mundo los empaqueta como copias del
    level.dat. La poda es POR archivo y nunca toca `conservar` (el respaldo
    recien creado): antes recorria todo worlds/ por fecha y el respaldo nuevo
    heredaba con copy2 la fecha vieja del level.dat; con tres respaldos
    recientes de otro mundo, se borraba el que protegia el archivo que se iba
    a reescribir (2026-10-21).
    """
    carpeta = os.path.dirname(original)
    prefijo = os.path.basename(original) + ".respaldo_"
    respaldos = []
    try:
        nombres = os.listdir(carpeta)
    except OSError:
        return
    for nombre in nombres:
        ruta = os.path.join(carpeta, nombre)
        if not nombre.startswith(prefijo) or os.path.normcase(ruta) == os.path.normcase(conservar):
            continue
        try:
            respaldos.append((os.path.getmtime(ruta), ruta))
        except OSError:
            continue
    respaldos.sort(reverse=True)
    for _mtime, viejo in respaldos[max_respaldos - 1:]:
        try:
            os.remove(viejo)
        except OSError:
            pass

def enable_experiments(file_path):
    if amulet_nbt is None:
        print(L("[ERROR] Falta 'amulet_nbt'. Instálalo con: pip install amulet-nbt",
                "[ERROR] 'amulet_nbt' is not installed. Install it with: pip install amulet-nbt"))
        return
    if not os.path.exists(file_path):
        print(L(f"[AVISO] No se encontró el archivo: {file_path}",
                f"[WARNING] File not found: {file_path}"))
        return

    with open(file_path, 'rb') as f:
        data = f.read()

    # Cabecera de level.dat: version (uint32) + longitud del payload NBT (uint32).
    if len(data) < 8:
        print(L(f"[ERROR] {file_path} no tiene cabecera de level.dat (archivo demasiado corto); no se modifica.",
                f"[ERROR] {file_path} has no level.dat header (file too short); left unchanged."))
        return
    try:
        version, length = struct.unpack('<II', data[:8])
    except struct.error as e:
        print(L(f"[ERROR] Cabecera ilegible en {file_path} ({e}); no se modifica.",
                f"[ERROR] Unreadable header in {file_path} ({e}); left unchanged."))
        return
    if 8 + length > len(data):
        print(L(f"[ERROR] Cabecera inconsistente en {file_path} (declara {length} bytes de NBT y hay {len(data) - 8}); no se modifica.",
                f"[ERROR] Inconsistent header in {file_path} (declares {length} NBT bytes but only {len(data) - 8} present); left unchanged."))
        return
    print(L(f"Archivo: {file_path} | Versión: {version} | Longitud: {length}",
            f"File: {file_path} | Version: {version} | Length: {length}"))

    # Load NBT payload
    payload_bytes = data[8:8+length]
    f_nbt = io.BytesIO(payload_bytes)
    nbt_data = amulet_nbt.load(f_nbt, compressed=False, little_endian=True)

    # Modify NBT experiments
    experiments = nbt_data.compound.get('experiments')
    if experiments is None:
        experiments = amulet_nbt.TAG_Compound()
        nbt_data.compound['experiments'] = experiments
        print(L("Creado el compound experiments.", "Created experiments compound."))

    experiments['gametest'] = amulet_nbt.TAG_Byte(1)
    experiments['data_driven_items'] = amulet_nbt.TAG_Byte(1)
    experiments['experimental_custom_ui'] = amulet_nbt.TAG_Byte(1)
    experiments['experiments_ever_used'] = amulet_nbt.TAG_Byte(1)
    experiments['saved_with_toggled_experiments'] = amulet_nbt.TAG_Byte(1)

    print(L("Experiments inyectados.", "Injected experiments."))

    # Save NBT payload back to bytes
    f_out = io.BytesIO()
    nbt_data.save_to(f_out, compressed=False, little_endian=True)
    new_payload = f_out.getvalue()

    # Reconstruct file with header
    new_header = struct.pack('<II', version, len(new_payload))
    new_data = new_header + new_payload

    # If there was a trailing payload, append it
    trailing_offset = 8 + length
    if len(data) > trailing_offset:
        new_data += data[trailing_offset:]
        print(L(f"Añadidos datos finales de {len(data) - trailing_offset} bytes.",
                f"Appended trailing data of size: {len(data) - trailing_offset}"))

    # Resguardo previo: la v1 destruyo un level.dat real y el round-trip de
    # amulet_nbt puede alterar datos que no sabemos regenerar. Copia (no
    # move): el original sigue en su sitio y el resguardo es solo evidencia.
    # copyfile y no copy2: el resguardo lleva la fecha de su creacion, la que
    # ordena la poda. El sufijo evita deliberadamente el patron bak del
    # recuperador: el recuperador de restauraciones interrumpidas renombra
    # cualquier *.bak_* de worlds/ como huerfano en el arranque del wrapper.
    backup_path = file_path + ".respaldo_" + os.urandom(4).hex()
    try:
        shutil.copyfile(file_path, backup_path)
        print(L(f"Resguardo previo guardado como: {backup_path}",
                f"Previous backup saved as: {backup_path}"))
    except OSError as e:
        print(L(f"[ERROR] No se pudo crear el resguardo previo ({e}); se aborta sin tocar el level.dat.",
                f"[ERROR] Could not create the previous backup ({e}); aborting without touching level.dat."))
        return

    # Los resguardos no se pueden dejar crecer: los siguientes backups del
    # mundo los empaquetarian como copias del level.dat.
    _podar_respaldos(file_path, backup_path)

    # Escritura atomica: open('wb') in-place trunca el original y recien
    # despues escribe; un corte de luz/Ctrl+C/antivirus a mitad dejaba un
    # level.dat truncado sin recuperacion. Con tmp + os.replace el original
    # solo se sustituye cuando el nuevo esta completo en disco.
    tmp_path = file_path + ".tmp_" + os.urandom(4).hex()
    try:
        with open(tmp_path, "wb") as f:
            f.write(new_data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, file_path)
    except PermissionError:
        print(L(f"[ERROR] No se pudo reemplazar {file_path}: lo tiene abierto BDS (PermissionError). "
                "Detén el servidor (stop) y vuelve a ejecutar el script.",
                f"[ERROR] Could not replace {file_path}: BDS has it open (PermissionError). "
                "Stop the server (stop) and run the script again."))
        return
    except OSError as e:
        print(L(f"[ERROR] No se pudo escribir {file_path} ({e}); el original queda intacto.",
                f"[ERROR] Could not write {file_path} ({e}); the original is unchanged."))
        return
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    print(L(f"Guardado {file_path} correctamente.", f"Saved {file_path} successfully."))

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(L("Uso: python enable_beta_apis_v2.py <ruta_a_level.dat>",
                "Usage: python enable_beta_apis_v2.py <path_to_level.dat>"))
        sys.exit(1)
    enable_experiments(sys.argv[1])
