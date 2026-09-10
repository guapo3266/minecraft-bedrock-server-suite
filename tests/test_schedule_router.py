# -*- coding: utf-8 -*-
"""Router /api/schedule: validacion 400 y guardado 200 en tmp."""

import json

from fastapi.testclient import TestClient

import server_gui_server as sgs
from gui_backend.services import schedule_config as sc

_CLIENTE_LOCAL = ("127.0.0.1", 50000)


def _client():
    return TestClient(sgs.app, client=_CLIENTE_LOCAL, raise_server_exceptions=False)


def test_schedule_get_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "SCHEDULE_PATH", str(tmp_path / "no_existe.json"))
    r = _client().get("/api/schedule")
    assert r.status_code == 200
    assert r.json() == sc.DEFAULTS


def test_schedule_post_invalido_400(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "SCHEDULE_PATH", str(tmp_path / "s.json"))
    r = _client().post("/api/schedule", json={"backup_interval_min": 2})
    assert r.status_code == 400
    assert "entre 5 y 1440" in r.json()["detail"]


def test_schedule_post_valido_guarda_en_tmp(tmp_path, monkeypatch):
    path = tmp_path / "s.json"
    monkeypatch.setattr(sc, "SCHEDULE_PATH", str(path))

    r = _client().post("/api/schedule", json={
        "backup_interval_min": 15,
        "auto_restart_on_crash": True,
        "daily_backup_time": "04:00",
    })

    assert r.status_code == 200
    guardado = json.loads(path.read_text(encoding="utf-8"))
    assert guardado["backup_interval_min"] == 15
    assert guardado["auto_restart_on_crash"] is True
    assert guardado["daily_backup_time"] == "04:00"
