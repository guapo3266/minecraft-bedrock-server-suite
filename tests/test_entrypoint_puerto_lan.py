"""Tests del entrypoint GUI (server_gui_server.__main__) SIN arrancar la GUI:
resolución de host LAN y búsqueda acotada de puerto.

Cubre el pendiente del modo LAN (Ronda 6):
- ``_resolver_host_gui``: coherencia GUI_ALLOW_LAN/GUI_HOST como función pura.
- Anti-drift: el parsing de GUI_ALLOW_LAN usa la fuente única ``security._allow_lan``.
- ``_resolver_puerto``: el salto de puerto queda ACOTADO a 65535 (el ``while``
  histórico giraba infinito si nada llegaba a enlazar, p. ej. con un host que
  el socket nunca acepta), avisa una vez por puerto saltado y devuelve el
  socket YA enlazado (uvicorn lo usa tal cual: sin carrera, 2026-10-21). En
  modo estricto (LAN) no salta de puerto.
- ``_enlazar``: un host IPv6 literal (contiene ":") enlaza por AF_INET6;
  con AF_INET el bind falla SIEMPRE y la búsqueda no encontraría jamás puerto.

Sin red externa: solo binds efímeros en loopback; nunca se escucha ni se
arranca uvicorn.
"""

import socket

import pytest

import server_gui_server as sgs
from gui_backend import security as sec


# ─────────────────────────────────────────────────────────────────
# Host efectivo: coherencia GUI_ALLOW_LAN / GUI_HOST
# ─────────────────────────────────────────────────────────────────

def test_sin_lan_default_loopback():
    assert sgs._resolver_host_gui(False, "") == "127.0.0.1"
    assert sgs._resolver_host_gui(False, None) == "127.0.0.1"


def test_con_lan_sin_host_abre_todas_las_interfaces():
    assert sgs._resolver_host_gui(True, "") == "0.0.0.0"


def test_con_lan_loopback_se_fuerza_a_apertura():
    # Pedir LAN dejando loopback es contradictorio: el entrypoint abre.
    assert sgs._resolver_host_gui(True, "localhost") == "0.0.0.0"
    assert sgs._resolver_host_gui(True, "127.0.0.1") == "0.0.0.0"


def test_host_especifico_se_respeta_con_y_sin_lan():
    assert sgs._resolver_host_gui(False, "192.168.1.70") == "192.168.1.70"
    assert sgs._resolver_host_gui(True, "192.168.1.70") == "192.168.1.70"


def test_host_env_se_recorta_espacios():
    assert sgs._resolver_host_gui(False, "  0.0.0.0  ") == "0.0.0.0"
    assert sgs._resolver_host_gui(True, " localhost ") == "0.0.0.0"


def test_allow_lan_es_fuente_unica_compartida_con_security(monkeypatch):
    """Anti-drift: el entrypoint NO re-parsea GUI_ALLOW_LAN inline; llama a
    security._allow_lan (misma semántica 1/true/yes/on case-insensitive)."""
    assert sgs._allow_lan is sec._allow_lan
    monkeypatch.setenv("GUI_ALLOW_LAN", "YES")
    assert sgs._allow_lan() is True
    monkeypatch.setenv("GUI_ALLOW_LAN", "")
    assert sgs._allow_lan() is False


# ─────────────────────────────────────────────────────────────────
# _enlazar: normalización e IPv6
# ─────────────────────────────────────────────────────────────────

