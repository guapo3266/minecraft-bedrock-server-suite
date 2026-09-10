"""Guardas de la GUI clasica (`web/`).

La GUI React escapa por defecto; la clasica construye DOM a mano. Este modulo
fija que los datos que vienen del servidor (nombres de jugadores, nombres de
archivos de backup) no se interpolen dentro de plantillas de innerHTML: un
nombre con markup se interpretaria como HTML (inyeccion).
"""

import os
import re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_web_clasico_no_interpola_datos_en_innerhtml():
    with open(os.path.join(BASE_DIR, "web", "app.js"), encoding="utf-8") as f:
        src = f.read()
    plantillas = re.findall(r"innerHTML\s*=\s*`([^`]*)`", src, re.S)
    con_interpolacion = [t for t in plantillas if "${" in t]
    assert not con_interpolacion, (
        "innerHTML con interpolacion en web/app.js (usar textContent para "
        "datos del servidor): %r" % con_interpolacion[:1]
    )
