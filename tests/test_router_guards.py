"""Red de seguridad de las guardas HTTP del backend.

Fija por test la invariante "todo endpoint de la API exige cliente local; todo
endpoint mutante exige además Origin permitido". Si se agrega una ruta nueva,
`test_cobertura_*` falla y obliga a sumarla a las sondas: la guarda deja de
depender de la memoria de quien la escribió.

Contexto: la GUI escucha en loopback, pero un navegador en la misma máquina
puede intentar CSRF contra 127.0.0.1; de ahí el doble control
(`security._ensure_local` + `security._check_origin`).
"""

import pytest
from fastapi.testclient import TestClient

import server_gui_server as sgs

# Plantilla de ruta (la del app) -> URL concreta para sondear.
_POST_PROBES = {
    "/api/action/{action_name}": "/api/action/start",
    "/api/restore": "/api/restore",
    "/api/backups/{filename}/delete": "/api/backups/dummy.zip/delete",
    "/api/backups/{filename}/verify": "/api/backups/dummy.zip/verify",
    "/api/server_properties": "/api/server_properties",
    "/api/schedule": "/api/schedule",
    "/api/setup/install_bds": "/api/setup/install_bds",
    "/api/setup/complete": "/api/setup/complete",
    "/api/command": "/api/command",
}

_GET_PROBES = {
    "/api/status": "/api/status",
    "/api/connectivity": "/api/connectivity",
    "/api/check_update": "/api/check_update",
    "/api/backups": "/api/backups",
    "/api/backups/{filename}/download": "/api/backups/dummy.zip/download",
    "/api/players": "/api/players",
    "/api/server_properties": "/api/server_properties",
    "/api/schedule": "/api/schedule",
    "/api/setup_status": "/api/setup_status",
    "/api/history/metrics": "/api/history/metrics",
    "/api/history/logs": "/api/history/logs",
    "/api/history/sessions": "/api/history/sessions",
}

_FUERA_DE_API = ("10.0.0.1", 50000)


def _openapi_paths():
    # FastAPI reciente envuelve los routers incluidos en `_IncludedRouter` y
    # `app.routes` ya no los aplana; el esquema OpenAPI sí expone el inventario.
    return sgs.app.openapi()["paths"]


def _route_templates(method):
    return {
        path for path, ops in _openapi_paths().items() if method in ops
    }


def _api_get_templates():
    return {
        p for p in _route_templates("get") if p.startswith("/api/")
    }


def test_cobertura_de_rutas_post():
    assert _route_templates("post") == set(_POST_PROBES), (
        "hay rutas POST nuevas o eliminadas: actualizar _POST_PROBES y verificar "
        "que pasan por la guarda temprana de /api/* (server_gui_server)"
    )


def test_cobertura_de_rutas_get_de_api():
    assert _api_get_templates() == set(_GET_PROBES), (        "hay rutas GET /api/ nuevas o eliminadas: actualizar _GET_PROBES y "
        "verificar que pasan por la guarda temprana de /api/* (server_gui_server)"
    )


@pytest.mark.parametrize("path", sorted(_POST_PROBES.values()))
def test_post_rechaza_cliente_no_local(path):
    client = TestClient(sgs.app, client=_FUERA_DE_API, raise_server_exceptions=False)
    r = client.post(path, json={})
    assert r.status_code == 403, (path, r.status_code, r.text[:200])


@pytest.mark.parametrize("path", sorted(_POST_PROBES.values()))
def test_post_rechaza_origin_externo(path):
    client = TestClient(sgs.app, client=("127.0.0.1", 50000), raise_server_exceptions=False)
    r = client.post(path, json={}, headers={"origin": "http://evil.example"})
    assert r.status_code == 403, (path, r.status_code, r.text[:200])


def test_guarda_corre_antes_de_la_validacion_del_body():
    """Un body invalido de un cliente externo debe dar 403, no 422: la guarda
    es middleware, no un chequeo dentro del endpoint (que corre despues de
    pydantic y permitia enumerar el esquema). Regresion del hallazgo del
    inventario de rutas."""
    client = TestClient(sgs.app, client=_FUERA_DE_API, raise_server_exceptions=False)
    r = client.post("/api/command", content=b"no-json")
    assert r.status_code == 403, (r.status_code, r.text[:200])


@pytest.mark.parametrize("path", sorted(_GET_PROBES.values()))
def test_get_api_rechaza_cliente_no_local(path):
    client = TestClient(sgs.app, client=_FUERA_DE_API, raise_server_exceptions=False)
    r = client.get(path)
    assert r.status_code == 403, (path, r.status_code, r.text[:200])
