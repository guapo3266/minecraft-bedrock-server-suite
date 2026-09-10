# -*- coding: utf-8 -*-
"""Contrato de historial-vacio: un fallo de SQLite nunca rompe la GUI.

Los lectores devuelven su forma vacia y los escritores/sweep se tragan
sqlite3.Error (docstring de services/history.py).
"""
import sqlite3

from gui_backend.services import history


def _db_caida(monkeypatch):
    def _boom():
        raise sqlite3.Error("base de datos inaccesible")
    monkeypatch.setattr(history, "_connect", _boom)


def test_lectores_devuelven_vacio_sin_db(monkeypatch):
    _db_caida(monkeypatch)
    assert history.query_metrics(24) == []
    assert history.query_logs(10) == []
    assert history.query_sessions(7) == {"sessions": [], "totals": []}


def test_escritores_y_sweep_no_lanzan_sin_db(monkeypatch):
    _db_caida(monkeypatch)
    history.record_metrics({"ram_mb": 1.0, "cpu_pct": 2.0}, True)
    history._persist_log({"time": "00:00:00", "type": "info", "text": "x"})
    history._persist_session_event("Ana", "123", True)
    history._persist_session_event("Ana", None, False)
    history.sweep()
