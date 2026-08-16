# -*- coding: utf-8 -*-
"""Rollback de version de BDS: resguardo persistente, swap simetrico y endpoint.

Todo opera en tmp: BASE_DIR/previous dir parcheados; nunca la instalacion real.
"""
import json
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gui_backend.config as config
import gui_backend.supervisor as supervisor
import gui_backend.services.bds_update as bds_update
import gui_backend.services.lifecycle as lifecycle
import server_gui_server as gui


def _reset_manager_state():
    gui.manager.is_running = False
    gui.manager.start_time = None
    gui.manager.wrapper_process = None
    gui.manager.update_in_progress = False
    gui.manager.backup_in_progress = False
    gui.manager.players_online.clear()
    gui.manager.wrapper_exit_event.set()
    gui.manager.server_stopped_event.set()


@pytest.fixture
def env(monkeypatch, tmp_path):
    base = str(tmp_path / "inst")
    os.makedirs(base)
    prev = os.path.join(str(tmp_path), "bds_previous")
    monkeypatch.setattr(bds_update, "PREVIOUS_VERSION_DIR", prev)
    # El stop_and_wait/apply usan config.BASE_DIR: apuntarlo a tmp
    monkeypatch.setattr(config, "BASE_DIR", base)
    _reset_manager_state()
    gui.manager.installed_version = None
    yield base, prev
    _reset_manager_state()


def _mk_staging(path, files):
    os.makedirs(path, exist_ok=True)
    for rel, content in files.items():
        target = os.path.join(path, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)


# ═══════════════════════════════════════════════════════════════════════
# Resguardo persistente
# ═══════════════════════════════════════════════════════════════════════
def test_apply_con_keep_prev_conserva_resguardo(env):
    base, prev = env
    _mk_staging(os.path.join(base, "staging"), {"bedrock_server.exe": "NUEVO"})
    with open(os.path.join(base, "bedrock_server.exe"), "w") as f:
        f.write("VIEJO")

    bds_update._apply_staged_update(
        os.path.join(base, "staging"), base,
        bds_update.PRESERVE_FILES, bds_update.PRESERVE_DIRS,
        keep_prev_dir=prev, prev_version="1.26.33.2",
    )

    with open(os.path.join(base, "bedrock_server.exe")) as f:
        assert f.read() == "NUEVO"
    # resguardo conservado: binario viejo + metadata, sin manifiesto
    with open(os.path.join(prev, "bedrock_server.exe")) as f:
        assert f.read() == "VIEJO"
    assert not os.path.exists(os.path.join(prev, ".bds_update_manifest.json"))
    with open(os.path.join(prev, "bds_previous.json")) as f:
        assert json.load(f)["version"] == "1.26.33.2"
    assert bds_update.read_previous_version() == (True, "1.26.33.2")


def test_apply_sin_keep_prev_borra_resguardo(env):
    """Comportamiento historico intacto cuando no se pide conservar."""
    base, prev = env
    _mk_staging(os.path.join(base, "staging"), {"a.dll": "n"})
    bds_update._apply_staged_update(
        os.path.join(base, "staging"), base,
        bds_update.PRESERVE_FILES, bds_update.PRESERVE_DIRS,
    )
    assert not os.path.exists(prev)
    assert not [d for d in os.listdir(base) if d.startswith("bds_update_prev_")]


def test_read_previous_version_tolerante(env):
    _base, prev = env
    assert bds_update.read_previous_version() == (False, None)  # ausente
    os.makedirs(prev)
    with open(os.path.join(prev, "bds_previous.json"), "w") as f:
        f.write("{corrupto")
    with open(os.path.join(prev, "exe.bin"), "w") as f:
        f.write("x")
    # metadata ilegible pero binarios presentes: aplicable, version desconocida
    assert bds_update.read_previous_version() == (True, None)
    # directorio SOLO con metadata (instalacion nueva): no hay version anterior
    os.remove(os.path.join(prev, "exe.bin"))
    assert bds_update.read_previous_version() == (False, None)


def test_fallo_en_apply_no_pisa_resguardo_previo(env):
    """Si la aplicacion falla, el backup existente debe quedar intacto (no se
    sobreescribe con un resguardo incompleto)."""
    base, prev = env
    os.makedirs(prev)
    with open(os.path.join(prev, "bedrock_server.exe"), "w") as f:
        f.write("RESPALDO_BUENO")
    _mk_staging(os.path.join(base, "staging"), {"a.dll": "1", "b.dll": "2"})
    with open(os.path.join(base, "a.dll"), "w") as f:
        f.write("viejo-a")

    real_replace = os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if "b.dll" in dst and "staging" in src:
            raise OSError("fallo a mitad")
        return real_replace(src, dst)

    original_replace = bds_update.os.replace
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(bds_update.os, "replace", flaky)
    try:
        with pytest.raises(OSError):
            bds_update._apply_staged_update(
                os.path.join(base, "staging"), base,
                bds_update.PRESERVE_FILES, bds_update.PRESERVE_DIRS,
                keep_prev_dir=prev, prev_version="9.9.9.9",
            )
    finally:
        monkeypatch.setattr(bds_update.os, "replace", original_replace)
        monkeypatch.undo()
    # a.dll restaurado y el resguardo bueno NO fue tocado
    with open(os.path.join(base, "a.dll")) as f:
        assert f.read() == "viejo-a"
    with open(os.path.join(prev, "bedrock_server.exe")) as f:
        assert f.read() == "RESPALDO_BUENO"


