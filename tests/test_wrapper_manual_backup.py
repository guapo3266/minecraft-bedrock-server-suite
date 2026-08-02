# -*- coding: utf-8 -*-
"""Tests del disparo manual de backup en caliente (comando 'backup' del wrapper).

Verifica que _begin_manual_hot_backup() arranca el ciclo exactamente con la
misma maquina de estados que el scheduler periodico, y que el guard anti
concurrencia rechaza una segunda solicitud mientras hay un ciclo en curso.
No toca BDS ni el mundo real: solo la maquina de estados.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import server_wrapper as sw

_ORIG = {}


def _snapshot_state():
    return {
        "backup_in_progress": sw.backup_in_progress,
        "backup_dispatched": sw.backup_dispatched,
        "watchdog_fired": sw.watchdog_fired,
        "save_query_ready_seen": sw.save_query_ready_seen,
        "backup_cancel_event": sw.backup_cancel_event,
        "save_hold_timestamp": sw.save_hold_timestamp,
        "last_save_snapshot": sw.last_save_snapshot,
        "expecting_list_names": sw.expecting_list_names,
    }


def _restore_state():
    for k, v in _ORIG.items():
        setattr(sw, k, v)


def setup_function():
    global _ORIG
    _ORIG = _snapshot_state()
    # OJO: tests/test_wrapper_logic.py es script-style y ejecuta run_case()
    # a nivel de modulo al ser importado por pytest, dejando estado sucio
    # (p.ej. backup_in_progress=True de su t3b). Forzamos linea base limpia.
    sw.backup_in_progress = False
    sw.backup_dispatched = False
    sw.watchdog_fired = False
    sw.save_query_ready_seen = False
    sw.backup_cancel_event = None
    sw.save_hold_timestamp = 0
    sw.last_save_snapshot = []
    sw.expecting_list_names = False
    sw.shutting_down = False


def teardown_function():
    _restore_state()


def test_backup_manual_inicia_ciclo_completo(capsys):
    started = sw._begin_manual_hot_backup()
    out = capsys.readouterr().out
    assert started is True
    assert sw.backup_in_progress is True
    assert sw.backup_dispatched is False
    assert sw.watchdog_fired is False
    assert sw.save_query_ready_seen is False
    assert sw.backup_cancel_event is None
    assert sw.last_save_snapshot == []
    assert sw.expecting_list_names is False
    assert sw.save_hold_timestamp > 0
    assert "Backup manual solicitado" not in out  # el print va en read_stdin, no aqui


def test_backup_manual_rechaza_segunda_solicitud():
    assert sw._begin_manual_hot_backup() is True
    assert sw._begin_manual_hot_backup() is False  # ya hay ciclo en curso


def test_backup_manual_reutilizable_tras_terminar_ciclo():
    assert sw._begin_manual_hot_backup() is True
    # el worker/scheduler pone backup_in_progress=False al terminar
    sw.backup_in_progress = False
    assert sw._begin_manual_hot_backup() is True


def test_backup_manual_respeta_shutting_down_por_lock():
    # Con shutting_down=True read_stdin no llega a procesar el comando;
    # aqui verificamos que el helper no arranca nada si el estado lo impide.
    sw.backup_in_progress = True
    sw.shutting_down = True
    assert sw._begin_manual_hot_backup() is False