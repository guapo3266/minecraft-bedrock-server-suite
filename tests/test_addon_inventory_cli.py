# -*- coding: utf-8 -*-
"""Tests de la CLI de inventario de addons (addon_inventory_cli.py).

Se ejecuta la CLI como PROCESO real (sys.executable) para verificar de verdad
los codigos de salida y la salida JSON/legible, sobre instalaciones temporales.
La instalacion analizada se fotografia antes y despues: la CLI es de solo
lectura.
"""

import json
import os
import subprocess
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import addon_inventory  # noqa: E402
import addon_inventory_cli as cli  # noqa: E402

UUID_A = "aaaaaaaa-1111-4111-8111-111111111111"
UUID_B = "bbbbbbbb-2222-4222-8222-222222222222"
UUID_FANTASMA = "00000000-9999-4999-8999-999999999999"


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _manifiesto(uuid, version=(1, 0, 0), nombre="Pack", deps=None, modulos=None):
    return {
        "format_version": 2,
        "header": {"name": nombre, "description": "descripcion", "uuid": uuid,
                   "version": list(version), "min_engine_version": [1, 20, 0]},
        "modules": modulos or [{"type": "data", "uuid": uuid, "version": list(version)}],
        **({"dependencies": deps} if deps else {}),
    }


def _pack(base, rel, datos):
    carpeta = base / rel
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "manifest.json").write_text(json.dumps(datos), encoding="utf-8")


def _refs(base, mundo, behavior=None):
    carpeta = base / "worlds" / mundo
    carpeta.mkdir(parents=True, exist_ok=True)
    if behavior is not None:
        (carpeta / "world_behavior_packs.json").write_text(
            json.dumps(behavior), encoding="utf-8")


def instalacion_limpia(tmp_path):
    (tmp_path / "server.properties").write_text("level-name=Alfa\n", encoding="utf-8")
    (tmp_path / "worlds" / "Alfa").mkdir(parents=True)
    (tmp_path / "worlds" / "Alfa" / "level.dat").write_bytes(b"x")
    _pack(tmp_path, "behavior_packs/Sano", _manifiesto(UUID_A, nombre="Sano"))
    _refs(tmp_path, "Alfa", [{"pack_id": UUID_A, "version": [1, 0, 0]}])
    return tmp_path


def instalacion_con_hallazgos(tmp_path):
    instalacion_limpia(tmp_path)
    _refs(tmp_path, "Alfa", [{"pack_id": UUID_FANTASMA, "version": [1, 0, 0]}])
    _pack(tmp_path, "behavior_packs/Scripts", _manifiesto(
        UUID_B, deps=[{"module_name": "@minecraft/server", "version": "1.0.0-beta"}]))
    return tmp_path


def instalacion_parcial(tmp_path):
    instalacion_limpia(tmp_path)
    carpeta = tmp_path / "behavior_packs" / "Roto"
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "manifest.json").write_text("{ roto", encoding="utf-8")
    return tmp_path


def snapshot(base):
    huella = {}
    for raiz, _dirs, archivos in os.walk(str(base)):
        for nombre in archivos:
            ruta = os.path.join(raiz, nombre)
            st = os.stat(ruta)
            huella[os.path.relpath(ruta, str(base))] = (st.st_size, st.st_mtime_ns)
    return huella


def ejecutar(*args):
    """Ejecuta la CLI como proceso y devuelve (codigo, stdout, stderr)."""
    resultado = subprocess.run(
        [sys.executable, os.path.join(RAIZ, "addon_inventory_cli.py"), *args],
        cwd=RAIZ, capture_output=True, text=True, encoding="utf-8",
    )
    return resultado.returncode, resultado.stdout, resultado.stderr


# ---------------------------------------------------------------------------
# Codigos de salida documentados
# ---------------------------------------------------------------------------

def test_salida_limpia_devuelve_0(tmp_path):
    base = instalacion_limpia(tmp_path)
    codigo, salida, _err = ejecutar("--root", str(base), "--no-color", "--lang", "es")
    assert codigo == cli.EXIT_OK == 0
    assert "Sano" in salida
    assert "COMPLETO" in salida


def test_resumen_legible_corresponde_a_la_vista_filtrada(tmp_path):
    base = instalacion_limpia(tmp_path)
    datos = _manifiesto(UUID_B, nombre="Recursos")
    datos["modules"][0]["type"] = "resources"
    _pack(base, "resource_packs/RP", datos)
    _refs(base, "Beta", [])
    (base / "worlds" / "Beta" / "level.dat").write_bytes(b"x")
    codigo, salida, _err = ejecutar("--root", str(base), "--world", "Alfa",
                                    "--kind", "resource", "--lang", "es", "--no-color")
    assert codigo == 0
    assert "Packs: 1 (0 de comportamiento, 1 de recursos)" in salida
    assert "Mundos: 1 | Referencias de packs: 0" in salida