# ═══════════════════════════════════════════════════════════════════════
# Swap simétrico: rollback es aplicar el resguardo
# ═══════════════════════════════════════════════════════════════════════
def test_rollback_bds_swap_simetrico(env):
    base, prev = env
    # "instalacion" actual = version nueva; resguardo = version vieja
    with open(os.path.join(base, "bedrock_server.exe"), "w") as f:
        f.write("BINARIO_NUEVO")
    _mk_staging(prev, {"bedrock_server.exe": "BINARIO_VIEJO"})
    with open(os.path.join(prev, "bds_previous.json"), "w") as f:
        json.dump({"version": "1.26.30.1", "saved_at": "x"}, f)
    gui.manager.installed_version = "1.26.40.8"

    ok, version = bds_update.rollback_bds(log_fn=lambda *a, **k: None)
    assert ok and version == "1.26.30.1"
    with open(os.path.join(base, "bedrock_server.exe")) as f:
        assert f.read() == "BINARIO_VIEJO"
    assert gui.manager.installed_version == "1.26.30.1"
    # swap: el resguardo ahora contiene la version que se dejo de usar
    with open(os.path.join(prev, "bedrock_server.exe")) as f:
        assert f.read() == "BINARIO_NUEVO"
    assert bds_update.read_previous_version() == (True, "1.26.40.8")

    # deshacer el rollback = otro rollback
    ok, version = bds_update.rollback_bds(log_fn=lambda *a, **k: None)
    assert ok and version == "1.26.40.8"
    with open(os.path.join(base, "bedrock_server.exe")) as f:
        assert f.read() == "BINARIO_NUEVO"


def test_rollback_bds_sin_resguardo(env):
    ok, version = bds_update.rollback_bds(log_fn=lambda *a, **k: None)
    assert ok is False and version is None


# ═══════════════════════════════════════════════════════════════════════
# Endpoint
# ═══════════════════════════════════════════════════════════════════════
class _FakeStdin:
    def __init__(self):
        self.lines = []

    def write(self, s):
        self.lines.append(s)

    def flush(self):
        pass


class _FakeStdout:
    def readline(self):
        return ""


class _FakeProc:
    def __init__(self):
        self.stdin = _FakeStdin()
        self.stdout = _FakeStdout()

    def wait(self):
        return 0

    def poll(self):
        return None


def _post_rollback(client):
    return client.post("/api/action/rollback_bds")


def test_rollback_endpoint_sin_resguardo_409(env):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    _reset_manager_state()
    client = TestClient(gui.app, client=("127.0.0.1", 50000))
    r = _post_rollback(client)
    assert r.status_code == 409
    assert "versión anterior" in r.json()["detail"]


def test_rollback_endpoint_detiene_y_aplica(env, monkeypatch):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    base, prev = env
    _mk_staging(prev, {"bedrock_server.exe": "VIEJO"})
    with open(os.path.join(prev, "bds_previous.json"), "w") as f:
        json.dump({"version": "1.26.30.1"}, f)
    with open(os.path.join(base, "bedrock_server.exe"), "w") as f:
        f.write("NUEVO")

    # wrapper "corriendo": debe llegar el stop ANTES de aplicar
    fake_proc = _FakeProc()
    gui.manager.is_running = True
    gui.manager.wrapper_process = fake_proc
    gui.manager.wrapper_exit_event.clear()
    gui.manager.server_stopped_event.clear()

    orden = []
    monkeypatch.setattr(config, "SERVER_STOP_TIMEOUT_SEC", 2)
    monkeypatch.setattr(config, "WRAPPER_EXIT_TIMEOUT_SEC", 2)

    def fake_apply(staging, base_dir, pf, pd, keep_prev_dir=None, prev_version=None):
        orden.append(("apply", "stop" in str(fake_proc.stdin.lines)))

    monkeypatch.setattr(bds_update, "_apply_staged_update", fake_apply)

    client = TestClient(gui.app, client=("127.0.0.1", 50000))
    r = _post_rollback(client)
    assert r.json()["status"] == "rollback_dispatched"

    # simular muerte de BDS + wrapper para que el hilo termine
    gui.manager.server_stopped_event.set()
    gui.manager.wrapper_exit_event.set()

    deadline = time.time() + 5
    while time.time() < deadline and gui.manager.update_in_progress:
        time.sleep(0.05)
    assert gui.manager.update_in_progress is False
    assert orden == [("apply", True)]  # stop enviado antes de aplicar
    assert "stop\n" in fake_proc.stdin.lines
    assert gui.manager.stop_requested is True


def test_check_update_expone_previous(env, monkeypatch):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    base, prev = env
    _mk_staging(prev, {"bedrock_server.exe": "VIEJO"})
    with open(os.path.join(prev, "bds_previous.json"), "w") as f:
        json.dump({"version": "1.26.30.1"}, f)

    class _Resp:
        def __init__(self, payload):
            self._payload = payload
            self.headers = {}

        def json(self):
            return self._payload

        @property
        def text(self):
            return ""

    monkeypatch.setattr(bds_update.requests, "get", lambda *a, **k: _Resp(
        {"result": {"links": [{"downloadType": "serverBedrockWindows",
                               "downloadUrl": "https://x/bedrock-server-1.26.40.8.zip"}]}}
    ))
    gui.manager.installed_version = "1.26.33.2"

    client = TestClient(gui.app, client=("127.0.0.1", 50000))
    data = client.get("/api/check_update").json()
    assert data["has_previous"] is True
    assert data["previous_version"] == "1.26.30.1"
