# -*- coding: utf-8 -*-
"""Tests del analizador compartido de addons (addon_inventory.py).

Cubren el inventario y los diagnosticos sobre INSTALACIONES TEMPORALES
sinteticas: nunca se toca la instalacion real, no se arranca BDS y no se
ejecuta ningun e2e. El analizador es de solo lectura y aqui se verifica
explicitamente (snapshot de contenido/mtime antes y despues).
"""

import ast
import hashlib
import json
import os
import subprocess

import pytest

import addon_inventory as ai

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(RAIZ, "tests", "fixtures", "addons_payload.json")

UUID_A = "aaaaaaaa-1111-4111-8111-111111111111"
UUID_B = "bbbbbbbb-2222-4222-8222-222222222222"
UUID_C = "cccccccc-3333-4333-8333-333333333333"
UUID_D = "dddddddd-4444-4444-8444-444444444444"
UUID_E = "eeeeeeee-5555-4555-8555-555555555555"
UUID_SYS = "ffffffff-6666-4666-8666-666666666666"
UUID_FANTASMA = "00000000-9999-4999-8999-999999999999"


# ---------------------------------------------------------------------------
# Utilidades de instalacion sintetica
# ---------------------------------------------------------------------------

def instalar_base(tmp_path, level_name="Alfa", mundos=("Alfa",), con_pack_dirs=True):
    """Crea una instalacion temporal minima (server.properties + worlds/)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "server.properties").write_text(
        f"level-name={level_name}\nserver-port=19132\n", encoding="utf-8"
    )
    for mundo in mundos:
        carpeta = tmp_path / "worlds" / mundo
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "level.dat").write_bytes(b"level")
        if con_pack_dirs:
            (carpeta / "behavior_packs").mkdir(exist_ok=True)
            (carpeta / "resource_packs").mkdir(exist_ok=True)
    return tmp_path


def manifiesto(uuid, version=(1, 0, 0), nombre="Pack de prueba", modulos=None,
               dependencias=None, min_engine=(1, 20, 0), descripcion="pack de prueba",
               format_version=2, extra=None, tipo_modulo="data"):
    def como_lista(valor):
        # Un vector se copia; un texto se respeta tal cual (para probar el
        # formato inesperado documentado en B5/A3).
        return list(valor) if isinstance(valor, (list, tuple)) else valor

    datos = {
        "format_version": format_version,
        "header": {
            "name": nombre,
            "description": descripcion,
            "uuid": uuid,
            "version": como_lista(version),
            "min_engine_version": como_lista(min_engine) if min_engine is not None else None,
        },
        "modules": modulos if modulos is not None else [
            {"type": tipo_modulo, "uuid": str(uuid), "version": list(version)
             if isinstance(version, (list, tuple)) else [1, 0, 0]},
        ],
    }
    if datos["header"]["min_engine_version"] is None:
        del datos["header"]["min_engine_version"]
    if dependencias is not None:
        datos["dependencies"] = dependencias
    if extra:
        datos.update(extra)
    return datos


def escribir_pack(base, rel_dir, datos=None, texto=None, modulo_uuid=None):
    """Escribe <base>/<rel_dir>/manifest.json (datos dict o texto crudo)."""
    carpeta = base / rel_dir
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / "manifest.json"
    if texto is not None:
        destino.write_text(texto, encoding="utf-8")
        return carpeta
    if modulo_uuid and datos is not None:
        datos["modules"][0]["uuid"] = modulo_uuid
    destino.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")
    return carpeta


def escribir_refs(base, mundo, behavior=None, resource=None):
    carpeta = base / "worlds" / mundo
    carpeta.mkdir(parents=True, exist_ok=True)
    for nombre, refs in (("world_behavior_packs.json", behavior),
                         ("world_resource_packs.json", resource)):
        if refs is None:
            continue
        (carpeta / nombre).write_text(json.dumps(refs, indent=2), encoding="utf-8")


def codigos(payload, severidad=None):
    return [
        d["code"] for d in payload["diagnostics"]
        if severidad is None or d["severity"] == severidad
    ]


def buscar(payload, code):
    return [d for d in payload["diagnostics"] if d["code"] == code]


def pack_por_id(payload, pack_id):
    for pack in payload["packs"]:
        if pack["id"] == pack_id:
            return pack
    raise AssertionError(f"pack no encontrado: {pack_id}")


def snapshot_arbol(base):
    """Huella (ruta, tamano, mtime_ns, sha256) de TODO archivo bajo base."""
    huella = {}
    for raiz, dirs, archivos in os.walk(base):
        dirs.sort()
        for nombre in sorted(archivos):
            ruta = os.path.join(raiz, nombre)
            rel = os.path.relpath(ruta, base).replace(os.sep, "/")
            try:
                with open(ruta, "rb") as f:
                    datos = f.read()
                st = os.stat(ruta)
                huella[rel] = (len(datos), st.st_mtime_ns, hashlib.sha256(datos).hexdigest())
            except OSError as exc:  # un archivo ilegible tambien es parte del estado
                huella[rel] = ("ilegible", str(exc))
    return huella


# ---------------------------------------------------------------------------
# Aspectos basicos
# ---------------------------------------------------------------------------

def test_instalacion_sin_packs_es_completa(tmp_path):
    base = instalar_base(tmp_path)
    payload = ai.analyze_addons(str(base))
    assert payload["packs"] == []
    assert payload["complete"] is True
    assert payload["partial_reasons"] == []
    assert payload["active_world"] == "Alfa"
    # Las ubicaciones documentadas ausentes se informan, no son error.
    assert codigos(payload, "error") == []
    assert "SCOPE_ROOT_MISSING" in codigos(payload)
    assert payload["summary"]["mundos_total"] == 1


def test_raiz_inexistente_no_revienta(tmp_path):
    payload = ai.analyze_addons(str(tmp_path / "no-existe"))
    assert payload["complete"] is False
    assert "BASE_DIR_MISSING" in codigos(payload, "error")


def test_instalacion_con_junction_global_no_revienta(tmp_path):
    """Regresion: el analizador no debe reventar si falta la raiz entera."""
    payload = ai.analyze_addons(str(tmp_path))
    assert payload["packs"] == []
    assert payload["worlds"] == []


def test_packs_validos_compartidos_y_de_mundo(tmp_path):
    base = instalar_base(tmp_path, mundos=("Alfa", "Beta"))
    escribir_pack(base, "behavior_packs/CompartidoBP",
                  manifiesto(UUID_A, nombre="Compartido BP"))
    escribir_pack(base, "resource_packs/CompartidoRP",
                  manifiesto(UUID_B, nombre="Compartido RP", tipo_modulo="resources"))
    escribir_pack(base, "worlds/Alfa/behavior_packs/AlfaBP",
                  manifiesto(UUID_C, nombre="Alfa BP"))
    escribir_pack(base, "worlds/Beta/resource_packs/BetaRP",
                  manifiesto(UUID_D, nombre="Beta RP", tipo_modulo="resources"))
    escribir_refs(base, "Alfa",
                  behavior=[{"pack_id": UUID_A, "version": [1, 0, 0]},
                            {"pack_id": UUID_C, "version": [1, 0, 0]}],
                  resource=[{"pack_id": UUID_B, "version": [1, 0, 0]}])
    escribir_refs(base, "Beta", resource=[{"pack_id": UUID_D, "version": [1, 0, 0]}])

    payload = ai.analyze_addons(str(base))
    assert payload["complete"] is True
    assert payload["summary"]["packs_total"] == 4
    assert payload["summary"]["packs_compartidos"] == 2
    assert payload["summary"]["packs_de_mundo"] == 2

    compartido = pack_por_id(payload, "behavior_packs/CompartidoBP")
    assert compartido["origin"] == "compartido"
    assert compartido["world"] is None
    assert compartido["name"] == "Compartido BP"
    assert compartido["header_uuid"] == UUID_A
    assert compartido["version"] == [1, 0, 0]
    assert compartido["min_engine_version"] == [1, 20, 0]
    assert compartido["format_version"] == 2
    assert compartido["referenced_by_worlds"] == ["Alfa"]
    assert compartido["modules"][0]["type"] == "data"

    propio = pack_por_id(payload, "worlds/Beta/resource_packs/BetaRP")
    assert propio["origin"] == "mundo" and propio["world"] == "Beta"

    mundo_alfa = next(w for w in payload["worlds"] if w["name"] == "Alfa")
    assert mundo_alfa["active"] is True
    assert [r["status"] for r in mundo_alfa["references"]] == ["resolved"] * 3
    assert payload["summary"]["referencias_resueltas"] == 4
    assert codigos(payload, "error") == []


def test_los_mundos_que_referencian_un_pack_no_se_repten(tmp_path):
    """Un pack referenciado dos veces por el mismo mundo se lista UNA vez.

    Las referencias del mundo conservan las dos entradas (y sus diagnosticos);
    la lista "mundos que lo referencian" es un conjunto ordenado: sin esto la
    GUI y la CLI mostraban "Alfa, Alfa" para el mismo mundo.
    """
    base = instalar_base(tmp_path)
    escribir_pack(base, "behavior_packs/Uno", manifiesto(UUID_A))
    escribir_refs(base, "Alfa", behavior=[
        {"pack_id": UUID_A, "version": [1, 0, 0]},
        {"pack_id": UUID_A, "version": [1, 0, 0]},
    ])
    payload = ai.analyze_addons(str(base))
    assert [r["status"] for r in payload["worlds"][0]["references"]] == [
        "resolved", "resolved"]
    assert pack_por_id(payload, "behavior_packs/Uno")["referenced_by_worlds"] == ["Alfa"]


def test_referencia_rota_y_version_inexistente(tmp_path):
    base = instalar_base(tmp_path)
    escribir_pack(base, "behavior_packs/Uno", manifiesto(UUID_A))
    escribir_refs(base, "Alfa", behavior=[
        {"pack_id": UUID_FANTASMA, "version": [1, 0, 0]},
        {"pack_id": UUID_A, "version": [9, 9, 9]},
    ])
    payload = ai.analyze_addons(str(base))
    sin_resolver = buscar(payload, "WORLD_REF_UNRESOLVED")
    assert len(sin_resolver) == 1
    assert sin_resolver[0]["severity"] == "error"
    assert sin_resolver[0]["ref"]["pack_id"] == UUID_FANTASMA
    assert UUID_FANTASMA in sin_resolver[0]["message_es"]
    version = buscar(payload, "WORLD_REF_VERSION_UNAVAILABLE")
    assert len(version) == 1
    assert version[0]["severity"] == "aviso"
    assert version[0]["determined"] is False
    assert payload["complete"] is True  # hallazgos != inventario parcial
    assert payload["summary"]["referencias_sin_resolver"] == 1
    assert payload["summary"]["referencias_sin_version"] == 1


def test_resolucion_ambigua_en_dos_ambitos_del_mismo_mundo(tmp_path):
    """Mismo UUID y version en la carpeta del mundo y en la compartida: dos
    candidatos dentro del ambito efectivo del mundo -> ambigua, sin declarar
    por si solo un duplicado (ambitos distintos)."""
    base = instalar_base(tmp_path)
    escribir_pack(base, "behavior_packs/Compartido", manifiesto(UUID_A, nombre="Compartido"))
    escribir_pack(base, "worlds/Alfa/behavior_packs/Propio", manifiesto(UUID_A, nombre="Propio"))
    escribir_refs(base, "Alfa", behavior=[{"pack_id": UUID_A, "version": [1, 0, 0]}])
    payload = ai.analyze_addons(str(base))
    ambigua = buscar(payload, "WORLD_REF_AMBIGUOUS")
    assert len(ambigua) == 1
    assert ambigua[0]["severity"] == "aviso"
    assert ambigua[0]["determined"] is False
    referencia = next(w for w in payload["worlds"] if w["name"] == "Alfa")["references"][0]
    assert referencia["status"] == "ambiguous"
    assert len(referencia["candidates"]) == 2
    assert codigos(payload, "error") == []
    assert "PACK_UUID_IN_OTHER_SCOPES" in codigos(payload)


def test_uuid_duplicado_en_el_mismo_ambito(tmp_path):
    base = instalar_base(tmp_path)
    escribir_pack(base, "behavior_packs/Uno", manifiesto(UUID_A))
    escribir_pack(base, "behavior_packs/Dos", manifiesto(UUID_A))
    payload = ai.analyze_addons(str(base))
    duplicado = buscar(payload, "PACK_UUID_DUPLICATE")
    assert len(duplicado) == 1
    assert duplicado[0]["severity"] == "error"
    texto = duplicado[0]["source_file"] + " " + duplicado[0]["message_es"]
    assert "Uno" in texto and "Dos" in texto


def test_uuid_repetido_con_versiones_distintas_no_es_conflicto(tmp_path):
    """Patron de los packs vanilla versionados de BDS: mismo UUID, version
    distinta. La documentacion no cubre esa colision -> informativo."""
    base = instalar_base(tmp_path)
    escribir_pack(base, "behavior_packs/vanilla", manifiesto(UUID_A, version=(0, 0, 1)))
    escribir_pack(base, "behavior_packs/vanilla_1.21.0", manifiesto(UUID_A, version=(1, 21, 0)))
    payload = ai.analyze_addons(str(base))
    assert buscar(payload, "PACK_UUID_DUPLICATE") == []
    multiples = buscar(payload, "PACK_UUID_MULTIPLE_VERSIONS")
    assert len(multiples) == 1
    assert multiples[0]["severity"] == "info"
    assert multiples[0]["determined"] is False
    # La referencia con version exacta resuelve al candidato correcto.
    escribir_refs(base, "Alfa", behavior=[{"pack_id": UUID_A, "version": [1, 21, 0]}])
    payload = ai.analyze_addons(str(base))
    referencia = next(w for w in payload["worlds"] if w["name"] == "Alfa")["references"][0]
    assert referencia["status"] == "resolved"
    assert referencia["resolved_pack"] == "behavior_packs/vanilla_1.21.0"


def test_dependencia_de_pack_ausente_presente_y_discrepante(tmp_path):
    base = instalar_base(tmp_path)
    escribir_pack(base, "behavior_packs/Dependiente", manifiesto(
        UUID_A, dependencias=[
            {"uuid": UUID_FANTASMA, "version": [1, 0, 0]},
            {"uuid": UUID_B, "version": [1, 0, 0]},
            {"uuid": UUID_C, "version": [2, 0, 0]},
        ]))
    escribir_pack(base, "behavior_packs/Correcto", manifiesto(UUID_B, version=(1, 0, 0)))
    escribir_pack(base, "behavior_packs/OtraVersion", manifiesto(UUID_C, version=(1, 5, 0)))
    payload = ai.analyze_addons(str(base))
    ausente = buscar(payload, "DEPENDENCY_PACK_MISSING")
    assert len(ausente) == 1 and ausente[0]["severity"] == "error"
    discrepante = buscar(payload, "DEPENDENCY_PACK_VERSION_MISMATCH")
    assert len(discrepante) == 1
    assert discrepante[0]["severity"] == "aviso"
    assert discrepante[0]["determined"] is False
    resolucion = pack_por_id(payload, "behavior_packs/Dependiente")["dependency_resolution"]
    assert [r["status"] for r in resolucion] == ["missing", "resolved", "version_mismatch"]


def test_dependencia_satisfecha_por_otro_tipo_queda_como_estado(tmp_path):
    """Caso real (packs vanilla de chemistry): el BP depende del UUID del RP.
    F1 no restringe el tipo del pack dependido -> no es un diagnostico."""
    base = instalar_base(tmp_path)
    escribir_pack(base, "behavior_packs/BP", manifiesto(
        UUID_A, dependencias=[{"uuid": UUID_B, "version": [1, 0, 0]}]))
    escribir_pack(base, "resource_packs/RP", manifiesto(
        UUID_B, tipo_modulo="resources"))
    payload = ai.analyze_addons(str(base))
    assert buscar(payload, "DEPENDENCY_PACK_MISSING") == []
    resolucion = pack_por_id(payload, "behavior_packs/BP")["dependency_resolution"][0]
    assert resolucion["status"] == "resolved"
    assert resolucion["candidates"][0]["pack"] == "resource_packs/RP"
    # Con una version que no coincide y ningun candidato del mismo tipo, el
    # estado queda declarado como "otro tipo" (sin diagnostico).
    escribir_pack(base, "behavior_packs/BP2", manifiesto(
        UUID_C, dependencias=[{"uuid": UUID_B, "version": [7, 0, 0]}]))
    payload = ai.analyze_addons(str(base))
    resolucion = pack_por_id(payload, "behavior_packs/BP2")["dependency_resolution"][0]
    assert resolucion["status"] == "other_kind"
    assert buscar(payload, "DEPENDENCY_PACK_MISSING") == []
    assert buscar(payload, "DEPENDENCY_PACK_VERSION_MISMATCH") == []


@pytest.mark.parametrize("generado,valido", [
    ({"example_tool": ["1.0.0", "1.1.0"]}, True),
    ({"tool-2": ["1.0.0-beta.1+build.03"]}, True),
    ({}, True),
    ({"tool": []}, True),
    ([{"tool_name": "example_tool", "tool_version": "1.0.0"}], False),
    ({"tool": "1.0.0"}, False),
    ({"nombre invalido": ["1.0.0"]}, False),
    ({"x" * 33: ["1.0.0"]}, False),
    ({"tool": ["01.0.0"]}, False),
    ({"tool": ["1.0.0-01"]}, False),
    ({"tool": [None]}, False),
    (None, False),
])
def test_generated_with_respeta_el_objeto_del_ejemplo_oficial(tmp_path, generado, valido):
    base = instalar_base(tmp_path)
    escribir_pack(base, "behavior_packs/Generado", manifiesto(
        UUID_A, extra={"metadata": {"generated_with": generado}}))
    payload = ai.analyze_addons(str(base))
    assert bool(buscar(payload, "GENERATED_WITH_INVALID")) is (not valido)


@pytest.mark.parametrize("raiz", ["behavior_packs", "system_behavior_packs"])
def test_dependencia_compartida_se_resuelve_por_mundo(tmp_path, raiz):
    base = instalar_base(tmp_path, mundos=("Alfa", "Beta"))
    escribir_pack(base, raiz + "/BP", manifiesto(
        UUID_A, dependencias=[{"uuid": UUID_B, "version": [1, 0, 0]}]))
    escribir_pack(base, "worlds/Alfa/resource_packs/RP", manifiesto(
        UUID_B, tipo_modulo="resources"))
    for mundo in ("Alfa", "Beta"):
        escribir_refs(base, mundo, behavior=[{"pack_id": UUID_A, "version": [1, 0, 0]}])
    escribir_refs(base, "Alfa", resource=[{"pack_id": UUID_B, "version": [1, 0, 0]}])
    antes = snapshot_arbol(str(base))
    payload = ai.analyze_addons(str(base))
    resolucion = pack_por_id(payload, raiz + "/BP")["dependency_resolution"][0]
    assert resolucion["status"] == "context_dependent"
    por_mundo = {r["world"]: r for r in resolucion["world_resolutions"]}
    assert por_mundo["Alfa"]["status"] == "resolved"
    assert por_mundo["Alfa"]["candidates"][0]["pack"] == "worlds/Alfa/resource_packs/RP"
    assert por_mundo["Beta"]["status"] == "missing"
    assert por_mundo["Beta"]["candidates"] == []
    assert [d["world"] for d in buscar(payload, "DEPENDENCY_PACK_MISSING")] == ["Beta"]
    alfa = ai.filter_payload(payload, world="Alfa")
    assert buscar(alfa, "DEPENDENCY_PACK_MISSING") == []
    assert pack_por_id(alfa, raiz + "/BP")["dependency_resolution"][0]["status"] == "resolved"
    assert snapshot_arbol(str(base)) == antes
    assert pack_por_id(payload, raiz + "/BP")["dependency_resolution"][0]["status"] == "context_dependent"


def test_contexto_de_mundo_se_propaga_por_dependencias_transitivas_y_ciclos(tmp_path):
    base = instalar_base(tmp_path, mundos=("Alfa", "Beta"))
    for nombre, propio, destino in [("BP", UUID_A, UUID_B), ("Biblioteca", UUID_B, UUID_C)]:
        escribir_pack(base, "behavior_packs/" + nombre, manifiesto(
            propio, dependencias=[{"uuid": destino, "version": [1, 0, 0]}]))
    escribir_pack(base, "worlds/Alfa/resource_packs/RP", manifiesto(
        UUID_C, tipo_modulo="resources", dependencias=[{"uuid": UUID_B, "version": [1, 0, 0]}]))
    escribir_pack(base, "worlds/Beta/resource_packs/RP", manifiesto(
        UUID_C, tipo_modulo="resources", version=(2, 0, 0)))
    escribir_refs(base, "Alfa", behavior=[{"pack_id": UUID_A, "version": [1, 0, 0]}])
    payload = ai.analyze_addons(str(base))
    biblioteca = pack_por_id(payload, "behavior_packs/Biblioteca")["dependency_resolution"][0]
    assert biblioteca["status"] == "resolved"
    assert biblioteca["world_resolutions"][0]["world"] == "Alfa"
    assert biblioteca["candidates"][0]["pack"] == "worlds/Alfa/resource_packs/RP"
    assert buscar(payload, "DEPENDENCY_PACK_MISSING") == []


def test_un_filtro_no_hereda_la_resolucion_de_un_mundo_no_evaluado(tmp_path):
    base = instalar_base(tmp_path, mundos=("Alfa", "Beta"))
    escribir_pack(base, "behavior_packs/BP", manifiesto(
        UUID_A, dependencias=[{"uuid": UUID_B, "version": [1, 0, 0]}]))
    escribir_refs(base, "Beta", behavior=[{"pack_id": UUID_A, "version": [1, 0, 0]}])
    payload = ai.analyze_addons(str(base))
    assert pack_por_id(payload, "behavior_packs/BP")["dependency_resolution"][0]["status"] == "missing"
    alfa = ai.filter_payload(payload, world="Alfa")
    resolucion = pack_por_id(alfa, "behavior_packs/BP")["dependency_resolution"][0]
    assert resolucion["status"] == "unchecked"
    assert resolucion["world_resolutions"] == []
    assert buscar(alfa, "DEPENDENCY_PACK_MISSING") == []


@pytest.mark.parametrize("mundo", [None, "Alfa"])
def test_filtro_tipo_acota_referencias_archivos_y_diagnosticos(tmp_path, mundo):
    base = instalar_base(tmp_path)
    escribir_pack(base, "resource_packs/RP", manifiesto(UUID_B, tipo_modulo="resources"))
    escribir_refs(base, "Alfa", behavior=[{"pack_id": UUID_FANTASMA, "version": [1, 0, 0]}],
                  resource=[{"pack_id": UUID_B, "version": [1, 0, 0]}])
    payload = ai.analyze_addons(str(base))
    antes = json.dumps(payload, sort_keys=True)
    vista = ai.filter_payload(payload, world=mundo, kind="resource")
    assert [r["kind"] for w in vista["worlds"] for r in w["references"]] == ["resource"]
    assert all(f["kind"] == "resource" for w in vista["worlds"] for f in w["ref_files"])
    assert buscar(vista, "WORLD_REF_UNRESOLVED") == []
    assert vista["summary"]["referencias_resueltas"] == vista["summary"]["referencias_total"] == 1
    assert json.dumps(payload, sort_keys=True) == antes


@pytest.mark.parametrize("nombre", ["behavior", "resource"])
def test_nombre_de_mundo_no_se_confunde_con_tipo_en_el_filtro(tmp_path, nombre):
    base = instalar_base(tmp_path, level_name=nombre, mundos=(nombre,))
    (base / "worlds" / nombre / "level.dat").unlink()
    payload = ai.analyze_addons(str(base))
    vista = ai.filter_payload(payload, world=nombre,
                              kind="resource" if nombre == "behavior" else "behavior")
    assert len(buscar(vista, "WORLD_WITHOUT_LEVEL_DAT")) == 1


def test_dependencias_de_scripting(tmp_path):
    base = instalar_base(tmp_path)
    modulos = [{"type": "script", "uuid": UUID_A, "version": [1, 0, 0],
                "language": "javascript", "entry": "scripts/main.js"}]
    escribir_pack(base, "behavior_packs/Scripts", manifiesto(
        UUID_A, modulos=modulos, dependencias=[
            {"module_name": "@minecraft/server", "version": "1.9.0"},
            {"module_name": "@minecraft/server-admin", "version": "1.0.0-beta"},
            {"module_name": "@minecraft/server-editor", "version": "2.0.0-internal"},
            {"module_name": "@minecraft/server-ui", "version": "1.0"},
            {"module_name": "minecraft/server", "version": "1.0.0"},
            {"module_name": "@minecraft/server-net"},
        ]))
    payload = ai.analyze_addons(str(base))
    assert len(buscar(payload, "SCRIPT_DEP_BETA")) == 1
    interno = buscar(payload, "SCRIPT_DEP_INTERNAL")
    assert len(interno) == 1 and interno[0]["severity"] == "error"
    invalida = buscar(payload, "SCRIPT_DEP_VERSION_INVALID")
    assert [d["field"] for d in invalida] == ["dependencies[3].version"]
    assert len(buscar(payload, "SCRIPT_DEP_MODULE_NAME_INVALID")) == 1
    assert len(buscar(payload, "SCRIPT_DEP_VERSION_MISSING")) == 1
    pack = pack_por_id(payload, "behavior_packs/Scripts")
    assert pack["script_dependencies"][0]["module_name"] == "@minecraft/server"
    assert pack["script_dependencies"][1]["beta"] is True
    assert pack["script_dependencies"][2]["internal"] is True
    # La version "beta" a secas tambien es valida y se marca beta.
    escribir_pack(base, "behavior_packs/Beta", manifiesto(
        UUID_B, dependencias=[{"module_name": "@minecraft/server", "version": "beta"}]))
    payload = ai.analyze_addons(str(base))
    assert pack_por_id(payload, "behavior_packs/Beta")["script_dependencies"][0]["beta"] is True
    invalidas = [d for d in buscar(payload, "SCRIPT_DEP_VERSION_INVALID")
                 if "Beta" in d["source_file"]]
    assert invalidas == []


def test_modulos_tipos_y_coherencia(tmp_path):
    base = instalar_base(tmp_path)
    modulos = [
        {"type": "client_data", "uuid": UUID_B, "version": [1, 0, 0]},
        {"type": "resources", "uuid": UUID_C, "version": [1, 0, 0]},
    ]
    escribir_pack(base, "behavior_packs/Raro", manifiesto(UUID_A, modulos=modulos))
    payload = ai.analyze_addons(str(base))
    desconocido = buscar(payload, "MODULE_TYPE_UNKNOWN")
    assert len(desconocido) == 1 and desconocido[0]["severity"] == "aviso"
    incoherente = buscar(payload, "MODULE_KIND_MISMATCH")
    assert len(incoherente) == 1 and incoherente[0]["severity"] == "aviso"
    # Un tipo desconocido NO invalida el manifiesto (N2).
    assert pack_por_id(payload, "behavior_packs/Raro")["status"] == "ok"


def test_uuid_de_modulo_repetido_y_igual_al_header(tmp_path):
    base = instalar_base(tmp_path)
    modulos = [
        {"type": "data", "uuid": UUID_A, "version": [1, 0, 0]},
        {"type": "script", "uuid": UUID_A, "version": [1, 0, 0]},
    ]
    escribir_pack(base, "behavior_packs/Repetido", manifiesto(UUID_A, modulos=modulos))
    payload = ai.analyze_addons(str(base))
    assert len(buscar(payload, "MODULE_UUID_EQUALS_HEADER")) == 2
    assert len(buscar(payload, "MODULE_UUID_DUPLICATE_IN_PACK")) == 1
    # Mismo UUID de modulo en DOS packs con la misma version y ambito.
    base2 = instalar_base(tmp_path / "dos")
    escribir_pack(base2, "behavior_packs/Uno", manifiesto(UUID_B), modulo_uuid=UUID_E)
    escribir_pack(base2, "behavior_packs/Dos", manifiesto(UUID_C), modulo_uuid=UUID_E)
    payload2 = ai.analyze_addons(str(base2))
    compartido = buscar(payload2, "MODULE_UUID_DUPLICATE_IN_SCOPE")
    assert len(compartido) == 1 and compartido[0]["severity"] == "aviso"


def test_pack_de_sistema_protege_su_uuid(tmp_path):
    base = instalar_base(tmp_path)
    escribir_pack(base, "system_behavior_packs/Sistema", manifiesto(UUID_SYS))
    escribir_pack(base, "behavior_packs/Usuario", manifiesto(UUID_SYS))
    payload = ai.analyze_addons(str(base))
    protegido = buscar(payload, "SYSTEM_PACK_UUID_PROTECTED")
    assert len(protegido) == 1
    assert protegido[0]["severity"] == "error"
    assert protegido[0]["source"] == "BDS-howto"
    assert pack_por_id(payload, "system_behavior_packs/Sistema")["origin"] == "sistema"


# ---------------------------------------------------------------------------
# Manifiestos raros: JSON, formatos y campos
# ---------------------------------------------------------------------------

def test_manifest_json_invalido_no_impide_el_resto(tmp_path):
    base = instalar_base(tmp_path)
    escribir_pack(base, "behavior_packs/Roto", texto="{ esto no es json ,,,")
    escribir_pack(base, "behavior_packs/Sano", manifiesto(UUID_A))
    payload = ai.analyze_addons(str(base))
    roto = buscar(payload, "MANIFEST_JSON_INVALID")
    assert len(roto) == 1 and roto[0]["severity"] == "error"
    assert pack_por_id(payload, "behavior_packs/Roto")["status"] == "invalid"
    assert pack_por_id(payload, "behavior_packs/Sano")["status"] == "ok"
    assert payload["complete"] is False
    assert payload["partial_reasons"] == ["MANIFEST_JSON_INVALID"]


def test_manifest_json_tolerante_con_comentarios_y_coma_final(tmp_path):
    """Los manifiestos oficiales de Mojang (chemistry) traen comentarios //."""
    base = instalar_base(tmp_path)
    texto = (
        "{\n"
        '  "format_version": 2,\n'
        '  "header": {\n'
        '    "name": "Comentado",\n'
        '    "description": "d",\n'
        '    "uuid": "%s",\n'
        '    "version": [1, 0, 0],\n'
        '    "min_engine_version": [1, 20, 0]\n'
        "  },\n"
        '  "modules": [\n'
        '    // modulo de datos\n'
        '    {"type": "data", "uuid": "%s", "version": [1, 0, 0]},\n'
        "  ]\n"
        "}\n" % (UUID_A, UUID_B)
    )
    escribir_pack(base, "behavior_packs/Comentado", texto=texto)
    payload = ai.analyze_addons(str(base))
    tolerante = buscar(payload, "MANIFEST_JSON_TOLERANT")
    assert len(tolerante) == 1 and tolerante[0]["severity"] == "info"
    pack = pack_por_id(payload, "behavior_packs/Comentado")
    assert pack["json_tolerant"] is True
    assert pack["header_uuid"] == UUID_A
    assert pack["status"] == "ok"
    assert codigos(payload, "error") == []


