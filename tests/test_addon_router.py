# -*- coding: utf-8 -*-
"""Tests del endpoint GET /api/addons y de la equivalencia CLI <-> GUI.

El endpoint delega en `gui_backend.services.addons`, que a su vez usa el mismo
analizador que la CLI: aqui se fija por test que ambos consumidores devuelven
EXACTAMENTE el mismo payload para la misma instalacion (requisito 7) y que el
analisis es de solo lectura.

Nota sobre httpx: se importa TestClient de forma directa a proposito. Si httpx
faltara, el test debe FALLAR (no saltarse en silencio), porque es la unica
cobertura HTTP real de este contrato.
"""

import json
import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import addon_inventory  # noqa: E402
import server_gui_server as sgs  # noqa: E402
from gui_backend import config  # noqa: E402
from gui_backend.services import addons as addons_service  # noqa: E402

UUID_A = "aaaaaaaa-1111-4111-8111-111111111111"
UUID_B = "bbbbbbbb-2222-4222-8222-222222222222"


def _manifiesto(uuid, version=(1, 0, 0), nombre="Pack", tipo="data"):
    return {
        "format_version": 2,
        "header": {"name": nombre, "description": "d", "uuid": uuid,
                   "version": list(version), "min_engine_version": [1, 20, 0]},
        "modules": [{"type": tipo, "uuid": uuid, "version": list(version)}],
    }


def _instalacion(base):
    base.mkdir(parents=True, exist_ok=True)
    (base / "server.properties").write_text("level-name=Alfa\n", encoding="utf-8")
    for mundo in ("Alfa", "Beta"):
        carpeta = base / "worlds" / mundo
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "level.dat").write_bytes(b"x")
    for rel, datos in (
        ("behavior_packs/BPSano", _manifiesto(UUID_A, nombre="BP Sano")),
        ("resource_packs/RPSano", _manifiesto(UUID_B, nombre="RP Sano", tipo="resources")),
    ):
        carpeta = base / rel
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "manifest.json").write_text(json.dumps(datos), encoding="utf-8")
    (base / "worlds" / "Alfa" / "world_behavior_packs.json").write_text(
        json.dumps([{"pack_id": UUID_A, "version": [1, 0, 0]}]), encoding="utf-8")
    (base / "worlds" / "Alfa" / "world_resource_packs.json").write_text(
        json.dumps([{"pack_id": UUID_B, "version": [1, 0, 0]}]), encoding="utf-8")
    return base


@pytest.fixture()
def instalacion_temporal(tmp_path, monkeypatch):
    """Apunta el servicio a una instalacion temporal (nunca a la real)."""
    base = _instalacion(tmp_path / "instalacion")
    monkeypatch.setattr(config, "BASE_DIR", str(base))
    return base


def _cli_json(base):
    resultado = subprocess.run(
        [sys.executable, os.path.join(RAIZ, "addon_inventory_cli.py"),
         "--root", str(base), "--json"],
        cwd=RAIZ, capture_output=True, text=True, encoding="utf-8",
    )
    assert resultado.stdout, resultado.stderr
    return json.loads(resultado.stdout)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

def test_get_addons_devuelve_el_inventario_de_la_instalacion(instalacion_temporal):
    client = TestClient(sgs.app, client=('127.0.0.1', 50000))
    respuesta = client.get("/api/addons")
    assert respuesta.status_code == 200
    datos = respuesta.json()
    esperado = addon_inventory.analyze_addons(str(instalacion_temporal))
    assert datos == esperado
    assert datos["schema_version"] == 1
    assert datos["summary"]["packs_total"] == 2
    assert {p["name"] for p in datos["packs"]} == {"BP Sano", "RP Sano"}
    mundo = next(w for w in datos["worlds"] if w["name"] == "Alfa")
    assert [r["status"] for r in mundo["references"]] == ["resolved", "resolved"]


def test_get_addons_es_solo_lectura(instalacion_temporal):
    def huella():
        resultado = {}
        for raiz, _dirs, archivos in os.walk(str(instalacion_temporal)):
            for nombre in archivos:
                ruta = os.path.join(raiz, nombre)
                st = os.stat(ruta)
                resultado[os.path.relpath(ruta, str(instalacion_temporal))] = (
                    st.st_size, st.st_mtime_ns)
        return resultado

    antes = huella()
    client = TestClient(sgs.app, client=('127.0.0.1', 50000))
    for _ in range(2):
        assert client.get("/api/addons").status_code == 200
    assert huella() == antes


def test_filtro_por_tipo(instalacion_temporal):
    client = TestClient(sgs.app, client=('127.0.0.1', 50000))
    datos = client.get("/api/addons", params={"kind": "behavior"}).json()
    assert datos["filter"] == {"world": None, "kind": "behavior"}
    assert [p["kind"] for p in datos["packs"]] == ["behavior"]
    assert datos == addon_inventory.filter_payload(
        addon_inventory.analyze_addons(str(instalacion_temporal)), kind="behavior")


