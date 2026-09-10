# -*- coding: utf-8 -*-
"""Hardening regresiones para security y zip_safety.

Cubre:
- _is_allowed_origin robusto ante "null", vacios con espacios, control chars,
  host ausente, esquema malformado y puertos.
- _get_request_port con Host IPv6, Host sin puerto, Host malformado.
- _is_safe_zip_entry rechaza null byte (no rompe consenso).
- wrapper_schedule _coerce_schedule_value acepta "30.0" y "  60  ".
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gui_backend.security as sec
import zip_safety as zs
import wrapper_schedule
from hypothesis import given, strategies as st, settings, HealthCheck, example
from unittest.mock import Mock

import pytest


# ── zip_safety null byte ──
def test_zip_rejects_null_byte():
    assert zs._is_safe_zip_entry("a\x00b") is False
    assert zs._is_safe_zip_entry("level.dat\x00") is False
    assert zs._is_safe_zip_entry("normal/file.txt") is True
    assert zs._is_safe_zip_entry("") is True  # compat: "" sigue como antes (join degenerado)


@given(st.text(alphabet=st.characters(blacklist_categories=("Cs",)), min_size=0, max_size=50))
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_zip_null_byte_property(s):
    """Si el nombre contiene null byte se rechaza, sin importar el resto."""
    if "\x00" in s:
        assert zs._is_safe_zip_entry(s) is False


# ── _is_allowed_origin ──
def test_origin_null_rejected():
    assert sec._is_allowed_origin("null", expected_port=8000) is False
    assert sec._is_allowed_origin("Null", expected_port=8000) is False
    assert sec._is_allowed_origin("   null   ", expected_port=8000) is False


def test_origin_with_spaces_trimmed():
    assert sec._is_allowed_origin("  http://127.0.0.1:8000  ", expected_port=8000) is True
    assert sec._is_allowed_origin(" http://evil.com:8000 ", expected_port=8000) is False


def test_origin_control_char_rejected():
    assert sec._is_allowed_origin("http://127.0.0.1:8000\x00", expected_port=8000) is False
    assert sec._is_allowed_origin("http://127.0.0.1:8000\n", expected_port=8000) is False


def test_origin_missing_host_rejected():
    assert sec._is_allowed_origin("http://", expected_port=8000) is False
    assert sec._is_allowed_origin("http:///path", expected_port=8000) is False
    assert sec._is_allowed_origin("https://", expected_port=443) is False


def test_origin_scheme_case_insensitive():
    assert sec._is_allowed_origin("HTTP://127.0.0.1:8000", expected_port=8000) is True
    assert sec._is_allowed_origin("Ws://127.0.0.1:8000", expected_port=8000) is True


def test_origin_default_port_fallback():
    # sin puerto explicito, se asume 80 para http/ws y 443 para https/wss
    assert sec._is_allowed_origin("http://127.0.0.1", expected_port=80) is True
    assert sec._is_allowed_origin("http://127.0.0.1", expected_port=8000) is False
    assert sec._is_allowed_origin("https://127.0.0.1", expected_port=443) is True
    assert sec._is_allowed_origin("https://localhost", expected_port=443) is True
    assert sec._is_allowed_origin("ws://127.0.0.1", expected_port=80) is True
    assert sec._is_allowed_origin("wss://127.0.0.1", expected_port=443) is True


def test_origin_malicious_subdomain_rejected():
    assert sec._is_allowed_origin("http://127.0.0.1.evil.com:8000", expected_port=8000) is False
    assert sec._is_allowed_origin("http://evil-127.0.0.1.com", expected_port=8000) is False


@given(st.text(min_size=0, max_size=40))
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@example("null")
@example("http://127.0.0.1:8000")
@example("")
def test_origin_never_crash(s):
    """Nunca lanza, solo True/False."""
    try:
        res = sec._is_allowed_origin(s, expected_port=8000)
        assert isinstance(res, bool)
        res2 = sec._is_allowed_origin(s, expected_port=None)
        assert isinstance(res2, bool)
    except Exception as e:
        pytest.fail(f"Crash con {s!r}: {e}")


# ── _get_request_port ──
def _mock_request(url_port, host_hdr, scheme="http"):
    m = Mock()
    m.url.port = url_port
    m.url.scheme = scheme
    # headers como dict real; Mock no necesita override
    if host_hdr is not None:
        m.headers = {"host": host_hdr}
    else:
        m.headers = {}
    # asegurar que .get funciona (dict ya lo tiene)
    return m


def test_get_request_port_direct():
    assert sec._get_request_port(_mock_request(8000, "ignored")) == 8000
    assert sec._get_request_port(_mock_request(None, "127.0.0.1:9000")) == 9000
    assert sec._get_request_port(_mock_request(None, "127.0.0.1")) == 80
    assert sec._get_request_port(_mock_request(None, "127.0.0.1", scheme="https")) == 443
    assert sec._get_request_port(_mock_request(None, "[::1]:8000")) == 8000
    assert sec._get_request_port(_mock_request(None, "[::1]")) == 80
    assert sec._get_request_port(_mock_request(None, "bad:port")) == 80
    assert sec._get_request_port(_mock_request(None, None)) == 80
    assert sec._get_request_port(_mock_request(None, None, scheme="wss")) == 443


@given(st.integers(min_value=1, max_value=65535))
@settings(max_examples=100)
def test_get_request_port_never_crash(port):
    req = _mock_request(port, f"host:{port}")
    assert sec._get_request_port(req) == port
    req2 = _mock_request(None, f"127.0.0.1:{port}")
    assert sec._get_request_port(req2) == port


# ── wrapper_schedule _coerce ──
def test_coerce_interval_string_float():
    assert wrapper_schedule._coerce_schedule_value("backup_interval_min", "30.0") == 30
    assert wrapper_schedule._coerce_schedule_value("backup_interval_min", "  60  ") == 60
    assert wrapper_schedule._coerce_schedule_value("backup_interval_min", "30.5") == 30  # default por no entero
    # fuera de rango sigue defaulteando
    assert wrapper_schedule._coerce_schedule_value("backup_interval_min", "4") == 30
    assert wrapper_schedule._coerce_schedule_value("backup_interval_min", "1441") == 30


def test_coerce_interval_float_type():
    assert wrapper_schedule._coerce_schedule_value("backup_interval_min", 30.0) == 30
    assert wrapper_schedule._coerce_schedule_value("backup_interval_min", 30.5) == 30  # is_integer false -> default


@given(st.integers(min_value=5, max_value=1440))
@settings(max_examples=100)
def test_coerce_interval_roundtrip_valid(v):
    assert wrapper_schedule._coerce_schedule_value("backup_interval_min", v) == v
    assert wrapper_schedule._coerce_schedule_value("backup_interval_min", str(v)) == v
    assert wrapper_schedule._coerce_schedule_value("backup_interval_min", float(v)) == v
    assert wrapper_schedule._coerce_schedule_value("backup_interval_min", f"  {v}  ") == v


def test_load_schedule_config_size_cache(tmp_path, monkeypatch):
    """_load_schedule_config usa mtime+size: cambio rapido sin mtime sigue recargando."""
    cfg_path = tmp_path / "schedule_config.json"
    cfg_path.write_text('{"backup_interval_min": 30}', encoding="utf-8")
    monkeypatch.setattr(wrapper_schedule, "SCHEDULE_CONFIG_PATH", str(cfg_path))
    wrapper_schedule._schedule_cfg_cache["mtime"] = None
    wrapper_schedule._schedule_cfg_cache.pop("size", None)
    c1 = wrapper_schedule._load_schedule_config()
    assert c1["backup_interval_min"] == 30
    # escribir contenido distinto con tamaño diferente (30 -> 5 cambia 1 byte)
    import os
    cfg_path.write_text('{"backup_interval_min": 5}', encoding="utf-8")
    # forzar mtime igual al cacheado para simular granularidad 1s
    cached_mtime = wrapper_schedule._schedule_cfg_cache["mtime"]
    if cached_mtime is not None:
        os.utime(str(cfg_path), (cached_mtime, cached_mtime))
    c2 = wrapper_schedule._load_schedule_config()
    # debe haber recargado por size distinto aunque mtime igual
    assert c2["backup_interval_min"] == 5


# ── Modo LAN opt-in (GUI_ALLOW_LAN): gates S1/S3 con IPs privadas ──────
# El modo LAN relaja _ensure_local/_is_allowed_origin/_is_allowed_client_host
# a la red privada RFC1918 SOLO cuando el usuario lo habilita. Sin cobertura
# previa: es un limite de seguridad nuevo y el default historico (solo
# loopback) debe seguir intacto sin env.

@pytest.fixture
def _sin_lan(monkeypatch):
    monkeypatch.delenv("GUI_ALLOW_LAN", raising=False)
    return monkeypatch


def test_allow_lan_acepta_solo_valores_verdaderos(_sin_lan):
    for v in ("1", "true", "True", "YES", "yes", "on", "ON"):
        _sin_lan.setenv("GUI_ALLOW_LAN", v)
        assert sec._allow_lan() is True, v
    for v in ("0", "false", "no", "off", "", "garbage", "2"):
        _sin_lan.setenv("GUI_ALLOW_LAN", v)
        assert sec._allow_lan() is False, v


def test_is_private_ip_ejemplos():
    assert sec._is_private_ip("192.168.1.70") is True
    assert sec._is_private_ip("10.0.0.5") is True
    assert sec._is_private_ip("172.16.0.1") is True
    assert sec._is_private_ip("172.32.0.1") is False   # fuera de 172.16/12
    assert sec._is_private_ip("8.8.8.8") is False      # publica
    assert sec._is_private_ip("") is False
    assert sec._is_private_ip("   ") is False
    assert sec._is_private_ip("basura") is False
    assert sec._is_private_ip("127.0.0.1") is True     # loopback cuenta como privada
    assert sec._is_private_ip("[fd00::5]") is True     # IPv6 ULA con corchetes
    assert sec._is_private_ip("::1") is True


@given(st.text(min_size=0, max_size=60))
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_is_private_ip_never_crash(s):
    """ipaddress lanza ValueError ante basura: la funcion nunca debe propagarlo."""
    try:
        res = sec._is_private_ip(s)
        assert isinstance(res, bool)
    except Exception as e:
        pytest.fail(f"Crash con {s!r}: {e}")


def test_client_host_loopback_siempre_aceptado(_sin_lan):
    for host in ("127.0.0.1", "::1", "localhost"):
        assert sec._is_allowed_client_host(host) is True


def test_client_host_privada_solo_con_lan(_sin_lan):
    assert sec._is_allowed_client_host("192.168.1.50") is False
    _sin_lan.setenv("GUI_ALLOW_LAN", "1")
    assert sec._is_allowed_client_host("192.168.1.50") is True
    assert sec._is_allowed_client_host("10.20.30.40") is True


def test_client_host_publica_nunca_aceptada(_sin_lan):
    _sin_lan.setenv("GUI_ALLOW_LAN", "1")
    assert sec._is_allowed_client_host("8.8.8.8") is False
    assert sec._is_allowed_client_host("basura") is False


def test_ensure_local_403_para_externa_sin_lan(_sin_lan):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        sec._ensure_local("203.0.113.9")     # TEST-NET: externa
    assert ei.value.status_code == 403


def test_origin_privada_con_lan_y_puerto_correcto(_sin_lan):
    # Sin LAN: origen privado rechazado (comportamiento historico intacto).
    assert sec._is_allowed_origin("http://192.168.1.70:8000", expected_port=8000) is False
    _sin_lan.setenv("GUI_ALLOW_LAN", "1")
    assert sec._is_allowed_origin("http://192.168.1.70:8000", expected_port=8000) is True
    # Puerto distinto sigue rechazado (anti-CSRF se mantiene en modo LAN).
    assert sec._is_allowed_origin("http://192.168.1.70:9999", expected_port=8000) is False
    # Publica sigue rechazada incluso con LAN.
    assert sec._is_allowed_origin("http://8.8.8.8:8000", expected_port=8000) is False
    # Loopback sigue aceptado igual con LAN activa.
    assert sec._is_allowed_origin("http://127.0.0.1:8000", expected_port=8000) is True


def test_hardening_original_intacto_con_lan_activa(_sin_lan):
    """Activar LAN no reabre los vectores cerrados en la ronda 1."""
    _sin_lan.setenv("GUI_ALLOW_LAN", "1")
    assert sec._is_allowed_origin("null", expected_port=8000) is False
    assert sec._is_allowed_origin("http://127.0.0.1:8000\x00", expected_port=8000) is False
    assert sec._is_allowed_origin("http://evil.com:8000", expected_port=8000) is False
    assert sec._is_allowed_origin("http://192.168.1.70.evil.com:8000", expected_port=8000) is False