def test_salida_por_defecto_en_ingles(tmp_path):
    """Sin --lang y sin WRAPPER_LANG, la consola habla ingles (console_lang)."""
    base = instalacion_limpia(tmp_path)
    entorno = dict(os.environ)
    entorno.pop("WRAPPER_LANG", None)
    resultado = subprocess.run(
        [sys.executable, os.path.join(RAIZ, "addon_inventory_cli.py"),
         "--root", str(base), "--no-color"],
        cwd=RAIZ, capture_output=True, text=True, encoding="utf-8", env=entorno,
    )
    assert resultado.returncode == 0
    assert "ADDON INVENTORY" in resultado.stdout
    assert "COMPLETE" in resultado.stdout


def test_hallazgos_devuelven_1(tmp_path):
    base = instalacion_con_hallazgos(tmp_path)
    codigo, salida, _err = ejecutar("--root", str(base), "--no-color", "--lang", "es")
    assert codigo == cli.EXIT_HALLAZGOS == 1
    assert "WORLD_REF_UNRESOLVED" in salida
    assert "SCRIPT_DEP_BETA" in salida


def test_inventario_parcial_devuelve_2_y_tiene_precedencia(tmp_path):
    base = instalacion_parcial(tmp_path)
    _refs(base, "Alfa", [{"pack_id": UUID_FANTASMA, "version": [1, 0, 0]}])
    codigo, salida, _err = ejecutar("--root", str(base), "--no-color", "--lang", "es")
    assert codigo == cli.EXIT_PARCIAL == 2
    assert "PARCIAL" in salida
    assert "MANIFEST_JSON_INVALID" in salida


def test_raiz_inexistente_devuelve_3(tmp_path):
    codigo, _salida, err = ejecutar("--root", str(tmp_path / "no-existe"), "--lang", "es")
    assert codigo == cli.EXIT_USO == 3
    assert "no existe" in err


def test_argumentos_invalidos_devuelven_3(tmp_path):
    codigo, _salida, err = ejecutar("--root", str(tmp_path), "--kind", "inventado")
    assert codigo == cli.EXIT_USO == 3
    assert "ERROR" in err


def test_compact_sin_json_devuelve_3(tmp_path):
    codigo, _salida, err = ejecutar("--root", str(tmp_path), "--compact")
    assert codigo == cli.EXIT_USO == 3
    assert "compact" in err


def test_fallo_interno_del_analizador_devuelve_4(tmp_path, monkeypatch, capsys):
    """Salvaguarda de ultimo recurso: un fallo del analizador no debe confundirse
    con un hallazgo (1) ni con un inventario parcial (2). Se ejercita en proceso
    porque la CLI real no puede fallar a voluntad."""
    base = instalacion_limpia(tmp_path)

    def explotar(*_args, **_kwargs):
        raise RuntimeError("fallo simulado del analizador")

    monkeypatch.setattr(addon_inventory, "analyze_addons", explotar)
    codigo = cli.main(["--root", str(base), "--lang", "es"])
    assert codigo == cli.EXIT_INTERNO == 4
    err = capsys.readouterr().err
    assert "Fallo interno" in err and "fallo simulado del analizador" in err


def test_help_devuelve_0_y_documenta_los_codigos(tmp_path):
    codigo, salida, _err = ejecutar("--help")
    assert codigo == 0
    assert "Exit codes" in salida or "Codigos de salida" in salida
    assert "--root" in salida and "--json" in salida


def test_catalogo_de_codigos_devuelve_0(tmp_path):
    codigo, salida, _err = ejecutar("--codes", "--lang", "es")
    assert codigo == 0
    assert "WORLD_REF_UNRESOLVED" in salida
    assert "MANIFEST_JSON_INVALID" in salida
    assert "inventario parcial" in salida


# ---------------------------------------------------------------------------
# Salidas
# ---------------------------------------------------------------------------

def test_salida_json_equivale_al_analizador(tmp_path):
    base = instalacion_con_hallazgos(tmp_path)
    codigo, salida, _err = ejecutar("--root", str(base), "--json")
    assert codigo == cli.EXIT_HALLAZGOS
    datos = json.loads(salida)
    assert datos == addon_inventory.analyze_addons(str(base))
    assert datos["schema_version"] == 1


def test_salida_json_compacta_en_una_linea(tmp_path):
    base = instalacion_limpia(tmp_path)
    codigo, salida, _err = ejecutar("--root", str(base), "--json", "--compact")
    assert codigo == 0
    lineas = [l for l in salida.splitlines() if l.strip()]
    assert len(lineas) == 1
    assert json.loads(lineas[0])["summary"]["packs_total"] == 1


def test_filtros_json_iguales_al_analizador(tmp_path):
    base = instalacion_con_hallazgos(tmp_path)
    _pack(base, "resource_packs/RP", _manifiesto(UUID_B, version=(1, 0, 0)))
    codigo, salida, _err = ejecutar("--root", str(base), "--json", "--kind", "behavior",
                                    "--world", "Alfa")
    assert codigo == cli.EXIT_HALLAZGOS
    datos = json.loads(salida)
    esperado = addon_inventory.filter_payload(
        addon_inventory.analyze_addons(str(base)), world="Alfa", kind="behavior")
    assert datos == esperado
    assert datos["filter"] == {"world": "Alfa", "kind": "behavior"}
    assert all(p["kind"] == "behavior" for p in datos["packs"])


