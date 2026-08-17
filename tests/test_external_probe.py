# -*- coding: utf-8 -*-
"""Pruebas unitarias para la sonda de instancias externas (detect_external_bds)."""

import os
import sys
import psutil
import pytest
from starlette.testclient import TestClient

import server_gui_server as sgs
from gui_backend import config
from gui_backend.services import external_probe
import windows_process_guard as wpg


def test_detect_external_bds_no_detecta_cuando_no_hay_procesos(monkeypatch):
    """Sin mutex ni procesos externos, detect_external_bds retorna (False, None)."""
    sgs.manager.is_running = False
    monkeypatch.setattr(wpg.NamedMutex, "__init__", lambda self, name: setattr(self, "already_exists", False) or setattr(self, "handle", None))
    monkeypatch.setattr(wpg.NamedMutex, "close", lambda self: None)
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: [])

    is_ext, reason = external_probe.detect_external_bds()
    assert is_ext is False
    assert reason is None


def test_detect_external_bds_detecta_mutex_retenido_por_wrapper(monkeypatch):
    """Si otro proceso RETIENE el mutex del wrapper (wrapper vivo), detecta
    wrapper_mutex. Regresion: el sondeo por existencia (CreateMutexW +
    ERROR_ALREADY_EXISTS) daba falsos positivos cuando otra instancia solo
    tenia el mutex abierto un instante para sondearlo (p. ej. el loop de
    metricas de otra GUI de la misma instalacion)."""
    sgs.manager.is_running = False
    monkeypatch.setattr(wpg.NamedMutex, "__init__", lambda self, name: setattr(self, "already_exists", False) or setattr(self, "handle", None))
    monkeypatch.setattr(wpg.NamedMutex, "close", lambda self: None)
    monkeypatch.setattr(wpg.NamedMutex, "acquire", lambda self, timeout_ms=0: False)
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: [])

    is_ext, reason = external_probe.detect_external_bds()
    assert is_ext is True
    assert reason == "wrapper_mutex"

    # Si la GUI ya está corriendo, no debe reportar externo
    sgs.manager.is_running = True
    is_ext, reason = external_probe.detect_external_bds()
    assert is_ext is False
    sgs.manager.is_running = False


def test_detect_external_bds_no_confunde_probe_ajeno_con_wrapper(monkeypatch):
    """Regresion: otro probe que retenga el mutex solo un instante (colision
    entre dos sondeos) NO es una instancia externa: el reintento corto del
    probe por adquisicion lo resuelve."""
    sgs.manager.is_running = False
    monkeypatch.setattr(wpg.NamedMutex, "__init__", lambda self, name: setattr(self, "already_exists", False) or setattr(self, "handle", None))
    monkeypatch.setattr(wpg.NamedMutex, "close", lambda self: None)
    calls = {"n": 0}

    def flaky_acquire(self, timeout_ms=0):
        calls["n"] += 1
        return calls["n"] > 1  # 1er intento: colision con el otro probe

    monkeypatch.setattr(wpg.NamedMutex, "acquire", flaky_acquire)
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: [])

    is_ext, reason = external_probe.detect_external_bds()
    assert is_ext is False
    assert reason is None


def test_detect_external_bds_detecta_proceso_psutil_no_hijo(monkeypatch):
    """Detecta proceso bedrock_server (de ESTA instalacion) que no es hijo ni
    descendiente de la GUI."""
    sgs.manager.is_running = False
    monkeypatch.setattr(wpg.NamedMutex, "__init__", lambda self, name: setattr(self, "already_exists", False) or setattr(self, "handle", None))
    monkeypatch.setattr(wpg.NamedMutex, "close", lambda self: None)

    class FakeProc:
        def __init__(self, pid, name):
            self.pid = pid
            self.info = {"pid": pid, "name": name}
        def parent(self):
            return None
        def exe(self):
            return os.path.join(config.BASE_DIR, "bedrock_server.exe")

    fake_external = FakeProc(99999, "bedrock_server.exe")
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: [fake_external])
    monkeypatch.setattr(psutil, "Process", lambda pid: fake_external)

    is_ext, reason = external_probe.detect_external_bds()
    assert is_ext is True
    assert "bedrock_server_pid_99999" in reason


