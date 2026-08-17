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


def _events_path():
    return os.environ.get("WRAPPER_EVENTS_FILE") or os.path.join(
        EVENTS_DIR, "be_%d_%s.ndjson" % (int(time.time()), os.urandom(4).hex())
    )


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
    """Escribe un evento JSON de una linea (append + flush, bajo lock)."""
    global _events_handle, _events_file_path
    try:
        with _events_lock:
            if _events_handle is None:
                _events_file_path = _events_path()
                os.makedirs(os.path.dirname(_events_file_path), exist_ok=True)
                _events_handle = open(_events_file_path, "a", encoding="utf-8")
            payload = {"ts": int(time.time() * 1000), "event": event}
            payload.update(data)
            _events_handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
            _events_handle.flush()
    except Exception:
        try:
            if _events_handle is not None:
                _events_handle.close()
        except Exception:
            pass
        _events_handle = None


def _reset_events_for_tests():
    global _events_handle, _events_file_path
    with _events_lock:
        if _events_handle is not None:
            try:
                _events_handle.close()
            except Exception:
                pass
        _events_handle = None
        _events_file_path = None
