# -*- coding: utf-8 -*-
"""Guardas del router de acciones: errores de entrega y estados ocupados.

Complementa a los tests de start/stop/update existentes con el camino
caliente roto, rollback sin version previa y update ya en curso.
"""
from fastapi.testclient import TestClient

import server_gui_server as sgs
from gui_backend.services import bds_update as bds_update_service
from gui_backend.state import manager

_CLIENTE_LOCAL = ("127.0.0.1", 50000)


def _client():
    return TestClient(sgs.app, client=_CLIENTE_LOCAL, raise_server_exceptions=False)


class _StdinRoto:
    def write(self, _s):
        raise BrokenPipeError("tuberia rota")

    def flush(self):
        pass


class _ProcRoto:
    def __init__(self):
        self.stdin = _StdinRoto()

    def poll(self):
        return None


def test_backup_caliente_con_stdin_roto_500(monkeypatch):
    monkeypatch.setattr(manager, "is_running", True)
    monkeypatch.setattr(manager, "wrapper_process", _ProcRoto())

    r = _client().post("/api/action/backup")

    assert r.status_code == 500
    assert "backup" in r.json()["detail"].lower()


def test_update_bds_ya_en_curso(monkeypatch):
    monkeypatch.setattr(manager, "update_in_progress", True)
    monkeypatch.setattr(manager, "is_running", False)

    r = _client().post("/api/action/update_bds")

    assert r.status_code == 200
    assert r.json()["status"] == "already_updating"


def test_rollback_sin_version_previa_409(monkeypatch):
    monkeypatch.setattr(manager, "update_in_progress", False)
    monkeypatch.setattr(manager, "is_running", False)
    monkeypatch.setattr(bds_update_service, "read_previous_version",
                        lambda: (False, None))

    r = _client().post("/api/action/rollback_bds")

    assert r.status_code == 409
    assert "versión anterior" in r.json()["detail"]
