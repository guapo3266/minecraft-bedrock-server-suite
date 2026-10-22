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
import sys

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


class _SalidaTolerante:
    """stdout/stderr que no lanza si su lector desaparecio.

    El wrapper lanzado por la GUI escribe en una tuberia cuyo unico lector es
    la GUI. Si la GUI muere (Ctrl+C, cerrada a la fuerza), cada print lanzaba
    OSError: el scheduler dejaba de iniciar backups, el worker dejaba BDS en
    "save hold" y el backup de cierre no se hacia (2026-10-21). Una vez rota la
    tuberia no vuelve: se descarta la salida y el proceso sigue trabajando.
    """

    def __init__(self, stream):
        self._stream = stream
        self._rota = False

    def write(self, text):
        if not self._rota:
            try:
                return self._stream.write(text)
            except UnicodeEncodeError:
                enc = getattr(self._stream, "encoding", None) or "utf-8"
                try:
                    return self._stream.write(text.encode(enc, "replace").decode(enc))
                except (OSError, ValueError):
                    self._rota = True
            except (OSError, ValueError):
                self._rota = True
        return len(text)

    def flush(self):
        if not self._rota:
            try:
                self._stream.flush()
            except (OSError, ValueError):
                self._rota = True

    def __getattr__(self, name):
        return getattr(self._stream, name)


def proteger_salida_consola():
    """Instala _SalidaTolerante en sys.stdout y sys.stderr (idempotente).

    La llaman los procesos que escriben a la GUI por tuberia: el wrapper y el
    worker de compresion.
    """
    for nombre in ("stdout", "stderr"):
        stream = getattr(sys, nombre)
        if stream is not None and not isinstance(stream, _SalidaTolerante):
            setattr(sys, nombre, _SalidaTolerante(stream))
