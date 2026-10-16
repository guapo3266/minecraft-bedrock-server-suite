# -*- coding: utf-8 -*-
"""Anti-drift entre el catalogo de diagnosticos, la documentacion y la CLI.

La gravedad (y la fuente que la respalda) de cada codigo no puede quedar solo en
la cabeza de quien lo escribio: este test compara `addon_inventory.CATALOGO` con
la tabla de `docs/INFORME_ADDONS.md`, con los codigos de salida declarados y con
los idiomas del catalogo.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import addon_inventory as ai
import addon_inventory_cli as cli

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(RAIZ, "docs", "INFORME_ADDONS.md")
LOGICA_JS = os.path.join(RAIZ, "gui_frontend", "src", "addonsLogic.js")

# Estados de resolucion que el analizador escribe en el payload. Se leen del
# TEXTO fuente con prefijos acotados (`resolucion[...]`, `ref[...]`) para no
# confundirlos con los estados de un pack (`pack[`status`]`) ni con los de los
# archivos de referencias de un mundo (`estado[...]`), que son otra cosa.
_RE_ESTADO_ASIGNADO = re.compile(r'(?:resolucion|ref)\["status"\] = "([a-z_]+)"')
_RE_ESTADO_INICIAL = re.compile(r'resolucion = \{[^}]*"status": "([a-z_]+)"')

# Fuentes aceptadas: las obligatorias (F1..F5), el how-to de BDS y los puntos
# NO DETERMINADO del informe de investigacion (N1..N12).
FUENTES_VALIDAS = {"F1", "F2", "F3", "F4", "F5", "BDS-howto"} | {"N%d" % i for i in range(1, 13)}

_RE_FILA = re.compile(
    r"^\|\s*`([A-Z0-9_]+)`\s*\|\s*(error|aviso|info)\s*\|\s*([A-Za-z0-9\-]+)\s*\|"
    r"\s*(sí|si|no)\s*\|\s*(sí|si|no)\s*\|"
)
_RE_SALIDA = re.compile(r"^\|\s*`(\d)`\s*\|", re.MULTILINE)


@pytest.fixture(scope="module")
def documento():
    with open(DOC, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def tabla_documento(documento):
    filas = {}
    for linea in documento.splitlines():
        coincidencia = _RE_FILA.match(linea)
        if coincidencia:
            code, severidad, fuente, parcial, determinado = coincidencia.groups()
            filas[code] = {
                "severity": severidad,
                "source": fuente,
                "partial": parcial != "no",
                "determined": determinado != "no",
            }
    assert len(filas) > 50, "parseo sospechoso de la tabla de codigos"
    return filas


def test_todos_los_codigos_del_catalogo_estan_documentados(tabla_documento):
    faltan = sorted(set(ai.CATALOGO) - set(tabla_documento))
    assert not faltan, "codigos sin documentar en docs/INFORME_ADDONS.md: %s" % faltan


def test_no_hay_codigos_documentados_que_no_existan(tabla_documento):
    sobran = sorted(set(tabla_documento) - set(ai.CATALOGO))
    assert not sobran, "codigos documentados que ya no existen: %s" % sobran


def test_gravedad_fuente_y_banderas_coinciden(tabla_documento):
    discrepancias = {}
    for code, spec in ai.CATALOGO.items():
        documentado = tabla_documento.get(code)
        if documentado is None:
            continue
        esperado = {
            "severity": spec["severity"],
            "source": spec["source"],
            "partial": spec["partial"],
            "determined": spec["determined"],
        }
        if documentado != esperado:
            discrepancias[code] = {"documento": documentado, "catalogo": esperado}
    assert discrepancias == {}


def test_codigos_de_salida_documentados_coinciden_con_la_cli(documento):
    declarados = {int(m.group(1)) for m in _RE_SALIDA.finditer(documento)}
    assert declarados == {
        cli.EXIT_OK, cli.EXIT_HALLAZGOS, cli.EXIT_PARCIAL, cli.EXIT_USO, cli.EXIT_INTERNO,
    }, declarados


def test_catalogo_higiene():
    for code, spec in ai.CATALOGO.items():
        assert code == code.upper(), code
        assert spec["severity"] in ai.SEVERIDADES, code
        assert spec["source"] in FUENTES_VALIDAS, (code, spec["source"])
        assert isinstance(spec["partial"], bool) and isinstance(spec["determined"], bool)
        assert spec["es"].strip() and spec["en"].strip(), code
        # Un inventario parcial solo puede venir de un error o de un aviso.
        if spec["partial"]:
            assert spec["severity"] in ("error", "aviso"), code


def test_placeholders_simetricos_entre_idiomas():
    patron = re.compile(r"\{(\w+)\}")
    asimetricos = {
        code: {"es": sorted(patron.findall(spec["es"])),
               "en": sorted(patron.findall(spec["en"]))}
        for code, spec in ai.CATALOGO.items()
        if sorted(patron.findall(spec["es"])) != sorted(patron.findall(spec["en"]))
    }
    assert asimetricos == {}


def test_catalogo_publico_ordenado_y_completo():
    publico = ai.catalogo_publico()
    assert [e["code"] for e in publico] == sorted(ai.CATALOGO)
    assert len(publico) == len(ai.CATALOGO)
    for entrada in publico:
        assert set(entrada) == {"code", "severity", "source", "partial", "determined",
                                "message_es", "message_en"}


def test_alcance_declarado_coincide_con_el_payload(documento):
    """Las ubicaciones y exclusiones declaradas en el payload deben estar en el
    informe: si se amplia el alcance sin documentarlo, este test falla."""
    payload = ai.analyze_addons(os.path.join(RAIZ, "tests"))
    for ubicacion in payload["supported"]["locations"]:
        raiz = ubicacion.split("/")[0]
        assert raiz in documento, "ubicacion sin documentar: %s" % ubicacion
    for excluida in payload["supported"]["excluded_locations"]:
        assert excluida in documento, "exclusion sin documentar: %s" % excluida
    for version in payload["supported"]["manifest_format_versions"]:
        assert "format_version" in documento and str(version) in documento


def test_el_informe_declara_los_limites_no_verificables(documento):
    """G1..G8 (lo que no se puede comprobar con metadatos) deben seguir listados."""
    for marca in ("G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8"):
        assert "| %s |" % marca in documento, "falta el limite %s" % marca


def test_estados_de_resolucion_tienen_clave_en_la_gui():
    """Anti-drift GUI <-> analizador: cada estado de resolucion se traduce.

    Regresion de la revision en navegador (2026-10-06): el analizador emitia
    `version_mismatch` y la GUI no tenia clave para ese estado, de modo que
    pintaba "pendiente" (una afirmacion falsa sobre el enlace). Este test ata el
    mapa de la GUI a los literales del analizador.
    """
    with open(os.path.join(RAIZ, "addon_inventory.py"), encoding="utf-8") as f:
        fuente = f.read()
    estados = set(_RE_ESTADO_ASIGNADO.findall(fuente))
    estados |= set(_RE_ESTADO_INICIAL.findall(fuente))
    assert len(estados) >= 8, "parseo sospechoso de los estados: %s" % sorted(estados)

    with open(LOGICA_JS, encoding="utf-8") as f:
        logica = f.read()
    bloque = logica.split("CLAVES_RESOLUCION = {", 1)[1].split("};", 1)[0]
    claves = set(re.findall(r"^\s*([a-z_]+):", bloque, re.MULTILINE))
    faltan = sorted(estados - claves)
    assert not faltan, (
        "estados de resolucion sin clave i18n en la GUI (addonsLogic.js): %s" % faltan
    )
