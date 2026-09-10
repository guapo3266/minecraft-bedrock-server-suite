# -*- coding: utf-8 -*-
"""El lifespan de la GUI sobrevive a fallos de arranque de sus servicios.

Cada recuperacion/servicio de arranque va en su propio try/except: un fallo
(p. ej. psutil, disco, watchdog) debe loguearse y la GUI seguir sirviendo.
"""
from fastapi.testclient import TestClient

import server_gui_server as sgs


def test_lifespan_loguea_fallos_de_arranque_y_sigue_sirviendo(monkeypatch):
    logs = []
    monkeypatch.setattr(sgs.manager, "add_log", lambda *a, **k: logs.append(a[0]))

    def _boom(*_a, **_k):
        raise RuntimeError("boom de arranque")

    monkeypatch.setattr(sgs.auto_backup, "recover_interrupted_restores", _boom)
    monkeypatch.setattr(sgs.bds_update_service, "recover_interrupted_updates", _boom)
    monkeypatch.setattr(sgs.watchdog_service, "start", _boom)
    monkeypatch.setattr(sgs.history_service, "start", _boom)

    with TestClient(sgs.app, client=("127.0.0.1", 50000)) as client:
        r = client.get("/api/status")
        assert r.status_code == 200

    assert len(logs) >= 4, logs
    texto = " ".join(str(x) for x in logs).lower()
    for claves in (
        ("recuperación", "recovery"),
        ("actualizacion", "update"),
        ("watchdog",),
        ("historial", "history"),
    ):
        assert any(c in texto for c in claves), (claves, texto)