def test_aviso_de_severidad_ignorada_en_json(tmp_path):
    base = instalacion_limpia(tmp_path)
    codigo, salida, err = ejecutar("--root", str(base), "--json", "--severity", "info")
    assert codigo == 0
    assert json.loads(salida)  # el payload sigue siendo completo
    assert "severity" in err


def test_severidad_controla_la_salida_legible(tmp_path, capsys):
    base = instalacion_con_hallazgos(tmp_path)
    assert cli.main(["--root", str(base), "--no-color", "--lang", "es",
                     "--severity", "error"]) == 1
    solo_errores = capsys.readouterr().out
    assert "WORLD_REF_UNRESOLVED" in solo_errores
    assert "SCRIPT_DEP_BETA" not in solo_errores

    assert cli.main(["--root", str(base), "--no-color", "--lang", "es",
                     "--severity", "todos"]) == 1
    todo = capsys.readouterr().out
    assert "SCRIPT_DEP_BETA" in todo
    assert "MANIFEST_JSON_TOLERANT" not in todo  # no hay manifiestos tolerantes aqui
    assert "SCOPE_ROOT_MISSING" in todo


def test_idioma_de_la_salida(tmp_path, capsys):
    base = instalacion_limpia(tmp_path)
    assert cli.main(["--root", str(base), "--no-color", "--lang", "es"]) == 0
    es = capsys.readouterr().out
    assert "INVENTARIO DE ADDONS" in es
    assert "Resumen" in es
    assert cli.main(["--root", str(base), "--no-color", "--lang", "en"]) == 0
    en = capsys.readouterr().out
    assert "ADDON INVENTORY" in en
    assert "Summary" in en


def test_detalle_amplia_modulos_y_dependencias(tmp_path, capsys):
    base = instalacion_con_hallazgos(tmp_path)
    assert cli.main(["--root", str(base), "--no-color", "--lang", "es", "--detalle",
                     "--severity", "todos"]) == 1
    salida = capsys.readouterr().out
    assert "dependencia de scripting" in salida
    assert "@minecraft/server" in salida
    assert "modulo" in salida


def test_la_salida_incluye_nombre_y_descripcion(tmp_path, capsys):
    """Requisito 2: nombre y descripcion son parte del inventario legible."""
    base = tmp_path
    (base / "server.properties").write_text("level-name=Alfa\n", encoding="utf-8")
    (base / "worlds" / "Alfa").mkdir(parents=True)
    (base / "worlds" / "Alfa" / "level.dat").write_bytes(b"x")
    datos = _manifiesto(UUID_A, nombre="Con Descripcion")
    datos["header"]["description"] = "descripcion distintiva del pack"
    _pack(base, "behavior_packs/ConDesc", datos)
    assert cli.main(["--root", str(base), "--no-color", "--lang", "es"]) == 0
    salida = capsys.readouterr().out
    assert "Con Descripcion" in salida
    assert "descripcion distintiva del pack" in salida
    assert "descripcion" in salida  # rotulo del campo, traducible


def test_world_desconocido_no_filtra_pero_no_falla(tmp_path):
    base = instalacion_limpia(tmp_path)
    codigo, salida, _err = ejecutar("--root", str(base), "--json", "--world", "Inexistente")
    assert codigo == 0
    datos = json.loads(salida)
    # El filtro conserva compartidos/sistema, pero la lista de mundos queda vacia.
    assert datos["worlds"] == []


# ---------------------------------------------------------------------------
# Solo lectura
# ---------------------------------------------------------------------------

def test_la_cli_no_modifica_la_instalacion(tmp_path):
    base = instalacion_con_hallazgos(tmp_path)
    antes = snapshot(base)
    ejecutar("--root", str(base), "--no-color", "--severity", "todos", "--detalle")
    ejecutar("--root", str(base), "--json")
    assert snapshot(base) == antes


def test_los_mensajes_del_catalogo_no_dejan_placeholders_sin_sustituir(tmp_path):
    """Anti-drift: si falta un parametro, el mensaje mostraria {clave}."""
    base = instalacion_con_hallazgos(tmp_path)
    payload = addon_inventory.analyze_addons(str(base))
    for diagnostico in payload["diagnostics"]:
        assert "{" not in diagnostico["message_es"], diagnostico
        assert "{" not in diagnostico["message_en"], diagnostico
        assert diagnostico["message_es"].strip()
        assert diagnostico["message_en"].strip()


@pytest.mark.parametrize("code,esperado", [
    ("MANIFEST_JSON_INVALID", "error"),
    ("WORLD_REF_UNRESOLVED", "error"),
    ("PACK_UUID_DUPLICATE", "error"),
    ("SCRIPT_DEP_INTERNAL", "error"),
    ("WORLD_REF_AMBIGUOUS", "aviso"),
    ("PACK_UUID_MULTIPLE_VERSIONS", "info"),
])
def test_gravedad_estable_de_los_codigos_clave(code, esperado):
    assert addon_inventory.CATALOGO[code]["severity"] == esperado
