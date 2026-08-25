# -*- coding: utf-8 -*-
"""Tests del router WebSocket /ws SIN e2e y SIN TestClient.

Antes de este modulo el endpoint /ws solo tenia cobertura e2e (saltada sin
bedrock_server.exe): cero verificacion del handshake, del canal init/ping/
set_lang ni del registro active_websockets en fallos tempranos. El TestClient
de Starlette exige httpx (no esta en el .venv: los tests que lo usan llevan
anos saltandose), asi que aqui se ejercita la COROUTINE REAL
`websocket_endpoint` con un WebSocket falso (misma tecnica que la simulacion
del watchdog en test_watchdog_simulacion.py): sin servidor, hermetico y
determinista.

Cubre:
  1) Handshake S3: Origin externo / puerto distinto -> close(1008) sin aceptar.
  2) Handshake feliz: init entrega snapshot de logs + estado publico.
  3) Canal vivo: ping->pong, comando apagado y basura JSON no matan la sesion.
  4) REGRESION de registro: un cliente que muere DURANTE el envio del init
     (p. ej. build_public_status propaga por fallo de psutil sin cache)
     NO debe quedar en manager.active_websockets — el finally debe cubrir
     tambien la fase de init, no solo el bucle receive.
  5) Idioma: query param ?lang= y mensaje set_lang fijan WRAPPER_LANG;
     un idioma invalido es no-op documentado.
"""
import asyncio
import json
import os

import pytest

from gui_backend.routers.websocket import websocket_endpoint
from gui_backend.state import manager


# ── fakes ─────────────────────────────────────────────────────────────
class _UrlFalsa:
    def __init__(self, port=8000, scheme="ws"):
        self.port = port
        self.scheme = scheme


class _WsFalso:
    """Suficiente para websocket_endpoint: client/headers/url/query_params +
    accept/close/send_json/receive_text asincronos."""

    def __init__(self, host="127.0.0.1", origin=None, host_hdr="127.0.0.1:8000",
                 url=None, query=None, entrantes=(), fallir_init=False):
        class _Cliente:  # noqa: E306
            pass
        c = _Cliente()
        c.host = host
        self.client = c
        self.headers = {}
        if host_hdr is not None:
            self.headers["host"] = host_hdr
        if origin is not None:
            self.headers["origin"] = origin
        self.url = url if url is not None else _UrlFalsa()
        self.query_params = query if query is not None else {}
        self._entrantes = list(entrantes)
        self.enviados = []
        self.accepted = False
        self.closed_code = None
        self._fallir_init = fallir_init

    async def accept(self):
        self.accepted = True

    async def close(self, code=1000):
        self.closed_code = code

    async def send_json(self, payload):
        if self._fallir_init and not self.enviados:
            raise RuntimeError("conexion muerta durante el envio del init")
        self.enviados.append(payload)

    async def receive_text(self):
        if not self._entrantes:
            raise RuntimeError("cliente desconectado")
        return self._entrantes.pop(0)


def _correr(ws):
    """Ejecuta la coroutine real y garantiza que el registro global quede
    limpio incluso cuando el codigo bajo prueba tiene la fuga (fase RED).
    Devuelve la excepcion con la que termino la sesion (una sesion normal
    acaba como el WebSocketDisconnect real: el cliente se va)."""
    error = None
    try:
        asyncio.run(websocket_endpoint(ws))
    except Exception as e:  # disconnect simulado o fallo del init
        error = e
    finally:
        manager.active_websockets.discard(ws)
    return error


def _correr_hasta_desconexion(ws):
    """Sesion que termina porque el fake se queda sin mensajes entrantes
    (mismo camino que un WebSocketDisconnect real): devuelve el ws."""
    error = _correr(ws)
    assert error is not None and "cliente desconectado" in str(error)
    return ws


@pytest.fixture(autouse=True)
def _registro_ws_limpio():
    yield
    manager.active_websockets.clear()


@pytest.fixture(autouse=True)
def _wrapper_lang_restaurado():
    valor_previo = os.environ.get("WRAPPER_LANG")
    yield
    if valor_previo is None:
        os.environ.pop("WRAPPER_LANG", None)
    else:
        os.environ["WRAPPER_LANG"] = valor_previo


@pytest.fixture(autouse=True)
def _log_historial_limpio():
    with manager.lock:
        previo = list(manager.log_history)
        previo_seq = manager._log_seq
    yield
    with manager.lock:
        manager.log_history[:] = previo
        manager._log_seq = previo_seq


# ── 1) handshake S3 ───────────────────────────────────────────────────
@pytest.mark.parametrize("origin", [
    "http://evil.example.com",    # host externo
    "http://localhost:9999",      # local pero OTRO puerto (anti-CSRF)
    "null",                       # privacy sandbox -> rechazado
])
def test_ws_rechaza_origin_no_permitido(origin):
    ws = _WsFalso(origin=origin)
    assert _correr(ws) is None
    assert ws.accepted is False
    assert ws.closed_code == 1008
    assert len(manager.active_websockets) == 0


def test_ws_acepta_sin_origin_cliente_no_navegador():
    # Un cliente no-navegador no manda Origin: permitido (contrato S3).
    ws = _WsFalso(origin=None)
    _correr_hasta_desconexion(ws)
    assert ws.accepted is True
    assert ws.enviados and ws.enviados[0]["type"] == "init"