def _ocupar_puerto_loopback():
    """Devuelve (socket, puerto): un bind vivo en 127.0.0.1 = puerto ocupado."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    return s, s.getsockname()[1]


def _libre(puerto, host):
    """True si _enlazar consiguio el puerto (y lo suelta)."""
    sock = sgs._enlazar(puerto, host)
    if sock is None:
        return False
    sock.close()
    return True


def test_enlazar_devuelve_socket_en_libre_y_none_en_ocupado():
    blocker, puerto = _ocupar_puerto_loopback()
    try:
        assert sgs._enlazar(puerto, "127.0.0.1") is None
    finally:
        blocker.close()
    sock = sgs._enlazar(puerto, "127.0.0.1")
    try:
        assert sock is not None and sock.getsockname()[1] == puerto
    finally:
        sock.close()


def test_enlazar_normaliza_host_vacio_y_localhost():
    """"" y "localhost" deben comportarse como 127.0.0.1 (detectar ocupado)."""
    blocker, puerto = _ocupar_puerto_loopback()
    try:
        assert _libre(puerto, "") is False
        assert _libre(puerto, "localhost") is False
        assert _libre(puerto, "127.0.0.1") is False
    finally:
        blocker.close()


class _RegistradorFamilia:
    """Envuelve socket.socket para registrar la familia pedida sin cambiar
    el comportamiento (delegamos en el constructor real)."""

    def __init__(self, original):
        self.original = original
        self.familias = []

    def __call__(self, family=socket.AF_INET, type=socket.SOCK_STREAM, *args, **kwargs):
        self.familias.append(family)
        return self.original(family, type, *args, **kwargs)


@pytest.mark.parametrize("host,familia", [
    ("127.0.0.1", socket.AF_INET),
    ("0.0.0.0", socket.AF_INET),
    ("", socket.AF_INET),
    ("::1", socket.AF_INET6),
])
def test_enlazar_elige_familia_segun_host(monkeypatch, host, familia):
    """Un host IPv6 literal debe usar AF_INET6: con AF_INET el bind de '::1'
    falla siempre (WinError 10047) y la búsqueda de puerto sería infinita."""
    reg = _RegistradorFamilia(socket.socket)
    monkeypatch.setattr(socket, "socket", reg)
    assert _libre(0, host) is True
    assert reg.familias == [familia]


# ─────────────────────────────────────────────────────────────────
# _url_para_navegador: normalización e IPv6
# ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("host,esperado", [
    ("127.0.0.1", "http://127.0.0.1:8000"),
    ("localhost", "http://127.0.0.1:8000"),
    ("", "http://127.0.0.1:8000"),
    ("  0.0.0.0  ", "http://0.0.0.0:8000"),
    ("192.168.1.70", "http://192.168.1.70:8000"),
    ("::1", "http://[::1]:8000"),
    ("[::1]", "http://[::1]:8000"),
])
def test_url_para_navegador_normaliza_y_corchetea_ipv6(host, esperado):
    """Un GUI_HOST IPv6 literal sin corchetes da una URL inválida y
    webbrowser.open falla en silencio; el helper la deja navegable."""
    assert sgs._url_para_navegador(host, 8000) == esperado


# ─────────────────────────────────────────────────────────────────
# _resolver_puerto: salto acotado
# ─────────────────────────────────────────────────────────────────

def test_resolver_puerto_regresa_primero_libre_real_ya_enlazado():
    blocker, ocupado = _ocupar_puerto_loopback()
    try:
        sock, elegido = sgs._resolver_puerto(ocupado, "127.0.0.1")
        try:
            # El primero libre puede ser el siguiente inmediato u otro posterior
            # (carreras con otros procesos): lo garantizado es > ocupado.
            assert elegido > ocupado
            assert elegido <= 65535
            # El socket devuelto ya tiene el puerto: nadie puede quitarselo
            # antes de que uvicorn escuche.
            assert sock.getsockname()[1] == elegido
            assert sgs._enlazar(elegido, "127.0.0.1") is None
        finally:
            sock.close()
    finally:
        blocker.close()


class _SocketFalso:
    def __init__(self, puerto):
        self.puerto = puerto


def test_resolver_puerto_salta_ocupados_y_avisa_una_vez_por_puerto(capsys, monkeypatch):
    ocupados = {8000, 8001}
    # L() solo habla español con WRAPPER_LANG=es (default EN): lección Ronda 2.
    monkeypatch.setenv("WRAPPER_LANG", "es")
    monkeypatch.setattr(sgs, "_enlazar",
                        lambda p, h="127.0.0.1": None if p in ocupados else _SocketFalso(p))
    sock, puerto = sgs._resolver_puerto(8000, "127.0.0.1")
    assert puerto == 8002 and sock.puerto == 8002
    salida = capsys.readouterr().out
    assert salida.count("[AVISO]") == 2
    assert "8000" in salida and "8001" in salida


def test_resolver_puerto_estricto_no_salta_de_puerto(capsys, monkeypatch):
    """Modo LAN (GUI_PORT_STRICT): la regla de firewall y la URL anunciada son
    del puerto pedido; saltar a otro dejaba la GUI inaccesible sin aviso."""
    consultados = []
    monkeypatch.setenv("WRAPPER_LANG", "es")
    monkeypatch.setattr(sgs, "_enlazar", lambda p, h="127.0.0.1": consultados.append(p))
    with pytest.raises(RuntimeError) as excinfo:
        sgs._resolver_puerto(8000, "0.0.0.0", estricto=True)
    assert consultados == [8000]
    assert "8000" in str(excinfo.value) and "GUI_PORT" in str(excinfo.value)
    assert "[AVISO]" not in capsys.readouterr().out


def test_resolver_puerto_esta_acotado_a_65535(monkeypatch):
    """REGRESIÓN del bucle infinito: si NINGÚN puerto llega a enlazar, antes
    el while del __main__ giraba para siempre superando el rango válido
    (bind >65535 falla siempre). Ahora se agota en 65535 con error claro."""
    consultados = []
    monkeypatch.setattr(sgs, "_enlazar",
                        lambda p, h="127.0.0.1": consultados.append(p))
    with pytest.raises(RuntimeError) as excinfo:
        sgs._resolver_puerto(65534, "127.0.0.1")
    assert consultados == [65534, 65535]
    assert "65535" in str(excinfo.value)


def test_resolver_puerto_mensaje_menciona_rango_y_host(monkeypatch):
    monkeypatch.setattr(sgs, "_enlazar", lambda p, h="127.0.0.1": None)
    with pytest.raises(RuntimeError) as excinfo:
        sgs._resolver_puerto(65535, "0.0.0.0")
    mensaje = str(excinfo.value)
    assert "65535" in mensaje and "0.0.0.0" in mensaje


def test_resolver_puerto_no_consulta_mas_alla_del_tope(monkeypatch):
    consultados = []
    monkeypatch.setattr(sgs, "_enlazar",
                        lambda p, h="127.0.0.1": consultados.append(p))
    with pytest.raises(RuntimeError):
        sgs._resolver_puerto(65530, "127.0.0.1")
    assert max(consultados) <= 65535
