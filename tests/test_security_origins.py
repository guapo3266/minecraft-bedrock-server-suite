# -*- coding: utf-8 -*-
"""Ramas de error de security._is_allowed_origin y _get_request_port."""


import pytest

from gui_backend import security as sec


@pytest.mark.parametrize("origin", [
    "http://",                       # host ausente
    "http://[::1",                   # IPv6 malformado
    "ftp://127.0.0.1:8000",          # esquema no permitido
    "http://127.0.0.1:notaport",     # puerto no numerico
    "null",                          # sandbox de privacidad
    "http://127.0.0.1:8000\n",       # control char
    "http://evil.example",           # host externo
])
def test_is_allowed_origin_rechaza_malformados(origin):
    assert sec._is_allowed_origin(origin, expected_port=8000) is False


@pytest.mark.parametrize("origin,puerto", [
    ("http://127.0.0.1:8000", 8000),
    ("http://localhost:8000", 8000),
    ("https://127.0.0.1:8443", 8443),
])
def test_is_allowed_origin_acepta_loopback_con_puerto(origin, puerto):
    assert sec._is_allowed_origin(origin, expected_port=puerto) is True


def test_is_allowed_origin_rechaza_puerto_distinto():
    assert sec._is_allowed_origin("http://127.0.0.1:9999", expected_port=8000) is False


class _UrlFalsa:
    def __init__(self, port=None, scheme="http"):
        self.port = port
        self.scheme = scheme


class _ReqFalso:
    def __init__(self, port=None, scheme="http", host=None):
        self.url = _UrlFalsa(port, scheme)
        self.headers = {} if host is None else {"host": host}


def test_get_request_port_usa_url():
    assert sec._get_request_port(_ReqFalso(port=8000)) == 8000


@pytest.mark.parametrize("host,esperado", [
    ("[::1]:8000", 8000),      # IPv6 con corchetes
    ("127.0.0.1:8123", 8123),
    ("127.0.0.1", 80),         # sin puerto -> default del esquema
    ("127.0.0.1:abc", 80),     # puerto invalido -> default
])
def test_get_request_port_parsea_host(host, esperado):
    assert sec._get_request_port(_ReqFalso(host=host)) == esperado


def test_get_request_port_esquema_ws_default_80():
    assert sec._get_request_port(_ReqFalso(scheme="ws", host="127.0.0.1")) == 80
    assert sec._get_request_port(_ReqFalso(scheme="wss", host="127.0.0.1")) == 443


def test_get_request_port_tolera_url_sin_atributos():
    class _Roto:
        headers = {}
    assert sec._get_request_port(_Roto()) == 80  # AttributeError -> default http
