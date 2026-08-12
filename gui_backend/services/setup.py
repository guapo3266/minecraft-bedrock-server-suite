"""Detección del estado de instalación (asistente de primer arranque).

El marcador se escribe solo al completar el wizard. Una instalacion que ya
arranco alguna vez (BDS presente + mundo con level.dat) se considera
configurada aunque no tenga marcador: asi el wizard NO molesta a
instalaciones existentes tras una sincronizacion.
"""

import os

from gui_backend import config


def _is_install_used():
    """True si la instalacion ya arranco al menos una vez: existe bedrock_server.exe
    y worlds/ contiene al menos un mundo con level.dat (el mundo nace en el
    primer boot; un BDS recien extraido no lo tiene)."""
    worlds_dir = os.path.join(config.BASE_DIR, "worlds")
    if not os.path.isdir(worlds_dir):
        return False
    for name in os.listdir(worlds_dir):
        if os.path.isfile(os.path.join(worlds_dir, name, "level.dat")):
            return True
    return False


def _setup_required():
    """True solo para instalaciones NUEVAS: sin marcador y sin uso previo."""
    if os.path.exists(config.SETUP_MARKER):
        return False
    if os.path.exists(config.SERVER_EXE) and _is_install_used():
        return False
    return True
