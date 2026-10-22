"""update_items.py — alias deprecado de update_items_v2.py.

ESTA version (1.0.5) quitaba use_animation/use_modifiers de los items y fijaba
la version 1.0.5 de los packs sin respaldo y con la ruta del mundo fija
(worlds/Bedrock level): ejecutarla despues de la v2 bajaba los packs de 1.0.6 a
1.0.5 (2026-10-21). La v2 incluye ese paso (de 1.0.4 va directo a 1.0.6) y
respalda lo que reescribe; este archivo se conserva solo como alias del CLI
(viaja en el ZIP de la Release: suite_release.TOOL_FILES).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import update_items_v2 as _v2

if __name__ == "__main__":
    sys.exit(_v2.main())
