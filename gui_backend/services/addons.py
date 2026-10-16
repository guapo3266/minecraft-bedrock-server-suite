"""Servicio de inventario y diagnostico de addons (solo lectura, GUI).

Delegacion fina en el analizador compartido `addon_inventory`: la GUI no
reimplementa ninguna validacion (anti-drift CLI/GUI) y este modulo no conoce
FastAPI. El analisis recorre el arbol de la instalacion en modo lectura; no
crea, modifica ni borra archivos.
"""

import addon_inventory
from gui_backend import config


def build_addons_view(world=None, kind=None, base_dir=None):
    """Payload de inventario (equivalente al de la CLI) para la GUI.

    - `world`: acota la vista al ambito de ese mundo (packs propios,
      compartidos y de sistema, que son los que pueden resolver sus
      referencias).
    - `kind`: "behavior" o "resource".
    """
    payload = addon_inventory.analyze_addons(base_dir or config.BASE_DIR)
    return addon_inventory.filter_payload(payload, world=world, kind=kind)
