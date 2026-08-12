"""Guardas de seguridad compartidas: loopback, Origin anti-CSRF y zip-slip."""

import os
from urllib.parse import urlsplit

from fastapi import HTTPException, Request


def _ensure_local(client_host: str):
    """S1: Solo acepta peticiones desde la propia máquina (loopback)."""
    if client_host not in ("127.0.0.1", "::1"):
        raise HTTPException(status_code=403, detail="Acceso denegado: solo conexiones locales")

_LOCAL_ORIGIN_HOSTS = ("127.0.0.1", "localhost")

def _is_allowed_origin(origin: str | None) -> bool:
    """S3: True si el header Origin viene de la propia máquina.

    Los navegadores siempre envían Origin en POST y en el handshake de
    WebSocket. Una página web maliciosa abierta en el navegador del usuario
    genera conexiones desde 127.0.0.1 (superando _ensure_local), así que el
    Origin es el único filtro que distingue "la GUI local" de "una web externa".
    Clientes sin navegador (curl, scripts) no envían Origin: se permiten y
    queda el filtro de IP como respaldo.
    """
    if not origin:
        return True
    try:
        host = urlsplit(origin).hostname
    except ValueError:
        return False
    return host in _LOCAL_ORIGIN_HOSTS

def _check_origin(request: Request):
    """Rechaza peticiones de navegador cuyo Origin no sea loopback (anti-CSRF)."""
    if not _is_allowed_origin(request.headers.get("origin")):
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
