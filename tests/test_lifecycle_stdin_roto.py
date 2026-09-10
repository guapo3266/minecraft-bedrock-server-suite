# -*- coding: utf-8 -*-
"""El stop deliberado solo se marca tras ENTREGAR el comando al wrapper.

Misma regla que /api/action/stop (ronda 2026-09-10): si el write a stdin falla,
la operacion se cancela de inmediato y `stop_requested` queda False para no
inhibir al watchdog mientras el servidor sigue vivo. Antes, `restart_wrapper` y
`stop_and_wait` se tragaban el error, marcaban el flag y esperaban 75s+ un
apagado que nunca llegaria.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui_backend.services import lifecycle
from gui_backend.state import manager


class _BrokenStdin:
    def write(self, s):
        raise BrokenPipeError("tuberia rota")

    def flush(self):
        pass


class _ProcRoto:
    stdin = _BrokenStdin()


class _EventoEspia:
    """Sustituye a server_stopped_event.wait para no esperar 75s en el test."""

    def __init__(self):
        self.llamadas = []

    def wait(self, timeout=None):
        self.llamadas.append(timeout)
        return True


def _setup(monkeypatch):
    espia = _EventoEspia()
    monkeypatch.setattr(manager, "wrapper_process", _ProcRoto())
    monkeypatch.setattr(manager, "is_running", True)
    monkeypatch.setattr(manager, "stop_requested", False)
    monkeypatch.setattr(manager.server_stopped_event, "wait", espia.wait)
    manager.wrapper_exit_event.set()  # no esperar en la fase 2 si el codigo llega
    return espia


def test_restart_wrapper_no_marca_stop_ni_espera_si_stdin_roto(monkeypatch):
    espia = _setup(monkeypatch)
    logs = []
    monkeypatch.setattr(manager, "add_log", lambda *a, **k: logs.append(a[0]))

    lifecycle.restart_wrapper()

    assert espia.llamadas == [], "espero el apagado aunque no pudo entregar el stop"
    assert manager.stop_requested is False, "stop_requested inhibiria al watchdog"
    assert any("Reinicio cancelado" in x or "Restart cancelled" in x for x in logs), logs


def test_stop_and_wait_no_marca_stop_ni_espera_si_stdin_roto(monkeypatch):
    espia = _setup(monkeypatch)
    logs = []
    monkeypatch.setattr(manager, "add_log", lambda *a, **k: logs.append(a[0]))

    resultado = lifecycle.stop_and_wait("[Test]")

    assert resultado is False
    assert espia.llamadas == [], "espero el apagado aunque no pudo entregar el stop"
    assert manager.stop_requested is False
    assert any("Operación cancelada" in x or "Operation cancelled" in x for x in logs), logs
