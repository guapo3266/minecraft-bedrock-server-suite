# -*- coding: utf-8 -*-
"""Lector del canal NDJSON (`_tail_events`): espera el archivo, tolera basura
y termina cuando el wrapper muere."""

import json
import threading
import time

import gui_backend.supervisor as sup
from gui_backend.state import manager


def test_tail_events_espera_archivo_drena_y_termina(tmp_path, monkeypatch):
    ruta = tmp_path / "ev.ndjson"

    def _escribir():
        time.sleep(0.3)
        ruta.write_text(
            "\n".join([
                json.dumps({"event": "wrapper_started", "pid": 1}),
                "esto-no-es-json",
                json.dumps({"event": "version_captured", "version": "1.2.3.4"}),
            ]) + "\n",
            encoding="utf-8",
        )

    escritor = threading.Thread(target=_escribir, daemon=True)
    escritor.start()

    monkeypatch.setattr(manager, "events_alive", False)
    monkeypatch.setattr(manager, "installed_version", None)
    manager.wrapper_exit_event.clear()
    hilo = threading.Thread(target=sup._tail_events, args=(str(ruta),), daemon=True)
    hilo.start()

    deadline = time.time() + 5
    while time.time() < deadline and manager.installed_version != "1.2.3.4":
        time.sleep(0.05)

    assert manager.events_alive is True
    assert manager.installed_version == "1.2.3.4"

    manager.wrapper_exit_event.set()
    hilo.join(timeout=3)
    assert not hilo.is_alive(), "el lector no termino tras morir el wrapper"
    escritor.join(timeout=3)