# ── 2) handshake feliz ────────────────────────────────────────────────
def test_ws_init_entrega_logs_y_estado():
    with manager.lock:
        manager.log_history.append(
            {"id": 1, "time": "00:00:00", "text": "linea-previa", "type": "info"})
    try:
        ws = _WsFalso()
        _correr_hasta_desconexion(ws)
        assert ws.accepted is True
        init = ws.enviados[0]
        assert init["type"] == "init"
        assert isinstance(init["logs"], list)
        assert any(e["text"] == "linea-previa" for e in init["logs"])
        status = init["status"]
        # Mismos campos que build_public_status / /api/status (contrato unico).
        for campo in ("running", "players", "backup_in_progress", "hardware",
                      "installed_version"):
            assert campo in status, campo
    finally:
        with manager.lock:
            manager.log_history.pop()


# ── 3) canal vivo ─────────────────────────────────────────────────────
def test_ws_ping_comando_apagado_y_basura_no_matan_sesion(monkeypatch):
    escrituras = []
    proc_falso = type("P", (), {})()
    proc_falso.stdin = type("S", (), {})()
    proc_falso.stdin.write = lambda b: escrituras.append(b)
    proc_falso.stdin.flush = lambda: None
    proc_falso.poll = lambda: None
    monkeypatch.setattr(manager, "wrapper_process", proc_falso)
    monkeypatch.setattr(manager, "is_running", False)  # apagado: comando ignorado

    ws = _WsFalso(entrantes=[
        json.dumps({"type": "ping"}),
        "esto no es json",                 # basura -> ignorada
        json.dumps({"type": "command", "command": "say hola"}),  # apagado
        json.dumps({"type": "ping"}),
    ])
    _correr_hasta_desconexion(ws)
    pings_resp = [m for m in ws.enviados if m.get("type") == "pong"]
    assert len(pings_resp) == 2          # la sesion sobrevive a todo
    assert escrituras == []              # apagado: nada llega a stdin


def test_ws_command_con_servidor_encendido_escribe_stdin_bajo_lock(monkeypatch):
    escrituras = []
    proc_falso = type("P", (), {})()
    proc_falso.stdin = type("S", (), {})()
    proc_falso.stdin.write = lambda b: escrituras.append(b)
    proc_falso.stdin.flush = lambda: None
    proc_falso.poll = lambda: None
    monkeypatch.setattr(manager, "wrapper_process", proc_falso)
    monkeypatch.setattr(manager, "is_running", True)

    ws = _WsFalso(entrantes=[json.dumps({"type": "command", "command": "say hi"})])
    _correr_hasta_desconexion(ws)
    assert escrituras == ["say hi\n"]
    with manager.lock:
        tipos = [e["text"] for e in manager.log_history]
    assert any(t.startswith("> say hi") for t in tipos)


# ── 4) REGRESION: muerte durante el init ─────────────────────────────
def test_ws_muerte_durante_init_sale_del_registro():
    """El init va DENTRO de la sesion registrada: si falla su envio o su
    construccion (build_public_status propaga, p. ej. primer muestreo de
    disco psutil sin cache), el finally DEBE sacar el socket del registro.
    Antes del fix el init estaba fuera del try/finally: la entrada muerta
    persistia hasta el siguiente broadcast (reintento contra socket muerto)."""
    ws = _WsFalso(fallir_init=True)
    error = None
    try:
        asyncio.run(websocket_endpoint(ws))
    except Exception as e:
        error = e
    # REGRESION: el socket NO debe quedar registrado tras morir en el init.
    # OJO: sin limpieza manual previa — el discard de _correr enmascararia
    # exactamente la fuga que este test detecta.
    try:
        assert len(manager.active_websockets) == 0, (
            "socket muerto durante init quedo en active_websockets")
        assert error is not None and "envio del init" in str(error)
    finally:
        manager.active_websockets.discard(ws)


# ── 5) idioma ─────────────────────────────────────────────────────────
def test_ws_query_param_lang_valido_fija_wrapper_lang():
    ws = _WsFalso(query={"lang": "es"})
    _correr_hasta_desconexion(ws)
    assert os.environ.get("WRAPPER_LANG") == "es"


def test_ws_query_param_lang_invalido_es_no_op():
    os.environ.pop("WRAPPER_LANG", None)
    ws = _WsFalso(query={"lang": "qq"})
    _correr_hasta_desconexion(ws)
    # Invalido: set_lang es no-op documentado (NO inventa 'en').
    assert os.environ.get("WRAPPER_LANG") is None


def test_ws_mensaje_set_lang_cambia_idioma_en_vivo():
    ws = _WsFalso(entrantes=[json.dumps({"type": "set_lang", "lang": "en"})])
    _correr_hasta_desconexion(ws)
    assert os.environ.get("WRAPPER_LANG") == "en"


def test_ws_mensaje_set_lang_invalido_no_cambia_idioma():
    # Contrato no-op: el idioma previo (el que sea; otros tests pueden haber
    # fijado el env global) queda EXACTAMENTE igual tras un set_lang invalido.
    previo = os.environ.get("WRAPPER_LANG")
    ws = _WsFalso(entrantes=[json.dumps({"type": "set_lang", "lang": ""})])
    _correr_hasta_desconexion(ws)
    assert os.environ.get("WRAPPER_LANG") == previo