def test_estructuras_inesperadas_se_reportan_sin_reventar(tmp_path):
    base = instalar_base(tmp_path)
    escribir_pack(base, "behavior_packs/SinHeader", {"format_version": 2, "modules": []})
    escribir_pack(base, "behavior_packs/SinModulos", {
        "format_version": 2,
        "header": {"name": "n", "description": "d", "uuid": UUID_B, "version": [1, 0, 0]},
    })
    escribir_pack(base, "behavior_packs/ListaNoObjeto", texto="[1, 2, 3]")
    escribir_pack(base, "behavior_packs/SinFormat", {
        "header": {"name": "n", "description": "d", "uuid": UUID_C, "version": [1, 0, 0]},
        "modules": [{"type": "data", "uuid": UUID_D, "version": [1, 0, 0]}],
    })
    escribir_pack(base, "behavior_packs/ModuloRaro", manifiesto(UUID_D, modulos=[
        "no-es-objeto",
        {"uuid": UUID_E, "version": [1, 0, 0]},
    ]))
    payload = ai.analyze_addons(str(base))
    assert len(buscar(payload, "MANIFEST_HEADER_MISSING")) == 1
    # SinHeader tiene modules: [] (lista vacia) y SinModulos no la declara.
    assert len(buscar(payload, "MANIFEST_MODULES_MISSING")) == 2
    assert len(buscar(payload, "MANIFEST_JSON_NOT_OBJECT")) == 1
    assert len(buscar(payload, "MANIFEST_FORMAT_VERSION_MISSING")) == 1
    assert len(buscar(payload, "MODULE_NOT_OBJECT")) == 1
    assert len(buscar(payload, "MODULE_TYPE_MISSING")) == 1
    assert payload["complete"] is False
    # Ningun pack valido se pierde por los rotos.
    assert len(payload["packs"]) == 5


