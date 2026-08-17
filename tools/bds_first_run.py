# -*- coding: utf-8 -*-
"""Primer arranque por consola: instala BDS si falta bedrock_server.exe.

Lo ejecuta iniciar_servidor.bat antes de server_wrapper.py. Si el ejecutable
ya esta presente no hace nada (exit 0). Si falta, pregunta [S/n] (Enter = Si)
y reutiliza el pipeline de descarga de la GUI (bds_update._download_and_install_bds)
con los mensajes de progreso en la consola. Si tampoco existe server.properties,
copia el example antes de salir.

Exit codes: 0 listo (exe presente o instalado), 1 error operativo,
2 el usuario respondio que no.
"""
import os
import shutil
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from console_lang import L
from gui_backend import config
from gui_backend.services import bds_update


def _console_log(msg, _type="system"):
    print(msg)


def _copy_properties_if_missing():
    if os.path.exists(config.PROPS_PATH):
        return
    example = os.path.join(config.BASE_DIR, "server.properties.example")
    if not os.path.exists(example):
        return
    try:
        shutil.copyfile(example, config.PROPS_PATH)
        print(L("[Setup] No habia server.properties: se copio del example.",
                "[Setup] server.properties was missing: copied from the example."))
    except Exception as e:
        print(L("[Setup] No se pudo copiar server.properties.example: %s" % e,
                "[Setup] Could not copy server.properties.example: %s" % e))


def main():
    if os.path.exists(config.SERVER_EXE):
        return 0

    print("")
    print(L("[!] No se encontro bedrock_server.exe en la carpeta.",
            "[!] bedrock_server.exe was not found in this folder."))
    try:
        answer = input(L("?Deseas descargar e instalar la ultima version oficial de Mojang? [S/n]: ",
                         "Do you want to download and install the latest official Mojang version? [S/n]: "))
    except (EOFError, KeyboardInterrupt):
        return 2
    answer = answer.strip().lower()
    if answer not in ("", "s", "si", "sí", "y", "yes"):
        print(L("Ok, sin instalar BDS. Descargalo a mano (o usa iniciar_gui.bat) y vuelve a intentarlo.",
                "OK, BDS not installed. Download it manually (or use iniciar_gui.bat) and try again."))
        return 2

    print(L("[Setup] Descargando BDS desde Mojang (puede tardar un par de minutos)...",
            "[Setup] Downloading BDS from Mojang (may take a couple of minutes)..."))
    try:
        ok, version = bds_update._download_and_install_bds(tag="[Setup]", log_fn=_console_log)
    except Exception as e:
        print(L("[Setup] Error durante la descarga o instalacion: %s" % e,
                "[Setup] Error during download or installation: %s" % e))
        return 1
    if not ok:
        print(L("[Setup] No se pudo instalar BDS (sin red o descarga invalida). Revisa los mensajes anteriores.",
                "[Setup] BDS could not be installed (no network or invalid download). Check the messages above."))
        return 1

    print(L("[Setup] BDS instalado (v%s)." % version if version else "[Setup] BDS instalado.",
            "[Setup] BDS installed (v%s)." % version if version else "[Setup] BDS installed."))
    _copy_properties_if_missing()
    return 0


if __name__ == "__main__":
    sys.exit(main())
