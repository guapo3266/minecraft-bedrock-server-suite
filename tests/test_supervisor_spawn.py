# -*- coding: utf-8 -*-
"""Cableado de _spawn_wrapper_process: env UTF-8, canal NDJSON y cwd."""

from gui_backend import supervisor as sup
from gui_backend.state import manager


class _ProcFalso:
    pass


def test_spawn_wrapper_pasa_env_eventos_utf8_y_cwd(tmp_path, monkeypatch):
    capturado = {}

    def _popen(args, **kwargs):
        capturado["args"] = args
        capturado.update(kwargs)
        return _ProcFalso()

    monkeypatch.setattr(sup.subprocess, "Popen", _popen)
    monkeypatch.setattr(sup.config, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(manager, "stop_requested", True)

    proc = sup._spawn_wrapper_process()

    assert isinstance(proc, _ProcFalso)
    env = capturado["env"]
    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["WRAPPER_EVENTS_FILE"].startswith(str(tmp_path))
    assert env["WRAPPER_EVENTS_FILE"].endswith(".ndjson")
    assert capturado["cwd"] == str(tmp_path)
    assert capturado["args"][1] == "-u"
    assert manager.events_file == env["WRAPPER_EVENTS_FILE"]
    assert manager.stop_requested is False
