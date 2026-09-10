# -*- coding: utf-8 -*-
"""Robustez del broadcast del ServerManager (gui_backend/state.py) ante loops muertos.

El lifespan fija `manager.loop` al loop VIVO; al apagarse (GUI real o teardown
de un TestClient) ese loop se cierra, pero el atributo global sobrevive
apuntando a un loop MUERTO. `asyncio.run_coroutine_threadsafe(coro,
loop_cerrado)` lanza un RuntimeError SINCRONICO: sin guardia, cualquier
`add_log`/`update_status` ejecutado en esa ventana desde un hilo de fondo
(watchdog daemon, hilos lectores del wrapper) propaga la excepcion y la
corrutina queda HUERFANA (RuntimeWarning "never awaited" — reproducible en la
suite ejecutando test_gui_new_features.py antes que test_websocket_router.py).

Contrato esperado (consistente con el diseño documentado de los sinks):
el broadcast en vivo es BEST-EFFORT. La fuente autoritativa del estado es el
historial persistente y el canal NDJSON; un fallo de agendado nunca debe
propagarse ni dejar corrutinas huerfanas.
"""
import asyncio
import gc
import warnings

import pytest

from gui_backend.state import manager


@pytest.fixture
def _estado_manager_hermetico():
    """Restaura loop/sockets/historial/sinks tras cada test."""
    with manager.lock:
        previo_logs = list(manager.log_history)
        previo_seq = manager._log_seq
        previo_sinks = list(manager.log_sinks)
        previo_sockets = set(manager.active_websockets)
    previo_loop = manager.loop
    yield
    manager.loop = previo_loop
    with manager.lock:
        manager.log_history[:] = previo_logs
        manager._log_seq = previo_seq
        manager.log_sinks[:] = previo_sinks
        manager.active_websockets.clear()
        manager.active_websockets.update(previo_sockets)


class _SocketFalso:
    """Solo se necesita su identidad como clave del registro."""


def _loop_cerrado():
    loop = asyncio.new_event_loop()
    loop.close()
    return loop


# ── 1) add_log con loop cerrado: no lanza, registra y llama sinks ────
def test_add_log_con_loop_cerrado_no_lanza_y_registra(_estado_manager_hermetico):
    manager.loop = _loop_cerrado()
    manager.active_websockets.add(_SocketFalso())
    llamadas = []
    manager.log_sinks.append(lambda e: llamadas.append(e))

    # Antes del guardia: RuntimeError("Event loop is closed") desde aqui mismo.
    manager.add_log("mensaje durante apagado", "system")

    with manager.lock:
        textos = [e["text"] for e in manager.log_history]
    assert any(t == "mensaje durante apagado" for t in textos)
    assert len(llamadas) == 1  # los sinks siguen recibiendo la entrada


# ── 2) update_status con loop cerrado: no lanza ──────────────────────
def test_update_status_con_loop_cerrado_no_lanza(_estado_manager_hermetico):
    manager.loop = _loop_cerrado()
    manager.active_websockets.add(_SocketFalso())
    manager.update_status()  # antes: RuntimeError


# ── 3) sin fugas: la corrutina no queda huerfana tras el fallo ───────
def test_fallo_de_agendado_no_deja_corrutina_huerfana(_estado_manager_hermetico):
    manager.loop = _loop_cerrado()
    manager.active_websockets.add(_SocketFalso())

    with warnings.catch_warnings(record=True) as capturadas:
        warnings.simplefilter("always")
        manager.add_log("otro mensaje", "info")
        gc.collect()  # el RuntimeWarning de corrutina huerfana sale al GC

    assert not [
        w for w in capturadas if "never awaited" in str(w.message)
    ], "corrutina broadcast quedo huerfana"


# ── 4) loop None con sockets registrados: camino ya seguro, fijado ───
def test_loop_none_con_sockets_no_agenda_nada(_estado_manager_hermetico):
    manager.loop = None
    manager.active_websockets.add(_SocketFalso())
    manager.add_log("sin loop", "info")   # no debe lanzar ni crear corrutina
    manager.update_status()
    with manager.lock:
        textos = [e["text"] for e in manager.log_history]
    assert any(t == "sin loop" for t in textos)


# ── 5) REGRESION del estado global: lifespan deja loop None al salir ─
def test_lifespan_deja_manager_loop_none_al_apagarse():
    """El teardown del lifespan debe resetear manager.loop: si no, queda un
    loop CERRADO como global y cada add_log posterior (tests incluidos)
    entra en la ventana rota que cubren los tests 1-3."""
    from fastapi.testclient import TestClient
    import server_gui_server as sgs

    with TestClient(sgs.app, client=("127.0.0.1", 50000)):
        assert manager.loop is not None  # vivo durante la sesion
    assert manager.loop is None  # y None tras el apagado


# ── 6) broadcast(): descarta sockets muertos y conserva los vivos ────
def test_broadcast_descarta_sockets_muertos_y_conserva_vivos(_estado_manager_hermetico):
    class _Vivo:
        def __init__(self):
            self.enviados = []

        async def send_json(self, msg):
            self.enviados.append(msg)

    class _Muerto:
        async def send_json(self, msg):
            raise RuntimeError("socket muerto")

    vivo, muerto = _Vivo(), _Muerto()
    with manager.lock:
        manager.active_websockets.clear()
        manager.active_websockets.update({vivo, muerto})

    asyncio.run(manager.broadcast({"type": "ping"}))

    assert vivo in manager.active_websockets
    assert muerto not in manager.active_websockets
    assert vivo.enviados == [{"type": "ping"}]
