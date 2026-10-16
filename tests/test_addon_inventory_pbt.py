# -*- coding: utf-8 -*-
"""Property-based tests del analizador de addons.

Cubren los contratos que mas facil es romper en silencio:
  1) El parser tolerante (comentarios / comas finales) es EQUIVALENTE a
     json.loads para JSON estricto: no reescribe ni pierde datos.
  2) No confunde "//" o "/*" dentro de una CADENA con un comentario.
  3) analyze_addons NUNCA lanza con un manifiesto arbitrario (texto libre) y
     siempre devuelve un payload serializable y determinista, sin escribir en
     la instalacion analizada.
  4) La normalizacion de UUID y la clasificacion de versiones son estables.
"""

import hashlib
import itertools
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hypothesis import HealthCheck, example, given, settings, strategies as st

import addon_inventory as ai


# ---------------------------------------------------------------------------
# Estrategias y utilidades locales (sin depender de otros modulos de test)
# ---------------------------------------------------------------------------

valores_json = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(max_size=20),
    lambda hijos: st.lists(hijos, max_size=3)
    | st.dictionaries(st.text(max_size=8), hijos, max_size=3),
    max_leaves=8,
)

# Texto para incrustar en la MISMA linea de un comentario //: sin caracteres de
# control (un \n cerraria el comentario y el documento dejaria de ser JSON).
texto_linea = st.text(
    alphabet=st.characters(blacklist_categories=("Cc", "Cs", "Zl", "Zp")),
    max_size=12,
)

texto_manifiesto = st.text(max_size=300)
uuids = st.uuids().map(str)
versiones = st.lists(st.integers(min_value=0, max_value=50), min_size=1, max_size=5)

# Contador para aislar cada ejemplo de Hypothesis en su propio subdirectorio.
_CONTADOR = itertools.count()


def instalar_base(base):
    """Instalacion temporal minima: server.properties + worlds/Alfa."""
    base.mkdir(parents=True, exist_ok=True)
    (base / "server.properties").write_text("level-name=Alfa\n", encoding="utf-8")
    mundo = base / "worlds" / "Alfa"
    mundo.mkdir(parents=True, exist_ok=True)
    (mundo / "level.dat").write_bytes(b"level")
    return base


def snapshot_arbol(base):
    huella = {}
    for raiz, dirs, archivos in os.walk(str(base)):
        dirs.sort()
        for nombre in sorted(archivos):
            ruta = os.path.join(raiz, nombre)
            rel = os.path.relpath(ruta, str(base)).replace(os.sep, "/")
            with open(ruta, "rb") as f:
                datos = f.read()
            st_archivo = os.stat(ruta)
            huella[rel] = (len(datos), st_archivo.st_mtime_ns,
                           hashlib.sha256(datos).hexdigest())
    return huella


KEYS_PAYLOAD = {
    "schema_version", "base_dir", "complete", "partial_reasons", "active_world",
    "supported", "scopes", "packs", "worlds", "not_analyzed", "diagnostics", "summary",
}


# ---------------------------------------------------------------------------
# 1) y 2) Parser tolerante
# ---------------------------------------------------------------------------

@given(valores_json)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_json_estricto_pasa_intacto_por_el_parser_tolerante(valor):
    texto = json.dumps(valor, ensure_ascii=False)
    cargado, motivo_tolerante, error = ai.cargar_json(texto)
    assert error is None
    assert motivo_tolerante is None  # era JSON estricto: sin aviso
    assert cargado == valor


@given(valores_json, texto_linea)
@example("Texto, } y Ejemplo, ] con // y /* */", "comentario")
@example({"clave, }": 'texto con \\" y , ]'}, "")
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_comentarios_y_comas_finales_no_alteran_las_cadenas(valor, sufijo):
    """El limpiador de comentarios respeta las cadenas: un valor que CONTENGA
    //, /* o */ debe sobrevivir tal cual (y el documento sigue siendo valido)."""
    texto = (
        "{\n"
        '  "a": %s,\n'
        "  // comentario de linea %s\n"
        '  "b": [1, 2,],\n'
        "  /* bloque */\n"
        '  "c": {"d": %s}\n'
        "}\n" % (json.dumps(valor, ensure_ascii=False), sufijo,
                 json.dumps([valor, sufijo], ensure_ascii=False))
    )
    cargado, motivo_tolerante, error = ai.cargar_json(texto)
    assert error is None
    assert motivo_tolerante is not None
    assert cargado == {"a": valor, "b": [1, 2], "c": {"d": [valor, sufijo]}}


def test_comentarios_no_fusionan_tokens_ni_aceptan_bloques_sin_cerrar():
    for texto in ('[1/* comentario */2]', '{"a": 1} /* sin cerrar'):
        cargado, motivo, error = ai.cargar_json(texto)
        assert cargado is None and motivo is None and error is not None


