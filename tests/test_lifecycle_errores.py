# -*- coding: utf-8 -*-
"""Caminos de error de lifecycle y arranque idempotente del watchdog."""

import types


from gui_backend.services import lifecycle, watchdog
from gui_backend.state import manager


class _StdinOk:
    @staticmethod
    def write(_s):
        pass

    @staticmethod
    def flush():
        pass


class _ProcOk:
    stdin = _StdinOk()

    def poll(self):
        return None


def test_launch_wrapper_error_de_spawn_devuelve_error_y_libera_lock(monkeypatch):
    from gui_backend import supervisor

    monkeypatch.setattr(manager, "is_running", False)
    monkeypatch.setattr(supervisor, "_spawn_wrapper_process",
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    logs = []
    monkeypatch.setattr(manager, "add_log", lambda *a, **k: logs.append(a[0]))

    status, detalle = lifecycle._launch_wrapper()

    assert status == "error"
    assert "boom" in detalle
    assert manager.op_lock.locked() is False, "el op_lock quedo tomado"
    assert any("Error al iniciar el wrapper" in x or "Error starting the wrapper" in x
               for x in logs)


def test_cold_backup_loguea_error_y_limpia_flag(monkeypatch):
    import auto_backup

    monkeypatch.setattr(manager, "is_running", False)
    monkeypatch.setattr(manager, "backup_in_progress", False)
    monkeypatch.setattr(auto_backup, "create_backup",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("disco lleno")))
    monkeypatch.setattr(manager, "update_status", lambda: None)
    logs = []
    monkeypatch.setattr(manager, "add_log", lambda *a, **k: logs.append(a[0]))

    lifecycle.cold_backup("test")

    assert any("Error en backup" in x or "Backup error" in x for x in logs)
    assert manager.backup_in_progress is False


def test_stop_and_wait_timeout_de_bds(monkeypatch):
    monkeypatch.setattr(manager, "is_running", True)
    monkeypatch.setattr(manager, "wrapper_process", _ProcOk())
    monkeypatch.setattr(manager, "stop_requested", False)
    monkeypatch.setattr(manager.server_stopped_event, "wait", lambda timeout=None: False)
    logs = []
    monkeypatch.setattr(manager, "add_log", lambda *a, **k: logs.append(a[0]))

    assert lifecycle.stop_and_wait("[T]") is False

    # El stop SE ENTREGO (write ok): el flag queda marcado aunque el apagado
    # haya expirado, para que el watchdog no re-lance lo que el usuario paro.
    assert manager.stop_requested is True
    assert any("no se detuvo" in x or "did not stop" in x for x in logs)


def test_stop_and_wait_timeout_del_wrapper(monkeypatch):
    monkeypatch.setattr(manager, "is_running", True)
    monkeypatch.setattr(manager, "wrapper_process", _ProcOk())
    monkeypatch.setattr(manager, "stop_requested", False)
    monkeypatch.setattr(manager.server_stopped_event, "wait", lambda timeout=None: True)
    monkeypatch.setattr(manager, "wrapper_exit_event",
                        types.SimpleNamespace(wait=lambda timeout=None: False))
    logs = []
    monkeypatch.setattr(manager, "add_log", lambda *a, **k: logs.append(a[0]))

    assert lifecycle.stop_and_wait("[T]") is False
    assert any("no termino" in x or "did not finish" in x for x in logs)


class _FakeThread:
    creados = []

    def __init__(self, target=None, daemon=None, name=None):
        self.target = target
        self.daemon = daemon
        self.name = name
        self.started = False
        _FakeThread.creados.append(self)

    def start(self):
        self.started = True


def test_watchdog_start_es_idempotente_y_crea_un_solo_hilo(monkeypatch):
    _FakeThread.creados = []
    monkeypatch.setattr(watchdog, "threading",
                        types.SimpleNamespace(Thread=_FakeThread))
    monkeypatch.setattr(watchdog, "_load_gui_state", lambda: None)
    watchdog._started.clear()
    try:
        # `_start_real` lo expone tests/conftest.py: el fixture de sesion anula
        # `watchdog.start` para que la suite no lance el loop de fondo real.
        watchdog._start_real()
        watchdog._start_real()
    finally:
        watchdog._started.clear()

    assert len(_FakeThread.creados) == 1
    assert _FakeThread.creados[0].started is True
    assert _FakeThread.creados[0].daemon is True


def test_save_gui_state_tolera_oserror(tmp_path, monkeypatch):
    monkeypatch.setattr(watchdog, "STATE_PATH", str(tmp_path / "sub" / "state.json"))
    monkeypatch.setattr(watchdog.os, "replace",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("bloqueado")))
    watchdog._save_gui_state()  # no debe lanzar
