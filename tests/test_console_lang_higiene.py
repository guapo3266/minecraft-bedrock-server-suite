# -*- coding: utf-8 -*-
"""Higiene i18n de la consola: el fallback INGLES de L() debe estar en ingles.

`console_lang.L(es, en)` devuelve el segundo argumento cuando WRAPPER_LANG no
es "es" — es decir, INGLES es el idioma POR DEFECTO del wrapper y de la GUI.
Cualquier residuo de espanol dentro de ese argumento EN se imprime tal cual
ante el usuario por defecto (hallazgo real de la Ronda 8: "...exceeded 240s.
Finalizando proceso." y "[ERROR] Ya hay un backup ejecutandose; cancelling
this request.").

Esta suite recorre con AST todos los sitios L(es, en) de los modulos de
produccion (raiz del repo + gui_backend/; excluidos archived/, tests/,
tools/ y gui_frontend/) y exige del argumento EN:
  1. cero caracteres propios del espanol (acentos, ñ, ¡ ¿ º ª);
  2. cero residuos espanoles conocidos (lista negra minima y explicita).

El barrido se AUTO-VERIFICA: si dejara de encontrar sitios L() (rutas mal
resueltas, renombre de modulos), los checks pasarian vacios — un suelo de
sitios detectados convierte ese no-op silencioso en fallo visible. Solo se
inspeccionan literales (Constant / JoinedStr); los argumentos construidos
dinamicamente se ignoran porque su contenido no es visible estaticamente.
"""
import ast
import glob
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Caracteres que no aparecen en frases inglesas legitimas de consola.
ACCENTUADOS = set("áéíóúñÁÉÍÓÚÑºª¡¿")

# Residuos españoles inequívocos hallados en producción (Ronda 8); no deben volver.
RESIDUOS_ES = ("finalizando", "ejecutandose", "ejecutándose")

# Suelo muy por debajo de los ~200 sitios reales pero muy por encima de un
# barrido sordo (0-10 sitios): si baja, algo rompio la resolución de rutas.
SUELO_SITIOS_L = 100


def _modulos_produccion():
    rutas = sorted(glob.glob(os.path.join(ROOT, "*.py")))
    rutas += sorted(
        glob.glob(os.path.join(ROOT, "gui_backend", "**", "*.py"), recursive=True)
    )
    excluido = os.sep + "archived" + os.sep
    return [r for r in rutas if excluido not in r]


def _texto_literal(node):
    """Concatena las partes literales de un argumento Constant o JoinedStr."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        partes = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                partes.append(v.value)
            elif isinstance(v, ast.FormattedValue):
                partes.append("{}")
        return "".join(partes)
    return None


def _sitios_L():
    """Genera (ruta_relativa, lineno, texto_es, texto_en) por cada L(es, en)."""
    for ruta in _modulos_produccion():
        with open(ruta, encoding="utf-8") as f:
            arbol = ast.parse(f.read(), filename=ruta)
        for node in ast.walk(arbol):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", "") == "L"
                and len(node.args) >= 2
            ):
                yield (
                    os.path.relpath(ruta, ROOT),
                    node.lineno,
                    _texto_literal(node.args[0]),
                    _texto_literal(node.args[1]),
                )


def test_barrido_encuentra_sitios_reales_no_es_un_noop():
    total = sum(1 for _ in _sitios_L())
    assert total >= SUELO_SITIOS_L, (
        "el barrido solo encontro %d sitios L() (suelo %d): el scanner quedo "
        "sordo (rutas mal resueltas?) y estos tests serian un no-op"
        % (total, SUELO_SITIOS_L)
    )


def test_fallback_en_sin_caracteres_acentuados_espanoles():
    violaciones = []
    for ruta, linea, _es, en in _sitios_L():
        if en is None:
            continue
        malos = sorted({c for c in en if c in ACCENTUADOS})
        if malos:
            violaciones.append(
                "%s:%d caracteres %r en EN=%r" % (ruta, linea, "".join(malos), en[:90])
            )
    assert not violaciones, "acento espanol en fallback EN:\n" + "\n".join(violaciones)


def test_fallback_en_sin_residuo_espanol_conocido():
    violaciones = []
    for ruta, linea, _es, en in _sitios_L():
        if en is None:
            continue
        bajo = en.lower()
        for residuo in RESIDUOS_ES:
            if residuo in bajo:
                violaciones.append(
                    "%s:%d contiene %r en EN=%r" % (ruta, linea, residuo, en[:90])
                )
    assert not violaciones, "residuo espanol en fallback EN:\n" + "\n".join(violaciones)
