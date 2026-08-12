# -*- coding: utf-8 -*-
"""Tests del setup inicial (first-run wizard) — server_gui_server.py.

Cubren:
- Deteccion de instalacion nueva vs usada vs marcada (solo instalaciones
  nuevas ven el wizard; Servidor de Guapo queda auto-marcado por su mundo).
- Guards de /api/setup/install_bds (409 con servidor corriendo, 'busy' con
  otra operacion en curso).
- Pipeline compartido _download_and_install_bds: exito con apply, fallo sin
  red (no cuelga, no toca la instalacion).
- /api/setup/complete: escribe marcador, guard sin BDS instalado.
"""
import io
import os
import sys
import threading
import time
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server_gui_server as gui
import gui_backend.config as config
import gui_backend.services.bds_update as bds_update
import gui_backend.services.setup as setup_service

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════
def _fake_install(monkeypatch, tmp_path, with_world=False):
    """BASE_DIR/SERVER_EXE/SETUP_MARKER falsos dentro de tmp_path."""
    base = str(tmp_path)
    monkeypatch.setattr(config, "BASE_DIR", base)
    monkeypatch.setattr(config, "SERVER_EXE", os.path.join(base, "bedrock_server.exe"))
    monkeypatch.setattr(config, "SETUP_MARKER", os.path.join(base, "data", "setup_done.json"))
    worlds = os.path.join(base, "worlds")
    os.makedirs(worlds, exist_ok=True)
    if with_world:
        wdir = os.path.join(worlds, "Bedrock level")
        os.makedirs(wdir, exist_ok=True)
        with open(os.path.join(wdir, "level.dat"), "wb") as f:
            f.write(b"LEVEL")
    return base


def _reset_manager_state():
    gui.manager.is_running = False
    gui.manager.wrapper_process = None
    gui.manager.update_in_progress = False
    gui.manager.backup_in_progress = False


# ═══════════════════════════════════════════════════════════════════════
# Deteccion de primer arranque
# ═══════════════════════════════════════════════════════════════════════
def test_setup_required_instalacion_nueva(monkeypatch, tmp_path):
    """Instalacion sin BDS, sin mundo y sin marcador: el wizard ES requerido."""
    _fake_install(monkeypatch, tmp_path, with_world=False)
    assert setup_service._setup_required() is True
    assert setup_service._is_install_used() is False


def test_setup_no_required_instalacion_ya_usada(monkeypatch, tmp_path):
    """BDS presente + mundo con level.dat (ya arranco una vez): sin wizard,
    aunque no exista marcador (caso Servidor de Guapo tras sync)."""
    _fake_install(monkeypatch, tmp_path, with_world=True)
    with open(config.SERVER_EXE, "wb") as f:
        f.write(b"x")
    assert setup_service._is_install_used() is True
    assert setup_service._setup_required() is False


def test_setup_no_required_con_marcador(monkeypatch, tmp_path):
    """Con marcador escrito, nunca se requiere el wizard (aunque no haya mundo)."""
    _fake_install(monkeypatch, tmp_path, with_world=False)
    os.makedirs(os.path.dirname(config.SETUP_MARKER), exist_ok=True)
    with open(config.SETUP_MARKER, "w", encoding="utf-8") as f:
        f.write("{}")
    assert setup_service._setup_required() is False


def test_setup_required_bds_sin_mundo(monkeypatch, tmp_path):
    """BDS recien extraido (sin mundo): SÍ se requiere el wizard."""
    _fake_install(monkeypatch, tmp_path, with_world=False)
    with open(config.SERVER_EXE, "wb") as f:
        f.write(b"x")
    assert setup_service._setup_required() is True


def test_setup_status_endpoint(monkeypatch, tmp_path):
    """GET /api/setup_status refleja required y bds_installed."""
    from fastapi.testclient import TestClient

    _fake_install(monkeypatch, tmp_path, with_world=False)
    with TestClient(gui.app, client=("127.0.0.1", 50000)) as c:
        j = c.get("/api/setup_status").json()
    assert j == {"required": True, "bds_installed": False}, j


