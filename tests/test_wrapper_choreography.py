# -*- coding: utf-8 -*-
"""Caracterizacion de la coreografia observable del worker de backups.

Estos tests fijan el orden de eventos, comandos y marcadores de consola antes
de extraer el worker a un modulo propio.
"""
import json
import multiprocessing
import os

import pytest

import server_wrapper as sw
import wrapper_backup
import wrapper_events
import wrapper_state as wstate


class _FakePopen:
    def __init__(self, result_path, result=None, alive=False):
        self._alive = alive
        self.killed = False
        if result is not None:
            with open(result_path, "w", encoding="utf-8") as f:
                json.dump(result, f)

    def poll(self):
        return None if self._alive else 0

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True
        self._alive = False


def _reset_state():
    with wstate.state_lock:
        wstate.backup_in_progress = True
        wstate.backup_dispatched = True
        wstate.watchdog_fired = False
        wstate.save_query_ready_seen = True
        wstate.backup_cancel_event = None
        wstate.active_compress_process = None
        wstate.last_backup_completed_time = 0
        wstate.snapshot_retry_count = 0
        wstate.snapshot_retry_at = 0.0
        wstate.backup_ipc_lock = multiprocessing.Lock()


def _run_worker(monkeypatch, tmp_path, result=None, alive=False, launch_error=None,
                watchdog_fired=False):
    _reset_state()
    with wstate.state_lock:
        wstate.watchdog_fired = watchdog_fired

    events = []
    commands = []
    processes = []
    monkeypatch.setenv("TEMP", str(tmp_path))
    monkeypatch.setattr(sw.auto_backup, "BACKUP_DIR", str(tmp_path))
    monkeypatch.setattr(
        wrapper_events,
        "_emit_event",
        lambda event, **data: events.append((event, data)),
    )
    monkeypatch.setattr(sw, "send_command", commands.append)

    def fake_popen(args, **kwargs):
        if launch_error is not None:
            raise launch_error
        proc = _FakePopen(args[-1], result=result, alive=alive)
        processes.append(proc)
        return proc

    monkeypatch.setattr(wrapper_backup.subprocess, "Popen", fake_popen)
    sw.execute_backup_worker(file_snapshot=[("level.dat", 10)], cancel_event=None)
    return events, commands, processes


@pytest.mark.parametrize(
    ("result", "alive", "launch_error", "expected_outcome", "retry"),
    [
        ({"zip": "ok.zip", "error": None}, False, None, "success", False),
        ({"zip": None, "error": "Snapshot: incomplete snapshot"}, False, None, "failed", True),
        ({"zip": None, "error": "No space left on device"}, False, None, "failed", False),
        (None, True, None, "timeout", False),
        (None, False, OSError("launch failed"), "launch_error", False),
    ],
    ids=["success", "snapshot-error", "operational-error", "timeout", "launch-error"],
)
def test_worker_preserva_secuencia_por_desenlace(
    monkeypatch, tmp_path, capsys, result, alive, launch_error, expected_outcome, retry
):
    events, commands, processes = _run_worker(
        monkeypatch,
        tmp_path,
        result=result,
        alive=alive,
        launch_error=launch_error,
    )

    expected_events = ["backup_compress_started", "backup_finished"]
    if expected_outcome == "success":
        expected_events.insert(1, "backup_ok")
    assert [event for event, _data in events] == expected_events
    assert events[-1][1]["outcome"] == expected_outcome
    assert commands == ["save resume"]

    output = capsys.readouterr().out
    assert "Backup finalizado" in output or "Backup finished" in output

    with wstate.state_lock:
        assert wstate.backup_in_progress is False
        assert wstate.backup_dispatched is False
        assert wstate.save_query_ready_seen is False
        assert wstate.backup_cancel_event is None
        assert wstate.last_backup_completed_time != 0
        if retry:
            assert wstate.snapshot_retry_count == 1
            assert wstate.snapshot_retry_at > 0
        else:
            assert wstate.snapshot_retry_count == 0
            assert wstate.snapshot_retry_at == 0.0

    if expected_outcome == "timeout":
        assert processes and processes[0].killed is True
        with wstate.state_lock:
            assert wstate.watchdog_fired is True


def test_worker_watchdog_no_reanuda_dos_veces(monkeypatch, tmp_path):
    events, commands, _processes = _run_worker(
        monkeypatch,
        tmp_path,
        result={"zip": "watchdog.zip", "error": None},
        watchdog_fired=True,
    )

    assert [event for event, _data in events] == [
        "backup_compress_started",
        "backup_finished",
    ]
    assert events[-1][1]["outcome"] == "watchdog"
    assert commands == []
