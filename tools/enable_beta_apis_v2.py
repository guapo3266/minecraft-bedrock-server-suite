try:
    import amulet_nbt
except ImportError:
    amulet_nbt = None
import io
import struct
import sys
import os

def enable_experiments(file_path):
    if amulet_nbt is None:
        print("Error: 'amulet_nbt' no está instalado. Instálalo con: pip install amulet-nbt")
        return
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return
        
    with open(file_path, 'rb') as f:
        data = f.read()
        
    # Unpack version and length
    version, length = struct.unpack('<II', data[:8])
    print(f"File: {file_path} | Version: {version} | Length: {length}")
    
    # Load NBT payload
    payload_bytes = data[8:8+length]
    f_nbt = io.BytesIO(payload_bytes)
    nbt_data = amulet_nbt.load(f_nbt, compressed=False, little_endian=True)
    
    # Modify NBT experiments
    experiments = nbt_data.compound.get('experiments')
    if experiments is None:
        experiments = amulet_nbt.TAG_Compound()
        nbt_data.compound['experiments'] = experiments
        print("Created experiments compound.")
        
    experiments['gametest'] = amulet_nbt.TAG_Byte(1)
    experiments['data_driven_items'] = amulet_nbt.TAG_Byte(1)
    experiments['experimental_custom_ui'] = amulet_nbt.TAG_Byte(1)
    experiments['experiments_ever_used'] = amulet_nbt.TAG_Byte(1)
    experiments['saved_with_toggled_experiments'] = amulet_nbt.TAG_Byte(1)
    
    print("Injected experiments.")
    
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
        print(f"Appended trailing data of size: {len(data) - trailing_offset}")
        
    # Escritura atomica: open('wb') in-place trunca el original y recien
    # despues escribe; un corte de luz/Ctrl+C/antivirus a mitad dejaba un
    # level.dat truncado sin recuperacion. Con tmp + os.replace el original
    # solo se sustituye cuando el nuevo esta completo en disco.
    tmp_path = file_path + ".tmp_" + os.urandom(4).hex()
    with open(tmp_path, "wb") as f:
        f.write(new_data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, file_path)

    print(f"Saved {file_path} successfully.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python enable_beta_apis_v2.py <ruta_a_level.dat>")
        sys.exit(1)
    enable_experiments(sys.argv[1])
