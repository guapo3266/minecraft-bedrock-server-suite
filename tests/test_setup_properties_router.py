# -*- coding: utf-8 -*-
"""Ramas de error del router de setup y del editor de properties."""

import time

from fastapi.testclient import TestClient

import server_gui_server as sgs
from gui_backend import config
from gui_backend.services import bds_update as bu
from gui_backend.state import manager


def _client():
    return TestClient(sgs.app, client=("127.0.0.1", 50000), raise_server_exceptions=False)


def test_complete_falla_al_escribir_marcador_500(tmp_path, monkeypatch):
    exe = tmp_path / "bedrock_server.exe"
    exe.write_bytes(b"x")
    monkeypatch.setattr(config, "SERVER_EXE", str(exe))
    marcador_dir = tmp_path / "marcador_dir"
    marcador_dir.mkdir()
    monkeypatch.setattr(config, "SETUP_MARKER", str(marcador_dir))

    r = _client().post("/api/setup/complete")

    assert r.status_code == 500
    assert "marcador" in r.json()["detail"]


def test_install_bds_excepcion_loguea_y_libera_lock(monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("fallo de red")

    monkeypatch.setattr(bu, "_download_and_install_bds", _boom)
    monkeypatch.setattr(manager, "is_running", False)
    logs = []
    monkeypatch.setattr(manager, "add_log", lambda *a, **k: logs.append(a[0]))

    r = _client().post("/api/setup/install_bds")
    assert r.status_code == 200
    assert r.json()["status"] == "install_dispatched"

    deadline = time.time() + 5
    while time.time() < deadline:
        if any("Error durante la instalacion" in x or "Error during installation" in x
               for x in logs):
            break
        time.sleep(0.05)

    assert any("Error durante la instalacion" in x or "Error during installation" in x
               for x in logs), logs
    assert manager.op_lock.locked() is False


def test_server_properties_json_invalido_400():
    r = _client().post(
        "/api/server_properties", content=b"no-json",
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 400


def test_server_properties_escritura_valida(tmp_path, monkeypatch):
    props = tmp_path / "server.properties"
    props.write_text("server-name=Antes\n", encoding="utf-8")
    monkeypatch.setattr(config, "PROPS_PATH", str(props))

    r = _client().post("/api/server_properties", json={"values": {"server-name": "Despues"}})

    assert r.status_code == 200
    assert r.json()["written"] == ["server-name"]
    assert "server-name=Despues" in props.read_text(encoding="utf-8")