def test_campos_adicionales_no_invalidan_el_manifiesto(tmp_path):
    base = instalar_base(tmp_path)
    escribir_pack(base, "behavior_packs/Extra", manifiesto(
        UUID_A, extra={
            "metadata": {"authors": ["alguien"], "license": "MIT", "url": "https://ejemplo"},
            "capabilities": ["pbr", "capacidad_futura"],
            "subpacks": [{"folder_name": "x", "name": "x", "memory_tier": 0}],
            "campo_desconocido": {"a": 1},
        }))
    payload = ai.analyze_addons(str(base))
    pack = pack_por_id(payload, "behavior_packs/Extra")
    assert pack["status"] == "ok"
    assert codigos(payload, "error") == []
    capacidad = buscar(payload, "CAPABILITY_UNKNOWN")
    assert len(capacidad) == 1 and capacidad[0]["severity"] == "aviso"


def test_formatos_no_soportados_aparecen_como_no_analizados(tmp_path):
    base = instalar_base(tmp_path)
    escribir_pack(base, "behavior_packs/Preview", manifiesto(UUID_A, format_version=3,
                                                             version=("1.0.0",)))
    escribir_pack(base, "resource_packs/Skin", manifiesto(UUID_B, format_version=1,
                                                          tipo_modulo="skin_pack"))
    escribir_pack(base, "behavior_packs/Normal", manifiesto(UUID_C))
    payload = ai.analyze_addons(str(base))
    no_soportados = buscar(payload, "MANIFEST_FORMAT_VERSION_UNSUPPORTED")
    assert len(no_soportados) == 2
    assert all(d["severity"] == "info" for d in no_soportados)
    assert all(d["determined"] is False for d in no_soportados)
    preview = pack_por_id(payload, "behavior_packs/Preview")
    assert preview["status"] == "unsupported"
    assert preview["unsupported_reason"] == "format_version"
    # No analizado NO es corrupto: no hay diagnosticos de error por ello.
    assert codigos(payload, "error") == []
    assert {n["reason_code"] for n in payload["not_analyzed"]} == {
        "MANIFEST_FORMAT_VERSION_UNSUPPORTED"}
    assert len(payload["not_analyzed"]) == 2
    assert payload["complete"] is True  # limitacion declarada, no fallo


