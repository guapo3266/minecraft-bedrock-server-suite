# -*- coding: utf-8 -*-
"""console_lang.py — idioma de los mensajes de la consola (backend).

La variable de entorno WRAPPER_LANG (proceso-global) decide el idioma de los
mensajes que generan el wrapper, la GUI y auto_backup:
  - "es"  -> español
  - ausente o cualquier otro valor -> inglés (default)

La GUI la fija cuando el frontend anuncia su idioma (WebSocket set_lang / query
param lang) y el wrapper la hereda por env al ser lanzado. Los tests unitarios
(que no lanzan el frontend) ven el default: inglés.
"""

import os

# Idiomas aceptados por el frontend (i18n.jsx)
VALID_LANGS = ("es", "en")


def L(es, en):
    """Devuelve el mensaje en el idioma activo.

    Los argumentos ya son cadenas evaluadas por el llamador (f-strings con sus
    variables sustituidas); aqui solo se elige uno de los dos.
    """
    return es if os.environ.get("WRAPPER_LANG") == "es" else en


def set_lang(lang):
    """Fija el idioma de la consola si es valido. Devuelve True si cambio."""
    if lang in VALID_LANGS:
        os.environ["WRAPPER_LANG"] = lang
        return True
    return False
