# -*- coding: utf-8 -*-
"""Apagado coordinado (`initiate_shutdown`) y consola (`read_stdin`).

Fija: marcado atomico + stop, cancelacion de backup con resume, idempotencia
del doble stop, y los tres caminos de read_stdin (backup manual, comando
normal, stop) incluido el corte por shutting_down.
"""
import io
import sys

import pytest

import server_wrapper as sw
import wrapper_state as wstate


def _limpiar_estado():
    with wstate.state_lock:
        wstate.shutting_down = False
        wstate.shutdown_requested_at = 0.0
        wstate.backup_in_progress = False
        wstate.backup_dispatched = False
        wstate.save_query_ready_seen = False
        wstate.backup_cancel_event = None
        wstate.watchdog_fired = False


@pytest.fixture(autouse=True)
def _estado_limpio():
    _limpiar_estado()
    yield
    _limpiar_estado()


class _EventoFalso:
    def __init__(self):
        self.marcado = False

    def set(self):
        self.marcado = True


def test_initiate_shutdown_marca_y_manda_stop(monkeypatch):
    comandos = []
    eventos = []
    monkeypatch.setattr(sw, "send_command", comandos.append)
    monkeypatch.setattr(sw, "_emit_event", lambda event, **data: eventos.append(event))

    sw.initiate_shutdown("test")

    assert wstate.shutting_down is True
    assert wstate.shutdown_requested_at > 0
    assert comandos == ["stop"]
    assert eventos == ["shutdown_initiated"]


def test_initiate_shutdown_cancela_backup_y_reanuda(monkeypatch):
    evento = _EventoFalso()
    with wstate.state_lock:
        wstate.backup_in_progress = True
        wstate.backup_cancel_event = evento
    comandos = []
    monkeypatch.setattr(sw, "send_command", comandos.append)
    monkeypatch.setattr(sw, "_emit_event", lambda *a, **k: None)

    sw.initiate_shutdown("corte")

    assert evento.marcado is True
    assert comandos == ["save resume", "stop"]
    with wstate.state_lock:
        assert wstate.backup_in_progress is False
        assert wstate.backup_cancel_event is None
        assert wstate.watchdog_fired is True


def test_initiate_shutdown_es_idempotente(monkeypatch):
    with wstate.state_lock:
        wstate.shutting_down = True
        wstate.shutdown_requested_at = 123.0
    comandos = []
    monkeypatch.setattr(sw, "send_command", comandos.append)
    monkeypatch.setattr(sw, "_emit_event", lambda *a, **k: None)

    sw.initiate_shutdown("otra vez")

    assert comandos == [], "un segundo apagado no debe reenviar stop"
    assert wstate.shutdown_requested_at == 123.0


# ── read_stdin ────────────────────────────────────────────────────────
def _stdin(monkeypatch, texto):
    monkeypatch.setattr(sys, "stdin", io.StringIO(texto))


def test_read_stdin_comandos_y_stop(monkeypatch):
    _stdin(monkeypatch, "list\nsay hola\nstop\n")
    comandos = []
    apagados = []
    monkeypatch.setattr(sw, "send_command", comandos.append)
    monkeypatch.setattr(sw, "initiate_shutdown", lambda motivo: apagados.append(motivo))

    sw.read_stdin()

    assert comandos == ["list", "say hola"]
    assert apagados == ["comando 'stop' en consola"]


def test_read_stdin_backup_manual_dispara_hold(monkeypatch):
    _stdin(monkeypatch, "backup\nstop\n")
    monkeypatch.setattr(sw.wrapper_backup, "_begin_manual_hot_backup", lambda: True)
    comandos = []
    monkeypatch.setattr(sw, "send_command", comandos.append)
    monkeypatch.setattr(sw, "initiate_shutdown", lambda motivo: None)

    sw.read_stdin()

    assert comandos == ["save hold"]


def test_read_stdin_backup_manual_rechazado_no_dispara(monkeypatch):
    _stdin(monkeypatch, "backup\nstop\n")
    monkeypatch.setattr(sw.wrapper_backup, "_begin_manual_hot_backup", lambda: False)
    comandos = []
    monkeypatch.setattr(sw, "send_command", comandos.append)
    monkeypatch.setattr(sw, "initiate_shutdown", lambda motivo: None)

    sw.read_stdin()

    assert comandos == []


def test_read_stdin_con_shutting_down_no_procesa(monkeypatch):
    _stdin(monkeypatch, "list\n")
    with wstate.state_lock:
        wstate.shutting_down = True
    comandos = []
    monkeypatch.setattr(sw, "send_command", comandos.append)

    sw.read_stdin()

    assert comandos == []