def test_manifiesto_anidado_y_representacion_empaquetada(tmp_path):
    base = instalar_base(tmp_path)
    anidado = base / "behavior_packs" / "Desempaquetado" / "PackReal"
    anidado.mkdir(parents=True)
    (anidado / "manifest.json").write_text(json.dumps(manifiesto(UUID_A)), encoding="utf-8")
    (base / "behavior_packs" / "Empaquetado.mcpack").write_bytes(b"PK\x03\x04")
    payload = ai.analyze_addons(str(base))
    assert len(buscar(payload, "PACK_MANIFEST_NESTED")) == 1
    assert len(buscar(payload, "PACK_ARCHIVED_REPRESENTATION")) == 1
    assert payload["packs"] == []
    assert payload["complete"] is True
    assert len(payload["not_analyzed"]) == 2


def test_carpeta_sin_manifiesto_y_mundo_sin_level_dat(tmp_path):
    base = instalar_base(tmp_path, mundos=())
    (base / "behavior_packs" / "Vacia").mkdir(parents=True)
    (base / "worlds" / "SinNivel").mkdir(parents=True)
    payload = ai.analyze_addons(str(base))
    assert len(buscar(payload, "PACK_FOLDER_WITHOUT_MANIFEST")) == 1
    assert len(buscar(payload, "WORLD_WITHOUT_LEVEL_DAT")) == 1
    assert payload["complete"] is False
    assert set(payload["partial_reasons"]) == {
        "PACK_FOLDER_WITHOUT_MANIFEST", "WORLD_WITHOUT_LEVEL_DAT"}


