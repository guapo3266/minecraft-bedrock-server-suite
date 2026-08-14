# -*- coding: utf-8 -*-
"""Tests del endpoint de conectividad (GET /api/connectivity).

Cubren:
- Devuelve lan_ip, public_ip y el puerto de server.properties.
- Sin internet: public_ip null con 200 (la GUI muestra "no se pudo detectar").
- Cache de IP publica: segunda llamada no repite la consulta externa;
  refresh=1 fuerza.
- Cadena de fallback de _fetch_public_ip (primer servicio caido -> segundo).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server_gui_server as sgs
import gui_backend.config as config
import gui_backend.routers.system as system_router

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_connectivity_devuelve_datos(monkeypatch, tmp_path):
    props = tmp_path / "server.properties"
    props.write_text("server-name=Test\nserver-port=19140\n", encoding="utf-8")
    monkeypatch.setattr(config, "PROPS_PATH", str(props))
    monkeypatch.setattr(system_router, "_get_lan_ip", lambda: "192.168.1.50")
    monkeypatch.setattr(system_router, "_get_public_ip_cached", lambda force=False: "203.0.113.9")

    from fastapi.testclient import TestClient
    with TestClient(sgs.app, client=("127.0.0.1", 50000)) as c:
        j = c.get("/api/connectivity").json()
    assert j["lan_ip"] == "192.168.1.50"
    assert j["public_ip"] == "203.0.113.9"
    assert j["port"] == "19140"


def test_connectivity_sin_internet(monkeypatch, tmp_path):
    props = tmp_path / "server.properties"
    props.write_text("server-port=19132\n", encoding="utf-8")
    monkeypatch.setattr(config, "PROPS_PATH", str(props))
    monkeypatch.setattr(system_router, "_get_lan_ip", lambda: "127.0.0.1")
    monkeypatch.setattr(system_router, "_fetch_public_ip", lambda: None)
    # fuerza consulta en frio: resultado null, pero el endpoint responde 200
    monkeypatch.setattr(system_router, "_conn_cache", {"at": 0.0, "public_ip": None})

    from fastapi.testclient import TestClient
    with TestClient(sgs.app, client=("127.0.0.1", 50000)) as c:
        r = c.get("/api/connectivity")
        assert r.status_code == 200
        j = r.json()
    assert j["public_ip"] is None
    assert j["port"] == "19132"


def test_cache_public_ip(monkeypatch):
    llamadas = {"n": 0}

    def fake_fetch():
        llamadas["n"] += 1
        return "203.0.113.5"

    monkeypatch.setattr(system_router, "_fetch_public_ip", fake_fetch)
    monkeypatch.setattr(system_router, "_conn_cache", {"at": 0.0, "public_ip": None})

    assert system_router._get_public_ip_cached() == "203.0.113.5"
    assert system_router._get_public_ip_cached() == "203.0.113.5"
    assert llamadas["n"] == 1, "segunda llamada en cache no debe consultar"
    assert system_router._get_public_ip_cached(force=True) == "203.0.113.5"
    assert llamadas["n"] == 2, "force=True debe reconsultar"


def test_fetch_public_ip_fallback(monkeypatch):
    """Primer servicio falla (timeout): usa el segundo de la cadena."""
    orden = {"n": 0}

    class FakeResp:
        def __init__(self, text):
            self.status_code = 200
            self._text = text

        @property
        def text(self):
            return self._text

    def fake_get(url, timeout=4):
        orden["n"] += 1
        if orden["n"] == 1:
            raise OSError("sin red")
        assert url == "https://ifconfig.me/ip"
        return FakeResp("198.51.100.7")

    monkeypatch.setattr(system_router.requests, "get", fake_get)
    assert system_router._fetch_public_ip() == "198.51.100.7"
    assert orden["n"] == 2


def test_fetch_public_ip_rechaza_respuesta_no_ip(monkeypatch):
    class FakeResp:
        status_code = 200
        text = "<html>no soy una ip</html>"

    monkeypatch.setattr(system_router.requests, "get", lambda url, timeout=4: FakeResp())
    assert system_router._fetch_public_ip() is None