def test_filtro_por_mundo(instalacion_temporal):
    client = TestClient(sgs.app, client=('127.0.0.1', 50000))
    datos = client.get("/api/addons", params={"world": "Alfa"}).json()
    assert datos["filter"] == {"world": "Alfa", "kind": None}
    assert [w["name"] for w in datos["worlds"]] == ["Alfa"]
    assert [p["id"] for p in datos["packs"]] == [
        "behavior_packs/BPSano", "resource_packs/RPSano"]


def test_tipo_invalido_devuelve_400(instalacion_temporal):
    client = TestClient(sgs.app, client=('127.0.0.1', 50000))
    respuesta = client.get("/api/addons", params={"kind": "inventado"})
    assert respuesta.status_code == 400
    assert "behavior" in respuesta.json()["detail"]


def test_mundo_desconocido_devuelve_400(instalacion_temporal):
    client = TestClient(sgs.app, client=('127.0.0.1', 50000))
    respuesta = client.get("/api/addons", params={"world": "NoExiste"})
    assert respuesta.status_code == 400
    assert "NoExiste" in respuesta.json()["detail"]


def test_el_router_no_ejecuta_el_analisis_en_el_event_loop():
    """El escaneo es I/O de disco: debe correr en el threadpool (no congelar WS)."""
    with open(os.path.join(RAIZ, "gui_backend", "routers", "addons.py"),
              encoding="utf-8") as f:
        fuente = f.read()
    assert "run_in_threadpool" in fuente
    assert "await run_in_threadpool(addons_service.build_addons_view" in fuente
    # El servicio no conoce FastAPI (direccion de dependencias del proyecto).
    with open(os.path.join(RAIZ, "gui_backend", "services", "addons.py"),
              encoding="utf-8") as f:
        servicio = f.read()
    assert "fastapi" not in servicio and "Request" not in servicio


# ---------------------------------------------------------------------------
# Equivalencia CLI <-> GUI (requisito 7)
# ---------------------------------------------------------------------------

def test_cli_y_gui_producen_el_mismo_payload(instalacion_temporal):
    client = TestClient(sgs.app, client=('127.0.0.1', 50000))
    api = client.get("/api/addons").json()
    cli = _cli_json(instalacion_temporal)
    servicio = addons_service.build_addons_view()
    analizador = addon_inventory.analyze_addons(str(instalacion_temporal))
    assert api == cli == servicio == analizador


def test_cli_y_gui_equivalentes_con_filtros(instalacion_temporal):
    client = TestClient(sgs.app, client=('127.0.0.1', 50000))
    api = client.get("/api/addons", params={"world": "Alfa", "kind": "behavior"}).json()
    resultado = subprocess.run(
        [sys.executable, os.path.join(RAIZ, "addon_inventory_cli.py"),
         "--root", str(instalacion_temporal), "--json", "--world", "Alfa",
         "--kind", "behavior"],
        cwd=RAIZ, capture_output=True, text=True, encoding="utf-8",
    )
    assert json.loads(resultado.stdout) == api


def test_payload_equivalente_con_hallazgos_y_parcial(tmp_path, monkeypatch):
    base = _instalacion(tmp_path / "con-hallazgos")
    carpeta = base / "behavior_packs" / "Roto"
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "manifest.json").write_text("{ roto", encoding="utf-8")
    (base / "worlds" / "Beta" / "world_behavior_packs.json").write_text(
        json.dumps([{"pack_id": "00000000-9999-4999-8999-999999999999",
                     "version": [1, 0, 0]}]), encoding="utf-8")
    monkeypatch.setattr(config, "BASE_DIR", str(base))
    client = TestClient(sgs.app, client=('127.0.0.1', 50000))
    api = client.get("/api/addons").json()
    assert api["complete"] is False
    assert api == _cli_json(base)
    codigos = {d["code"] for d in api["diagnostics"]}
    assert {"MANIFEST_JSON_INVALID", "WORLD_REF_UNRESOLVED"} <= codigos


def test_instalacion_real_del_repositorio_se_analiza():
    """El endpoint responde tambien sobre la instalacion del repo (solo lectura)."""
    client = TestClient(sgs.app, client=('127.0.0.1', 50000))
    respuesta = client.get("/api/addons")
    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["base_dir"] == os.path.abspath(config.BASE_DIR)
    assert datos["summary"]["packs_total"] == len(datos["packs"])
    assert datos["supported"]["manifest_format_versions"] == [2]
    import server_properties

    esperado = server_properties.read_value(
        os.path.join(config.BASE_DIR, "server.properties"), "level-name")
    assert datos["active_world"] == esperado