def test_detect_external_bds_ignora_bds_de_otra_instalacion(monkeypatch):
    """Regresion: un bedrock_server.exe cuyo ejecutable pertenece a OTRA
    instalacion (otra ruta) no debe bloquear start/update/restore de esta:
    el falso positivo obligaba a lifecycle.restart_wrapper a esquivar la
    sonda tras cada stop."""
    sgs.manager.is_running = False
    monkeypatch.setattr(wpg.NamedMutex, "__init__", lambda self, name: setattr(self, "already_exists", False) or setattr(self, "handle", None))
    monkeypatch.setattr(wpg.NamedMutex, "close", lambda self: None)

    class FakeProc:
        def __init__(self, pid, name):
            self.pid = pid
            self.info = {"pid": pid, "name": name}
        def parent(self):
            return None
        def exe(self):
            return r"C:\otra\instalacion\bedrock_server.exe"

    fake_foreign = FakeProc(77777, "bedrock_server.exe")
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: [fake_foreign])
    monkeypatch.setattr(psutil, "Process", lambda pid: fake_foreign)

    is_ext, reason = external_probe.detect_external_bds()
    assert is_ext is False
    assert reason is None


def test_detect_external_bds_ignora_hijos_de_la_gui(monkeypatch):
    """Ignora procesos bedrock_server que sean descendientes del PID de la GUI."""
    sgs.manager.is_running = False
    gui_pid = os.getpid()
    monkeypatch.setattr(wpg.NamedMutex, "__init__", lambda self, name: setattr(self, "already_exists", False) or setattr(self, "handle", None))
    monkeypatch.setattr(wpg.NamedMutex, "close", lambda self: None)

    class FakeParent:
        def __init__(self, pid):
            self.pid = pid
        def parent(self):
            return None

    class FakeChildProc:
        def __init__(self, pid, name):
            self.pid = pid
            self.info = {"pid": pid, "name": name}
        def parent(self):
            return FakeParent(gui_pid)

    child_proc = FakeChildProc(88888, "bedrock_server.exe")
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: [child_proc])
    monkeypatch.setattr(psutil, "Process", lambda pid: child_proc)

    is_ext, reason = external_probe.detect_external_bds()
    assert is_ext is False
    assert reason is None


def test_endpoints_devuelven_409_con_instancia_externa(monkeypatch, tmp_path):
    """start, update_bds y restore devuelven HTTP 409 si hay instancia externa detectada."""
    sgs.manager.is_running = False
    monkeypatch.setattr(external_probe, "detect_external_bds", lambda *args, **kwargs: (True, "wrapper_mutex"))

    with TestClient(sgs.app, client=("127.0.0.1", 50000)) as client:
        # 1. /api/action/start -> 409
        resp_start = client.post("/api/action/start")
        assert resp_start.status_code == 409

        # 2. /api/action/update_bds -> 409
        resp_update = client.post("/api/action/update_bds")
        assert resp_update.status_code == 409

        # 3. /api/restore -> 409
        resp_restore = client.post("/api/restore", json={"filename": "backup_dummy.zip"})
        assert resp_restore.status_code == 409


def test_status_y_polling_incluyen_external_instance(monkeypatch):
    """/api/status incluye external_instance y external_instance_reason."""
    monkeypatch.setattr(external_probe, "detect_external_bds", lambda *args, **kwargs: (True, "test_reason"))
    external_probe.update_external_instance_state()

    with TestClient(sgs.app, client=("127.0.0.1", 50000)) as client:
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["external_instance"] is True
        assert data["external_instance_reason"] == "test_reason"