@given(st.text(max_size=200))
@example("null")
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_texto_arbitrario_nunca_lanza_en_el_parser(texto):
    cargado, motivo, error = ai.cargar_json(texto)
    if error is not None:
        assert cargado is None and motivo is None
        assert isinstance(error, str) and error
    else:
        assert motivo in (None, "comentarios o comas finales")
        if motivo is None:
            # null es un exito cuyo valor es None. El error decide el estado.
            assert json.dumps(cargado, sort_keys=True) == json.dumps(json.loads(texto), sort_keys=True)


# ---------------------------------------------------------------------------
# 3) Robustez, determinismo y no modificacion
# ---------------------------------------------------------------------------

@given(texto_manifiesto, texto_manifiesto)
@settings(max_examples=40, deadline=None,
          suppress_health_check=[HealthCheck.too_slow,
                                 HealthCheck.function_scoped_fixture])
def test_manifiestos_arbitrarios_no_rompen_el_inventario(tmp_path, texto_a, texto_b):
    base = instalar_base(tmp_path)
    for nombre, texto in (("A", texto_a), ("B", texto_b)):
        carpeta = base / "behavior_packs" / nombre
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "manifest.json").write_text(texto, encoding="utf-8")
    antes = snapshot_arbol(base)
    payload = ai.analyze_addons(str(base))
    despues = snapshot_arbol(base)
    assert set(payload) == KEYS_PAYLOAD
    assert json.loads(json.dumps(payload, ensure_ascii=False)) == payload
    assert len(payload["packs"]) == 2
    assert isinstance(payload["complete"], bool)
    assert antes == despues, "el analizador escribio en la instalacion"
    assert json.dumps(payload, sort_keys=True) == json.dumps(
        ai.analyze_addons(str(base)), sort_keys=True)


@given(st.lists(st.tuples(uuids, versiones), min_size=1, max_size=6))
@settings(max_examples=25, deadline=None,
          suppress_health_check=[HealthCheck.too_slow,
                                 HealthCheck.function_scoped_fixture])
def test_inventario_determinista_con_packs_aleatorios(tmp_path, combinaciones):
    """Mismo arbol => mismo payload, tambien con UUIDs repetidos."""
    # tmp_path no se reinicia entre ejemplos de Hypothesis: cada ejemplo usa su
    # propio subdirectorio para no heredar packs del anterior.
    base = instalar_base(tmp_path / ("caso%03d" % next(_CONTADOR)))
    for indice, (uuid, version) in enumerate(combinaciones):
        carpeta = base / "behavior_packs" / ("Pack%02d" % indice)
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "manifest.json").write_text(json.dumps({
            "format_version": 2,
            "header": {"name": "p%d" % indice, "description": "d", "uuid": uuid,
                       "version": version, "min_engine_version": [1, 20, 0]},
            "modules": [{"type": "data", "uuid": uuid, "version": version}],
        }), encoding="utf-8")
    antes = snapshot_arbol(base)
    primero = ai.analyze_addons(str(base))
    segundo = ai.analyze_addons(str(base))
    assert json.dumps(primero, sort_keys=True) == json.dumps(segundo, sort_keys=True)
    assert snapshot_arbol(base) == antes
    assert len(primero["packs"]) == len(combinaciones)


# ---------------------------------------------------------------------------
# 4) UUID y versiones
# ---------------------------------------------------------------------------

@given(st.uuids())
@settings(max_examples=200)
def test_uuid_valido_y_normalizado(uuid):
    texto = str(uuid)
    assert ai.uuid_valido(texto)
    assert ai.uuid_valido(texto.upper())
    assert ai.normalizar_uuid(texto.upper()) == texto.lower()
    assert ai.normalizar_uuid("  %s  " % texto) == texto.lower()


@given(st.text(max_size=40))
@settings(max_examples=200)
def test_texto_arbitrario_no_es_un_uuid_salvo_formato_canonico(texto):
    if ai.uuid_valido(texto):
        normalizado = ai.normalizar_uuid(texto)
        assert ai.uuid_valido(normalizado)
        assert normalizado == texto.strip().lower()


@given(st.lists(st.integers(min_value=0, max_value=999), min_size=3, max_size=3))
@settings(max_examples=200)
def test_version_de_tres_componentes_es_comparable(componentes):
    estado, comps = ai.clasificar_version(componentes)
    assert estado == "ok"
    assert comps == tuple(componentes)
    assert ai.version_comparable(componentes) == tuple(componentes)


@given(st.lists(st.integers(min_value=0, max_value=99), min_size=1, max_size=6))
@settings(max_examples=200)
def test_componentes_sueltos_nunca_son_invalidos(componentes):
    estado, comps = ai.clasificar_version(componentes)
    assert estado in ("ok", "formato")
    assert len(comps) == 3


@given(valores_json)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_clasificar_version_nunca_lanza(valor):
    estado, comps = ai.clasificar_version(valor)
    assert estado in ("ok", "formato", "texto", "invalido")
    if estado == "invalido":
        assert comps is None
    texto = ai.texto_version(valor)
    assert isinstance(texto, str) and texto