def test_referencias_de_mundo_con_estructura_inesperada(tmp_path):
    base = instalar_base(tmp_path)
    escribir_pack(base, "behavior_packs/Uno", manifiesto(UUID_A))
    escribir_pack(base, "behavior_packs/Dos", manifiesto(UUID_B))
    carpeta = base / "worlds" / "Alfa"
    (carpeta / "world_behavior_packs.json").write_text(
        json.dumps({"pack_id": UUID_A, "version": [1, 0, 0]}), encoding="utf-8")
    (carpeta / "world_resource_packs.json").write_text(json.dumps([
        {"pack_id": UUID_A, "version": [1, 0, 0]},
        {"version": [1, 0, 0]},
        {"pack_id": "no-es-uuid", "version": [1, 0, 0]},
        "texto",
        {"pack_id": UUID_B},
    ]), encoding="utf-8")
    payload = ai.analyze_addons(str(base))
    assert len(buscar(payload, "WORLD_REFS_NOT_ARRAY")) == 1
    assert len(buscar(payload, "WORLD_REFS_ENTRY_INVALID")) == 1
    assert len(buscar(payload, "WORLD_REF_PACK_ID_MISSING")) == 1
    assert len(buscar(payload, "WORLD_REF_PACK_ID_INVALID")) == 1
    assert len(buscar(payload, "WORLD_REF_VERSION_MISSING")) == 1
    assert payload["complete"] is False
    mundo = payload["worlds"][0]
    assert mundo["ref_files"][0]["status"] == "unsupported"
    assert mundo["ref_files"][1]["status"] == "ok"