# ═══════════════════════════════════════════════════════════════════════
# /api/setup/install_bds
# ═══════════════════════════════════════════════════════════════════════
def test_install_bds_rechaza_con_servidor_corriendo(monkeypatch, tmp_path):
    """Con is_running=True, el endpoint devuelve 409 y no toca nada."""
    from fastapi.testclient import TestClient

    _reset_manager_state()
    _fake_install(monkeypatch, tmp_path)
    gui.manager.is_running = True
    try:
        with TestClient(gui.app, client=("127.0.0.1", 50000)) as c:
            r = c.post("/api/setup/install_bds")
            assert r.status_code == 409, r.text
    finally:
        _reset_manager_state()


def test_install_bds_busy_con_op_lock_ocupado(monkeypatch, tmp_path):
    """Con otra operacion en curso (op_lock tomado), devuelve 'busy'."""
    from fastapi.testclient import TestClient

    _reset_manager_state()
    _fake_install(monkeypatch, tmp_path)
    gui.manager.op_lock.acquire()
    try:
        with TestClient(gui.app, client=("127.0.0.1", 50000)) as c:
            r = c.post("/api/setup/install_bds")
            j = r.json()
            assert j.get("status") == "busy", j
    finally:
        gui.manager.op_lock.release()


def test_install_bds_despacha_y_reusa_pipeline(monkeypatch, tmp_path):
    """El endpoint despacha un hilo que corre _download_and_install_bds bajo
    op_lock y libera el lock al terminar (sin flag global: el wizard hace
    tracking con su propio await)."""
    from fastapi.testclient import TestClient

    _reset_manager_state()
    _fake_install(monkeypatch, tmp_path)
    record = {"called": 0, "tag": None}

    def fake_install(tag="[Actualizador BDS]"):
        record["called"] += 1
        record["tag"] = tag
        time.sleep(0.2)
        return True, "1.0.0.0"

    monkeypatch.setattr(bds_update, "_download_and_install_bds", fake_install)
    try:
        with TestClient(gui.app, client=("127.0.0.1", 50000)) as c:
            r = c.post("/api/setup/install_bds")
            assert r.json().get("status") == "install_dispatched", r.text
            end = time.time() + 5
            while record["called"] == 0 and time.time() < end:
                time.sleep(0.05)
        assert record["called"] == 1, "el helper no se ejecuto"
        assert record["tag"] == "[Setup]", record
        # op_lock liberado tras el finally del hilo
        end = time.time() + 5
        while gui.manager.op_lock.locked() and time.time() < end:
            time.sleep(0.05)
        assert not gui.manager.op_lock.locked(), "op_lock quedo retenido"
    finally:
        _reset_manager_state()


# ═══════════════════════════════════════════════════════════════════════
# Pipeline compartido _download_and_install_bds
# ═══════════════════════════════════════════════════════════════════════
def _zip_payload():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("bedrock_server.exe", b"fake-exe")
        z.writestr("server.properties", b"name=default")
    return buf.getvalue()


def test_download_and_install_bds_exito(monkeypatch, tmp_path):
    """Descarga simulada: aplica con staging/rollback, fija installed_version
    y limpia el zip temporal y el staging."""
    base = _fake_install(monkeypatch, tmp_path)
    payload = _zip_payload()

    class FakeResp:
        status_code = 200
        headers = {}

        def iter_content(self, chunk_size=8192):
            for i in range(0, len(payload), chunk_size):
                yield payload[i : i + chunk_size]

    monkeypatch.setattr(bds_update, "_fetch_latest_bedrock_download", lambda: ("https://fake/bds.zip", "1.26.33.2"))
    monkeypatch.setattr(bds_update.requests, "get", lambda *a, **k: FakeResp())

    gui.manager.installed_version = None
    ok, version = bds_update._download_and_install_bds(tag="[Setup]")
    assert ok is True, gui.manager.log_history[-3:]
    assert version == "1.26.33.2"
    assert gui.manager.installed_version == "1.26.33.2"
    assert os.path.exists(config.SERVER_EXE), "bedrock_server.exe no se instalo"
    assert not os.path.exists(os.path.join(base, "bds_update.zip")), "zip temporal no se limpio"
    assert not os.path.exists(os.path.join(base, "bds_update_staging")), "staging no se limpio"


