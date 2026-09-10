"""Guardas de seguridad compartidas: loopback, Origin anti-CSRF y zip-slip.

Soporte LAN opt-in: si `GUI_ALLOW_LAN=1` (ver server_gui_server.py) se
permiten también clientes de la red privada RFC1918 (10/8, 172.16/12,
192.168/16) además de loopback. Por defecto (sin env) mantiene el
comportamiento histórico: solo loopback.
"""

import ipaddress
import os
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

from zip_safety import _is_safe_zip_entry  # noqa: F401  (re-export: lo importa bds_update)


def _allow_lan() -> bool:
    """True si el usuario habilitó acceso desde la LAN local."""
    return os.environ.get("GUI_ALLOW_LAN", "").lower() in ("1", "true", "yes", "on")


def _is_private_ip(host: str) -> bool:
    """True si host es una IP privada RFC1918 (para modo LAN)."""
    if not host:
        return False
    h = host.strip().strip("[]")
    try:
        return ipaddress.ip_address(h).is_private
    except ValueError:
        return False


def _is_allowed_client_host(host: str) -> bool:
    """S1: loopback siempre; privada solo con GUI_ALLOW_LAN=1."""
    if host in ("127.0.0.1", "::1", "localhost"):
        return True
    if _allow_lan() and _is_private_ip(host):
        return True
    return False


def _ensure_local(client_host: str):
    """S1: Solo acepta peticiones desde la propia máquina (loopback).

    Con GUI_ALLOW_LAN=1 permite también IPs privadas de la LAN.
    """
    if not _is_allowed_client_host(client_host):
        raise HTTPException(status_code=403, detail="Acceso denegado: solo conexiones locales")

_LOCAL_ORIGIN_HOSTS = ("127.0.0.1", "localhost", "::1")
_ALLOWED_SCHEMES = ("http", "https", "ws", "wss")


def _is_allowed_origin(origin: str | None, expected_port: int | None = None) -> bool:
    """S3: True si el header Origin viene de la propia máquina y coincide el puerto esperado.

    Los navegadores siempre envían Origin en POST y en el handshake de
    WebSocket. Una página web local en otro puerto (p. ej. un servidor web
    malicioso en localhost:9999) o un sitio externo no deben poder interactuar
    con la API o WebSocket de la GUI.

    Robustez: maneja Origin malformado, host ausente, esquema ausente y
    valores tipo "null" (privacy) como no permitidos cuando hay Origin.
    """
    if not origin:
        return True
    # Rechazar control / null byte antes de strip (un trailing \n oculta el control)
    if "\x00" in origin or any(ord(c) < 0x20 for c in origin):
        return False
    origin = origin.strip()
    if not origin or origin.lower() == "null":
        return False
    try:
        parts = urlsplit(origin)
        scheme = (parts.scheme or "").lower()
        host = parts.hostname
        port = parts.port
    except ValueError:
        return False
    # Host ausente (p.ej. Origin: "http://") -> no permitido
    if not host:
        return False
    # Normalizar host para comparación (urlsplit ya lower para hostname, pero por si)
    host = host.lower()
    if scheme and scheme not in _ALLOWED_SCHEMES:
        return False
    if host not in _LOCAL_ORIGIN_HOSTS:
        # Modo LAN: permite Origin con IP privada (p.ej. http://192.168.1.70:8000)
        if not (_allow_lan() and _is_private_ip(host)):
            return False
    if expected_port is not None:
        try:
            exp = int(expected_port)
        except (TypeError, ValueError):
            exp = None
        if exp is not None:
            origin_port = port if port is not None else (80 if scheme in ("http", "ws") else 443)
            if origin_port != exp:
                return False
    return True


def _get_request_port(request):
    """Extrae el puerto esperado a partir de url.port o Host header.

    Acepta Request Y WebSocket (duck-typing: ambos exponen .url.port,
    .headers.get("host") y .url.scheme — el router /ws la usa como fuente
    unica anti-drift del guard S3).

    Soporta Host con puerto, Host sin puerto, y esquemas http/https/ws/wss.
    Ante Host malformado devuelve el puerto por defecto del esquema.
    """
    try:
        if request.url.port is not None:
            return int(request.url.port)
    except (ValueError, TypeError, AttributeError):
        pass
    host_hdr = (request.headers.get("host") or "").strip()
    # Host puede ser "[::1]:8000" o "127.0.0.1:8000" — tomar ultimo ":port"
    if host_hdr:
        # Manejar IPv6 con corchetes
        if host_hdr.startswith("["):
            # "[::1]:8000" -> buscar "]:"
            try:
                if "]:" in host_hdr:
                    return int(host_hdr.rsplit(":", 1)[-1])
            except ValueError:
                pass
        elif ":" in host_hdr:
            try:
                return int(host_hdr.rsplit(":", 1)[-1])
            except ValueError:
                pass
    try:
        scheme = (request.url.scheme or "").lower()
    except AttributeError:
        scheme = "http"
    return 80 if scheme in ("http", "ws") else 443


def _check_origin(request: Request):
    """Rechaza peticiones de navegador cuyo Origin no coincida con el host y puerto local."""
    port = _get_request_port(request)
    if not _is_allowed_origin(request.headers.get("origin"), expected_port=port):
        raise HTTPException(status_code=403, detail="Acceso denegado: origen no permitido")

# _is_safe_zip_entry re-exportado desde zip_safety (fuente unica anti-drift)
# La implementacion vive en zip_safety.py; este alias mantiene compatibilidad
# con los imports existentes (server_gui_server, bds_update, tests).
