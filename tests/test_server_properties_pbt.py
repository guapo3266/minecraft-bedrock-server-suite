# -*- coding: utf-8 -*-
"""PBT de server_properties.read_value.

Propiedades: con ruido arbitrario de lineas (comentarios/blancos/sin '=')
alrededor de `clave = valor`, el lector devuelve SIEMPRE el valor; y con texto
arbitrario nunca lanza.
"""
import os
import sys

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server_properties as sp

# Lineas de ruido que no contienen '=' ni la clave (sin surrogates: no se
# pueden escribir en UTF-8).
_ruido = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="=\n\r"),
    max_size=30,
)


@given(
    st.lists(_ruido, max_size=8),
    st.text(
        alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\n\r"),
        max_size=20,
    ),
    st.text(max_size=20),
)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
def test_read_value_encuentra_el_valor_con_ruido(tmp_path, lineas, valor, espacios):
    """`clave = valor` (con cualquier espacio alrededor) se encuentra aunque
    haya ruido alrededor; la clave no puede contener '=' ni saltos."""
    import re

    # Clave valida: solo alfanumericos/._- (evita que empiece con # o ;, que
    # serian comentario, y surrogates).
    clave = re.sub(r"[^\w.-]", "x", espacios) or "k"
    contenido = "\n".join(lineas + [f"{clave} = {valor}"] + lineas)
    destino = tmp_path / "server.properties"
    destino.write_text(contenido, encoding="utf-8")
    # El lector normaliza con strip(): los espacios de los extremos no
    # forman parte del valor en un .properties.
    assert sp.read_value(str(destino), clave) == valor.strip()


@given(st.text(max_size=300))
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
def test_read_value_nunca_lanza(tmp_path, texto):
    destino = tmp_path / "server.properties"
    destino.write_text(texto, encoding="utf-8")
    resultado = sp.read_value(str(destino), "level-name")
    assert resultado is None or isinstance(resultado, str)
