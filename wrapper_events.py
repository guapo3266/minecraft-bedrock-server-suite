"""Canal NDJSON de eventos del wrapper hacia la GUI."""

import json
import os
import threading
import time


EVENTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "wrapper_events"
)
EVENTS_RETENTION_DAYS = 7
_events_lock = threading.Lock()
_events_handle = None
_events_file_path = None
# Nombre estable del archivo de eventos en modo standalone (sin
# WRAPPER_EVENTS_FILE): se genera UNA sola vez por proceso. Sin esto,
# _events_path() devolvia una ruta nueva en cada _emit_event y cada evento
# creaba su propio NDJSON de una linea (regresion verificada 2026-08-28:
# decenas de archivos por boot en iniciar_servidor.bat).
_standalone_suffix = None


def _events_path():
    env_path = os.environ.get("WRAPPER_EVENTS_FILE")
    if env_path:
        return env_path
    global _standalone_suffix
    if _standalone_suffix is None:
        _standalone_suffix = "be_%d_%s.ndjson" % (
            int(time.time()), os.urandom(4).hex()
        )
    return os.path.join(EVENTS_DIR, _standalone_suffix)


def _rotate_old_events():
    """Borra logs de eventos con mas de EVENTS_RETENTION_DAYS dias."""
    try:
        cutoff = time.time() - EVENTS_RETENTION_DAYS * 86400
        for name in os.listdir(EVENTS_DIR):
            path = os.path.join(EVENTS_DIR, name)
            try:
                if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                    os.remove(path)
            except OSError:
                pass
    except OSError:
        pass


def _emit_event(event, **data):
    """Escribe un evento JSON de una linea (append + flush + fsync, bajo lock).

    El emisor nunca debe tumbar el wrapper: cualquier fallo se ignora y el
    handle se resetea para reintentar en el proximo evento. Detecta cambio de
    WRAPPER_EVENTS_FILE en runtime (p. ej. tests que cambian env) y reabre.
    """
    global _events_handle, _events_file_path
    try:
        with _events_lock:
            desired_path = _events_path()
            if _events_handle is None or _events_file_path != desired_path:
                if _events_handle is not None:
                    try:
                        _events_handle.close()
                    except Exception:
                        pass
                    _events_handle = None
                _events_file_path = desired_path
                os.makedirs(os.path.dirname(_events_file_path), exist_ok=True)
                _events_handle = open(_events_file_path, "a", encoding="utf-8")
            payload = {"ts": int(time.time() * 1000), "event": event}
            payload.update(data)
            _events_handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
            _events_handle.flush()
            try:
                os.fsync(_events_handle.fileno())
            except Exception:
                pass
    except Exception:
        try:
            if _events_handle is not None:
                _events_handle.close()
        except Exception:
            pass
        _events_handle = None
        _events_file_path = None


def _reset_events_for_tests():
    global _events_handle, _events_file_path, _standalone_suffix
    with _events_lock:
        if _events_handle is not None:
            try:
                _events_handle.close()
            except Exception:
                pass
        _events_handle = None
        _events_file_path = None
        _standalone_suffix = None
