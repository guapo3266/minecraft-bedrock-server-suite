# -*- coding: utf-8 -*-
"""run_wrapper_thread con stdout roto: captura el error y cierra la sesion."""

import threading

import gui_backend.supervisor as sup
from gui_backend.state import manager


class _ProcRoto:
    def __init__(self):
        self.stdout = self

    def readline(self):
        raise OSError("stdout roto")

    def wait(self):
        return 1

    def poll(self):
        return None


def test_run_wrapper_thread_con_stdout_roto_cierra_sesion(monkeypatch):
    logs = []
    monkeypatch.setattr(manager, "add_log", lambda *a, **k: logs.append(a[0]))
    monkeypatch.setattr(manager, "update_status", lambda: None)
    monkeypatch.setattr(manager, "events_file", None)
    monkeypatch.setattr(manager, "is_running", False)
    monkeypatch.setattr(manager, "wrapper_process", None)
    monkeypatch.setattr(manager, "wrapper_exit_event", threading.Event())
    monkeypatch.setattr(manager, "server_stopped_event", threading.Event())
    monkeypatch.setattr(manager, "players_online", set())
    monkeypatch.setattr(manager, "backup_in_progress", False)

    sup.run_wrapper_thread(_ProcRoto())

    assert manager.is_running is False
    assert manager.wrapper_process is None
    assert manager.wrapper_exit_event.is_set()
    assert manager.server_stopped_event.is_set()
    assert any("Error en el wrapper" in x or "Error in the wrapper" in x for x in logs), logs