def test_referencia_de_tipo_cruzado(tmp_path):
    """F-4: world_resource_packs.json no deberia listar un pack de comportamiento."""
    base = instalar_base(tmp_path)
    escribir_pack(base, "behavior_packs/BP", manifiesto(UUID_A))
    escribir_refs(base, "Alfa", resource=[{"pack_id": UUID_A, "version": [1, 0, 0]}])
    payload = ai.analyze_addons(str(base))
    cruce = buscar(payload, "WORLD_REF_KIND_MISMATCH")
    assert len(cruce) == 1 and cruce[0]["severity"] == "aviso"
    referencia = payload["worlds"][0]["references"][0]
    assert referencia["status"] == "kind_mismatch"
    assert referencia["candidates"][0]["pack"] == "behavior_packs/BP"
    assert payload["summary"]["referencias_tipo_cruzado"] == 1
    assert buscar(payload, "WORLD_REF_UNRESOLVED") == []
    assert pack_por_id(payload, "behavior_packs/BP")["referenced_by_worlds"] == ["Alfa"]


def test_referencia_a_pack_de_otro_mundo(tmp_path):
    """E4/E5: los packs propios de un mundo no estan disponibles en otro."""
    base = instalar_base(tmp_path, mundos=("Alfa", "Beta"))
    escribir_pack(base, "worlds/Beta/behavior_packs/SoloBeta", manifiesto(UUID_A))
    escribir_refs(base, "Alfa", behavior=[{"pack_id": UUID_A, "version": [1, 0, 0]}])
    payload = ai.analyze_addons(str(base))
    sin_resolver = buscar(payload, "WORLD_REF_UNRESOLVED")
    assert len(sin_resolver) == 1
    assert "mundo:Beta:behavior" in sin_resolver[0]["message_es"]


