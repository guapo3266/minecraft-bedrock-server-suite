"""Guardas de seguridad compartidas: loopback, Origin anti-CSRF y zip-slip."""

import os
from urllib.parse import urlsplit

from fastapi import HTTPException, Request


def _ensure_local(client_host: str):
    """S1: Solo acepta peticiones desde la propia máquina (loopback)."""
    if client_host not in ("127.0.0.1", "::1"):
        raise HTTPException(status_code=403, detail="Acceso denegado: solo conexiones locales")

_LOCAL_ORIGIN_HOSTS = ("127.0.0.1", "localhost", "::1")
_ALLOWED_SCHEMES = ("http", "https", "ws", "wss")


def _is_allowed_origin(origin: str | None, expected_port: int | None = None) -> bool:
    """S3: True si el header Origin viene de la propia máquina y coincide el puerto esperado.

    Los navegadores siempre envían Origin en POST y en el handshake de
    WebSocket. Una página web local en otro puerto (p. ej. un servidor web
    malicioso en localhost:9999) o un sitio externo no deben poder interactuar
    con la API o WebSocket de la GUI.
    """
    if not origin:
        return True
    try:
        parts = urlsplit(origin)
        scheme = parts.scheme.lower()
        host = parts.hostname
        port = parts.port
    except ValueError:
        return False
    if scheme and scheme not in _ALLOWED_SCHEMES:
        return False
    if host not in _LOCAL_ORIGIN_HOSTS:
        return False
    if expected_port is not None:
        origin_port = port if port is not None else (80 if scheme in ("http", "ws") else 443)
        if origin_port != expected_port:
            return False
    return True


def _get_request_port(request: Request) -> int | None:
    """Extrae el puerto del request a partir de url.port o Host header."""
    if request.url.port is not None:
        return request.url.port
    host_hdr = request.headers.get("host", "")
    if ":" in host_hdr:
        try:
            return int(host_hdr.split(":")[-1])
        except ValueError:
            pass
    return 80 if request.url.scheme in ("http", "ws") else 443


def _check_origin(request: Request):
    """Rechaza peticiones de navegador cuyo Origin no coincida con el host y puerto local."""
    port = _get_request_port(request)
    if not _is_allowed_origin(request.headers.get("origin"), expected_port=port):
        raise HTTPException(status_code=403, detail="Acceso denegado: origen no permitido")

def _is_safe_zip_entry(filename: str) -> bool:
    """S2: True si la entrada del zip es segura para extraer.

    Conservador: rechaza rutas absolutas, cualquier segmento '..' (traversal,
    incluso normalizado internamente) y prefijos de unidad/ADS tipo 'C:'.
    """
    norm = filename.replace("\\", "/")
    if norm.startswith("/") or os.path.isabs(norm):
        return False
    segs = norm.split("/")
    if any(s == ".." for s in segs):
        return False
    if ":" in segs[0]:
        return False
    return True
