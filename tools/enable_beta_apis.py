"""enable_beta_apis.py — alias deprecado de enable_beta_apis_v2.py.

ESTA version (v1) destruia el level.dat: amulet_nbt.load() con sus defaults
(big-endian + gzip) interpreta la cabecera little-endian de 8 bytes de
Bedrock como NBT comprimido y save_to() reescribe el archivo como un blob
gzip diminuto que solo conserva 'experiments' — con mensaje de exito y el
mundo inservible. Toda la logica correcta (preserva cabecera, little-endian
y datos trailing) vive en enable_beta_apis_v2.py; este archivo se conserva
solo como alias del CLI.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import enable_beta_apis_v2 as _v2

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python enable_beta_apis.py <ruta_a_level.dat>")
        sys.exit(1)
    _v2.enable_experiments(sys.argv[1])