def test_version_de_manifiesto_con_formato_inesperado(tmp_path):
    base = instalar_base(tmp_path)
    escribir_pack(base, "behavior_packs/DosComponentes", manifiesto(UUID_A, version=(1, 0),
                                                                    min_engine=(1, 20)))
    escribir_pack(base, "behavior_packs/VersionTexto", manifiesto(UUID_B, version="1.2.3"))
    escribir_pack(base, "behavior_packs/SinVersion", {
        "format_version": 2,
        "header": {"name": "n", "description": "d", "uuid": UUID_C, "version": "no-version"},
        "modules": [{"type": "data", "uuid": UUID_D, "version": [1, 0, 0]}],
    })
    payload = ai.analyze_addons(str(base))
    formato = buscar(payload, "PACK_VERSION_FORMAT_UNEXPECTED")
    assert {d["source_file"].split("/")[1] for d in formato} == {"DosComponentes", "VersionTexto"}
    assert len(buscar(payload, "PACK_VERSION_INVALID")) == 1
    assert len(buscar(payload, "MIN_ENGINE_VERSION_FORMAT_UNEXPECTED")) == 1
    # Las versiones de 2 componentes siguen siendo comparables en el inventario.
    assert pack_por_id(payload, "behavior_packs/DosComponentes")["version"] == [1, 0, 0]


# ---------------------------------------------------------------------------
# Seguridad de rutas: junctions / reparse points y permisos
# ---------------------------------------------------------------------------

def _crear_junction(enlace, destino):
    if os.name != "nt":
        pytest.skip("las junctions son exclusivas de Windows")
    resultado = subprocess.run(["cmd", "/c", "mklink", "/J", str(enlace), str(destino)],
                               capture_output=True, text=True)
    if resultado.returncode != 0 or not os.path.isdir(str(enlace)):
        pytest.skip("no se pudo crear la junction: %s" % (resultado.stderr.strip(),))


def test_junction_dentro_de_una_ubicacion_de_packs_no_se_sigue(tmp_path):
    base = instalar_base(tmp_path)
    (base / "behavior_packs").mkdir(parents=True, exist_ok=True)
    externo = tmp_path / "fuera" / "PackExterno"
    externo.mkdir(parents=True)
    (externo / "manifest.json").write_text(json.dumps(manifiesto(UUID_A)), encoding="utf-8")
    _crear_junction(base / "behavior_packs" / "Enlace", externo)
    payload = ai.analyze_addons(str(base))
    reparse = buscar(payload, "SCOPE_ENTRY_REPARSE")
    assert len(reparse) == 1 and reparse[0]["severity"] == "aviso"
    assert payload["packs"] == []
    assert payload["complete"] is False
    assert UUID_A not in json.dumps(payload)


def test_raiz_de_packs_que_es_junction_no_se_explora(tmp_path):
    base = instalar_base(tmp_path)
    real = tmp_path / "real_behavior_packs"
    real.mkdir()
    (real / "Pack").mkdir()
    (real / "Pack" / "manifest.json").write_text(json.dumps(manifiesto(UUID_A)), encoding="utf-8")
    _crear_junction(base / "behavior_packs", real)
    payload = ai.analyze_addons(str(base))
    reparse = buscar(payload, "SCOPE_ROOT_REPARSE")
    assert len(reparse) == 1
    assert payload["packs"] == []
    assert payload["complete"] is False


def test_junction_dentro_de_worlds_no_se_analiza(tmp_path):
    base = instalar_base(tmp_path)
    externo = tmp_path / "mundo_externo"
    externo.mkdir()
    (externo / "level.dat").write_bytes(b"x")
    _crear_junction(base / "worlds" / "Enlazado", externo)
    payload = ai.analyze_addons(str(base))
    reparse = buscar(payload, "WORLD_ENTRY_REPARSE")
    assert len(reparse) == 1
    assert [w["name"] for w in payload["worlds"]] == ["Alfa"]
    assert payload["complete"] is False


def test_manifiesto_que_es_junction_no_se_lee(tmp_path, monkeypatch):
    """El manifiesto es un reparse point: no se lee ni se sigue.

    Nota: un symlink de ARCHIVO exige SeCreateSymbolicLinkPrivilege (admin o
    modo desarrollador) y las junctions de Windows solo aplican a carpetas, asi
    que la rama se ejercita forzando la deteccion por el modulo dueno
    (auto_backup._es_punto_reparse), que es la convencion de monkeypatch del
    repo. La deteccion real de junctions se cubre en los tests de carpeta.
    """
    import auto_backup

    base = instalar_base(tmp_path)
    escribir_pack(base, "behavior_packs/Enlazado", manifiesto(UUID_A))
    original = auto_backup._es_punto_reparse
    objetivo = os.path.normcase(str(base / "behavior_packs" / "Enlazado" / "manifest.json"))

    def espiar(ruta):
        if os.path.normcase(str(ruta)) == objetivo:
            return True
        return original(ruta)

    monkeypatch.setattr(auto_backup, "_es_punto_reparse", espiar)
    payload = ai.analyze_addons(str(base))
    assert len(buscar(payload, "MANIFEST_REPARSE")) == 1
    assert payload["packs"][0]["status"] == "unreadable"
    assert UUID_A not in json.dumps(payload)


@pytest.mark.skipif(os.name != "nt", reason="los permisos se aplican con icacls (Windows)")
def test_manifiesto_sin_permisos_de_lectura(tmp_path):
    base = instalar_base(tmp_path)
    carpeta = escribir_pack(base, "behavior_packs/SinPermisos", manifiesto(UUID_A))
    escribir_pack(base, "behavior_packs/Sano", manifiesto(UUID_B))
    usuario = "%s\\%s" % (os.environ.get("USERDOMAIN", ""), os.environ.get("USERNAME", ""))
    manifiesto_path = str(carpeta / "manifest.json")
    aplicado = subprocess.run(["icacls", manifiesto_path, "/deny", "%s:(R)" % usuario],
                              capture_output=True, text=True)
    try:
        if aplicado.returncode != 0:
            pytest.skip("no se pudo aplicar el permiso: %s" % aplicado.stdout.strip())
        payload = ai.analyze_addons(str(base))
        ilegible = buscar(payload, "MANIFEST_UNREADABLE")
        assert len(ilegible) == 1 and ilegible[0]["severity"] == "error"
        assert pack_por_id(payload, "behavior_packs/SinPermisos")["status"] == "unreadable"
        assert pack_por_id(payload, "behavior_packs/Sano")["status"] == "ok"
        assert payload["complete"] is False
    finally:
        subprocess.run(["icacls", manifiesto_path, "/remove:d", usuario],
                       capture_output=True, text=True)


