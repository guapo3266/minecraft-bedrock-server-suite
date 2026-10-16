"""Cierre portable: resultado real del backup, exclusión, fallos y reintentos."""

import json
import threading
from types import SimpleNamespace

import pytest

from gui_backend.services import desktop_lifecycle as desktop
import server_wrapper


@pytest.fixture
def env(tmp_path, monkeypatch):
    proc = SimpleNamespace(poll=lambda: None)
    channel = tmp_path / "events.ndjson"
    mgr = SimpleNamespace(lock=threading.Lock(), op_lock=threading.Lock(),
                          wrapper_process=proc, events_file=str(channel),
                          is_running=True, add_log=lambda *a: None)
    monkeypatch.setattr(desktop, "manager", mgr)
    monkeypatch.setattr(desktop.external_probe, "detect_external_bds", lambda: (False, None))
    close = desktop.DesktopCloseCoordinator()
    yield close, mgr, proc, channel
    close.release()


def stop_success(monkeypatch, mgr, proc):
    def stop(*a, **kw):
        kw["on_progress"]("stopping")
        kw["on_progress"]("backup")
        mgr.is_running = False
        proc.poll = lambda: 0
        return True
    monkeypatch.setattr(desktop.lifecycle, "stop_and_wait", stop)


def test_cierre_espera_backup_confirmado_sin_duplicarlo(env, monkeypatch):
    close, mgr, proc, channel = env
    channel.write_text(json.dumps({"event": "final_backup_finished", "success": True, "zip": "valido.zip"}) + "\n", encoding="utf-8")
    stop_success(monkeypatch, mgr, proc)
    monkeypatch.setattr(desktop.auto_backup, "create_backup", lambda *a, **kw: pytest.fail("no duplicar backup"))
    stages = []
    assert close.close(stages.append) == {"state": "ready", "zip": "valido.zip"}
    assert stages == ["waiting", "stopping", "backup"]
    assert not mgr.op_lock.acquire(blocking=False)


@pytest.mark.parametrize("event", [None, {"event": "final_backup_finished", "success": False, "error": "Disco lleno"}])
def test_backup_no_confirmado_mantiene_exclusion_y_permite_reintentar(env, monkeypatch, event):
    close, mgr, proc, channel = env
    if event:
        channel.write_text(json.dumps(event), encoding="utf-8")
    stop_success(monkeypatch, mgr, proc)
    assert close.close()["state"] == "backup_error"
    assert close.backup_failed
    assert not mgr.op_lock.acquire(blocking=False)
    monkeypatch.setattr(desktop.auto_backup, "create_backup", lambda trigger: "reintento.zip")
    assert close.close(retry=True) == {"state": "ready", "zip": "reintento.zip"}
    assert not close.backup_failed


def test_fallo_de_entrega_stop_no_permite_salida_y_libera_operaciones(env, monkeypatch):
    close, mgr, _, _ = env
    monkeypatch.setattr(desktop.lifecycle, "stop_and_wait", lambda *a, **kw: False)
    assert close.close()["state"] == "stop_error"
    assert not close.holding
    assert mgr.op_lock.acquire(blocking=False)
    mgr.op_lock.release()


def test_no_declara_apagado_si_wrapper_sigue_vivo(env, monkeypatch):
    close, _, _, _ = env
    monkeypatch.setattr(desktop.lifecycle, "stop_and_wait", lambda *a, **kw: True)
    assert close.close()["state"] == "stop_error"


def test_reintento_fallido_no_cierra_ni_libera_exclusion(env, monkeypatch):
    close, mgr, proc, _ = env
    mgr.is_running = False
    proc.poll = lambda: 0
    monkeypatch.setattr(desktop.auto_backup, "create_backup", lambda *a: False)
    assert close.close(retry=True)["state"] == "backup_error"
    assert close.holding


def test_reintento_no_comprime_mientras_wrapper_sigue_vivo(env, monkeypatch):
    close, _, _, _ = env
    monkeypatch.setattr(desktop.auto_backup, "create_backup", lambda *a: pytest.fail("wrapper vivo"))
    assert close.close(retry=True)["state"] == "backup_error"


def test_instalacion_nueva_sin_wrapper_cierra_sin_backup(env, monkeypatch):
    close, mgr, _, _ = env
    mgr.is_running = False
    mgr.wrapper_process = None
    monkeypatch.setattr(desktop.auto_backup, "create_backup", lambda *a: pytest.fail("sin mundo"))
    assert close.close() == {"state": "ready"}


def test_reintento_no_copia_un_mundo_de_instancia_externa(env, monkeypatch):
    close, mgr, proc, _ = env
    mgr.is_running = False
    proc.poll = lambda: 0
    monkeypatch.setattr(desktop.external_probe, "detect_external_bds", lambda: (True, "externo"))
    monkeypatch.setattr(desktop.auto_backup, "create_backup", lambda *a: pytest.fail("instancia externa"))
    assert close.close(retry=True)["state"] == "backup_error"


@pytest.mark.parametrize("outcome", ["valido.zip", False, OSError("Disco lleno")])
def test_wrapper_emite_resultado_final_sin_ocultar_fallo(monkeypatch, outcome):
    events = []
    def create(*a, **kw):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
    monkeypatch.setattr(server_wrapper.auto_backup, "create_backup", create)
    monkeypatch.setattr(server_wrapper, "_emit_event", lambda name, **kw: events.append((name, kw)))
    server_wrapper.execute_final_backup()
    name, event = events[0]
    assert name == "final_backup_finished"
    assert event["success"] is (outcome == "valido.zip")
    assert event["error"] is not None if not event["success"] else event["zip"] == "valido.zip"
