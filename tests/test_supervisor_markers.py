# -*- coding: utf-8 -*-
"""run_wrapper_thread (fallback sin canal NDJSON): version y marcadores de backup.

Con `events_alive=False` (wrapper viejo o canal muerto), el parseo de stdout es
la fuente de estado: la linea de Version y los marcadores de compresion/fin
deben actualizar manager.installed_version y backup_in_progress.
"""
import threading

import gui_backend.supervisor as sup
from gui_backend.state import manager


class _FakeStdout:
    def __init__(self, lines):
        self._lines = list(lines)

    def readline(self):
        return self._lines.pop(0) if self._lines else ""


class _FakeProc:
    def __init__(self, lines):
        self.stdout = _FakeStdout(lines)

    def wait(self):
        return 0


def _aislar_manager(monkeypatch):
    monkeypatch.setattr(manager, "add_log", lambda *a, **k: None)
    estados = []
    monkeypatch.setattr(
        manager, "update_status", lambda: estados.append(manager.backup_in_progress)
    )
    monkeypatch.setattr(manager, "events_file", None)
    monkeypatch.setattr(manager, "events_alive", False)
    monkeypatch.setattr(manager, "installed_version", None)
    monkeypatch.setattr(manager, "is_running", False)
    monkeypatch.setattr(manager, "wrapper_process", None)
    monkeypatch.setattr(manager, "wrapper_exit_event", threading.Event())
    monkeypatch.setattr(manager, "server_stopped_event", threading.Event())
    monkeypatch.setattr(manager, "players_online", set())
    monkeypatch.setattr(manager, "backup_in_progress", False)
    return estados


def test_fallback_stdout_captura_version_y_marcadores_de_backup(monkeypatch):
    estados = _aislar_manager(monkeypatch)
    proc = _FakeProc([
        "[2026-09-10 10:00:00:001 INFO] Version: 1.26.40.8\n",
        "[Wrapper] Iniciando compresion de archivos en proceso separado (subprocess)...\n",
        "[Wrapper] Compresión exitosa. Reanudando escritura (save resume)...\n",
        "[Wrapper] Backup finalizado\n",
        "",
    ])

    sup.run_wrapper_thread(proc)

    assert manager.installed_version == "1.26.40.8"
    assert True in estados, "el marcador de inicio de compresion no activo el flag"
    assert estados[-1] is False, "el marcador de fin no apago el flag"
    assert manager.last_backup_time != "Ninguno"
    assert manager.is_running is False
    assert manager.wrapper_exit_event.is_set()