def test_fallo_inesperado_por_pack_no_aborta_el_inventario(tmp_path, monkeypatch):
    base = instalar_base(tmp_path)
    escribir_pack(base, "behavior_packs/Uno", manifiesto(UUID_A))
    escribir_pack(base, "behavior_packs/Dos", manifiesto(UUID_B))
    original = ai._Analisis._leer_manifest

    def explotar(self, pack, manifest, scope_id, kind):
        if pack["id"].endswith("Dos"):
            raise RuntimeError("fallo simulado")
        return original(self, pack, manifest, scope_id, kind)

    monkeypatch.setattr(ai._Analisis, "_leer_manifest", explotar)
    payload = ai.analyze_addons(str(base))
    error = buscar(payload, "ITEM_ANALYSIS_ERROR")
    assert len(error) == 1 and error[0]["severity"] == "error"
    assert pack_por_id(payload, "behavior_packs/Uno")["status"] == "ok"
    assert pack_por_id(payload, "behavior_packs/Dos")["status"] == "ok"
    assert payload["complete"] is False


# ---------------------------------------------------------------------------
# Determinismo, no modificacion y arquitectura
# ---------------------------------------------------------------------------

def test_el_analisis_no_modifica_la_instalacion(tmp_path):
    base = instalar_base(tmp_path, mundos=("Alfa", "Beta"))
    escribir_pack(base, "behavior_packs/Uno", manifiesto(UUID_A))
    escribir_pack(base, "behavior_packs/Roto", texto="{ roto")
    escribir_pack(base, "behavior_packs/Enlazado", manifiesto(UUID_B))
    escribir_pack(base, "resource_packs/RP", manifiesto(UUID_C, tipo_modulo="resources"))
    escribir_pack(base, "worlds/Alfa/behavior_packs/Propio", manifiesto(UUID_D))
    escribir_refs(base, "Alfa", behavior=[{"pack_id": UUID_A, "version": [1, 0, 0]}])
    (base / "behavior_packs" / "Empaquetado.mcpack").write_bytes(b"PK")
    antes = snapshot_arbol(str(base))
    primera = ai.analyze_addons(str(base))
    segunda = ai.analyze_addons(str(base))
    despues = snapshot_arbol(str(base))
    assert antes == despues, "el analizador modifico archivos de la instalacion"
    assert json.dumps(primera, sort_keys=True) == json.dumps(segunda, sort_keys=True)


def test_payload_determinista_y_serializable(tmp_path):
    base = instalar_base(tmp_path)
    escribir_pack(base, "behavior_packs/B", manifiesto(UUID_B))
    escribir_pack(base, "behavior_packs/A", manifiesto(UUID_A))
    payload = ai.analyze_addons(str(base))
    # Orden estable: packs por ambito+carpeta, mundos por nombre.
    assert [p["folder"] for p in payload["packs"]] == ["behavior_packs/A", "behavior_packs/B"]
    texto = json.dumps(payload, ensure_ascii=False)
    assert json.loads(texto) == payload
    assert "generado" not in texto and "timestamp" not in texto
    # Los diagnosticos van ordenados por gravedad y luego por codigo/archivo.
    claves = [(ai._ORDEN_SEVERIDAD[d["severity"]], d["code"], d["source_file"])
              for d in payload["diagnostics"]]
    assert claves == sorted(claves)


def test_el_analizador_no_depende_de_fastapi():
    """Debe poder compartirse con la CLI sin arrastrar la GUI."""
    with open(os.path.join(RAIZ, "addon_inventory.py"), encoding="utf-8") as f:
        arbol = ast.parse(f.read())
    modulos = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            modulos.update(alias.name.split(".")[0] for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.module:
            modulos.add(nodo.module.split(".")[0])
    assert not ({"fastapi", "starlette", "uvicorn"} & modulos), modulos
    assert {"json", "os", "re"} <= modulos
    # Y la CLI importa el mismo analizador (fuente unica).
    with open(os.path.join(RAIZ, "addon_inventory_cli.py"), encoding="utf-8") as f:
        fuente = f.read()
    assert "import addon_inventory" in fuente


def test_reutiliza_la_deteccion_de_reparse_del_pipeline_de_backups(tmp_path):
    """Anti-duplicacion: la deteccion de junctions es la de auto_backup."""
    import auto_backup

    base = instalar_base(tmp_path)
    escribir_pack(base, "behavior_packs/Uno", manifiesto(UUID_A))
    escribir_pack(base, "worlds/Alfa/behavior_packs/Propio", manifiesto(UUID_B))
    llamadas = []
    original = auto_backup._es_punto_reparse

    def espiar(ruta):
        llamadas.append(ruta)
        return original(ruta)

    auto_backup._es_punto_reparse = espiar
    try:
        payload = ai.analyze_addons(str(base))
    finally:
        auto_backup._es_punto_reparse = original
    assert llamadas, "el analizador no usa auto_backup._es_punto_reparse"
    assert payload["summary"]["packs_total"] == 2


# ---------------------------------------------------------------------------
# Filtro de vista compartido con la CLI (fixture comun con el frontend)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def payload_fixture():
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def _ids(payload):
    return [p["id"] for p in payload["packs"]]


def test_filter_payload_sin_filtros_devuelve_el_mismo_objeto(payload_fixture):
    assert ai.filter_payload(payload_fixture) is payload_fixture


def test_filter_payload_por_mundo(payload_fixture):
    vista = ai.filter_payload(payload_fixture, world="Alfa")
    assert _ids(vista) == [
        "behavior_packs/CompartidoBP",
        "system_behavior_packs/SysBP",
        "worlds/Alfa/behavior_packs/AlfaBP",
        "resource_packs/CompartidoRes",
    ]
    assert [w["name"] for w in vista["worlds"]] == ["Alfa"]
    assert [d["code"] for d in vista["diagnostics"]] == ["UNO", "TRES", "CUATRO"]
    assert vista["filter"] == {"world": "Alfa", "kind": None}
    assert vista["summary_installation"] == payload_fixture["summary"]


def test_filter_payload_por_tipo(payload_fixture):
    vista = ai.filter_payload(payload_fixture, kind="behavior")
    assert _ids(vista) == [
        "behavior_packs/CompartidoBP",
        "system_behavior_packs/SysBP",
        "worlds/Alfa/behavior_packs/AlfaBP",
        "worlds/Beta/behavior_packs/BetaBP",
    ]
    assert [w["name"] for w in vista["worlds"]] == ["Alfa", "Beta"]
    assert [d["code"] for d in vista["diagnostics"]] == ["UNO", "DOS", "TRES", "CUATRO"]


def test_filter_payload_mundo_y_tipo_descarta_diagnosticos_ajenos(payload_fixture):
    vista = ai.filter_payload(payload_fixture, world="Beta", kind="resource")
    assert _ids(vista) == ["resource_packs/CompartidoRes"]
    assert [d["code"] for d in vista["diagnostics"]] == ["TRES"]
    assert vista["summary"]["packs_total"] == 1
    assert vista["summary"]["diagnosticos_total"] == 1


def test_filter_payload_tipo_desconocido_no_filtra(payload_fixture):
    vista = ai.filter_payload(payload_fixture, kind="inexistente")
    assert _ids(vista) == _ids(payload_fixture)
