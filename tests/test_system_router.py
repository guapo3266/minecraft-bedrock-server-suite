# -*- coding: utf-8 -*-
"""Router de sistema: /, /favicon.svg y las ramas de POST /api/command.

Complementa a los tests de stop (que ya cubren el camino con stdin sano):
aqui se fijan vacio, apagado, error de entrega y los estaticos basicos.
"""

from fastapi.testclient import TestClient

import server_gui_server as sgs
from gui_backend.state import manager

_CLIENTE_LOCAL = ("127.0.0.1", 50000)


def _client():
    return TestClient(sgs.app, client=_CLIENTE_LOCAL, raise_server_exceptions=False)


class _ProcRoto:
    """Wrapper presente pero con stdin roto (poll dice vivo)."""

    def __init__(self):
        self.stdin = self

    def write(self, _s):
        raise BrokenPipeError("tuberia rota")

    def flush(self):
        pass

    def poll(self):
        return None


def test_root_y_favicon_responden_200():
    client = _client()
    assert client.get("/").status_code == 200
    assert client.get("/favicon.svg").status_code == 200


def test_command_vacio_200_sin_logs(monkeypatch):
    monkeypatch.setattr(manager, "is_running", False)
    monkeypatch.setattr(manager, "wrapper_process", None)
    with manager.lock:
        n0 = len(manager.log_history)

    r = _client().post("/api/command", json={"command": "   "})

    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    with manager.lock:
        assert len(manager.log_history) == n0


def test_command_offline_200_con_dos_logs(monkeypatch):
    monkeypatch.setattr(manager, "is_running", False)
    monkeypatch.setattr(manager, "wrapper_process", None)

    r = _client().post("/api/command", json={"command": "list"})

    assert r.status_code == 200
    assert r.json()["status"] == "offline"
    with manager.lock:
        textos = [e["text"] for e in manager.log_history]
    assert any(t.startswith("> list") for t in textos)
    assert any("APAGADO" in t or "OFF" in t for t in textos)


def test_command_stdin_roto_200_error(monkeypatch):
    monkeypatch.setattr(manager, "is_running", True)
    monkeypatch.setattr(manager, "wrapper_process", _ProcRoto())

    r = _client().post("/api/command", json={"command": "say hola"})

    assert r.status_code == 200
    assert r.json()["status"] == "error"
    with manager.lock:
        textos = [e["text"] for e in manager.log_history]
    assert any("Error enviando comando" in t or "Error sending command" in t for t in textos)