def test_download_and_install_bds_sin_red_no_toca_instalacion(monkeypatch, tmp_path):
    """URL no disponible: devuelve (False, None), NO aplica y NO cuelga."""
    base = _fake_install(monkeypatch, tmp_path)
    monkeypatch.setattr(bds_update, "_fetch_latest_bedrock_download", lambda: (None, None))
    applied = {"n": 0}
    monkeypatch.setattr(bds_update, "_apply_staged_update", lambda *a, **k: applied.__setitem__("n", applied["n"] + 1))
    ok, version = bds_update._download_and_install_bds(tag="[Setup]")
    assert ok is False and version is None
    assert applied["n"] == 0, "no debe aplicarse nada sin URL"
    assert not os.path.exists(os.path.join(base, "bds_update.zip"))


def test_download_and_install_bds_excede_limite_aborta(monkeypatch, tmp_path):
    """Cuerpo mas grande que el tope de 400 MB: aborta sin escribir zip final."""
    base = _fake_install(monkeypatch, tmp_path)
    monkeypatch.setattr(bds_update, "_fetch_latest_bedrock_download", lambda: ("https://fake/bds.zip", "1.0.0.0"))

    class HugeResp:
        headers = {}

        def iter_content(self, chunk_size=8192):
            # 401 MB en chunks: dispara el tope sin consumir memoria real
            for _ in range(401 * 1024 * 1024 // chunk_size):
                yield b"x" * chunk_size

    monkeypatch.setattr(bds_update.requests, "get", lambda *a, **k: HugeResp())
    ok, _v = bds_update._download_and_install_bds(tag="[Setup]")
    assert ok is False
    assert not os.path.exists(os.path.join(base, "bds_update.zip"))


def test_download_emite_progreso_en_tiempo_real(monkeypatch, tmp_path):
    """La descarga emite lineas de progreso cada 10 MB (con % si se conoce el
    tamano): sin ellas la mini-consola del wizard parece congelada durante la
    fase mas larga (la descarga)."""
    _fake_install(monkeypatch, tmp_path)
    payload = b"x" * (11 * 1024 * 1024)  # > 10 MB: dispara la primera linea

    class FakeResp:
        status_code = 200
        headers = {"Content-Length": str(len(payload))}

        def iter_content(self, chunk_size=8192):
            for i in range(0, len(payload), chunk_size):
                yield payload[i : i + chunk_size]

    monkeypatch.setattr(bds_update, "_fetch_latest_bedrock_download", lambda: ("https://fake/bds.zip", "1.0.0.0"))
    monkeypatch.setattr(bds_update.requests, "get", lambda *a, **k: FakeResp())

    log_start = len(gui.manager.log_history)
    # el payload no es un zip valido: la descompresion aborta (BadZipFile) y
    # el finally limpia; el progreso ya quedo registrado antes.
    with pytest.raises(zipfile.BadZipFile):
        bds_update._download_and_install_bds(tag="[Setup]")
    texts = [e["text"] for e in gui.manager.log_history[log_start:]]
    # L() usa el idioma activo (en tests: ingles); el patron comun es "10 MB (90%)"
    assert any("10 MB (90%)" in t for t in texts), texts


# ═══════════════════════════════════════════════════════════════════════
# /api/setup/complete
# ═══════════════════════════════════════════════════════════════════════
def test_complete_escribe_marcador_y_quita_required(monkeypatch, tmp_path):
    """POST /api/setup/complete escribe el marcador y required pasa a False."""
    from fastapi.testclient import TestClient

    base = _fake_install(monkeypatch, tmp_path, with_world=False)
    with open(config.SERVER_EXE, "wb") as f:
        f.write(b"x")
    with TestClient(gui.app, client=("127.0.0.1", 50000)) as c:
        r = c.post("/api/setup/complete")
        assert r.status_code == 200, r.text
    assert os.path.exists(config.SETUP_MARKER)
    assert setup_service._setup_required() is False


def test_complete_sin_bds_instalado_da_409(monkeypatch, tmp_path):
    """Sin bedrock_server.exe, finalizar el setup es rechazado con 409."""
    from fastapi.testclient import TestClient

    _fake_install(monkeypatch, tmp_path, with_world=False)
    with TestClient(gui.app, client=("127.0.0.1", 50000)) as c:
        r = c.post("/api/setup/complete")
        assert r.status_code == 409, r.text
