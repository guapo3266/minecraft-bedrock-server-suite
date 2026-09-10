# -*- coding: utf-8 -*-
"""Unitarios de wrapper_events: rotacion de NDJSON por retencion y emision."""
import json
import os
import time

import wrapper_events as we


def test_rotate_borra_viejos_y_conserva_recientes(tmp_path, monkeypatch):
    monkeypatch.setattr(we, "EVENTS_DIR", str(tmp_path))
    viejo = tmp_path / "viejo.ndjson"
    nuevo = tmp_path / "nuevo.ndjson"
    viejo.write_text("x", encoding="utf-8")
    nuevo.write_text("x", encoding="utf-8")
    hace_mucho = time.time() - (we.EVENTS_RETENTION_DAYS + 1) * 86400
    os.utime(str(viejo), (hace_mucho, hace_mucho))

    we._rotate_old_events()

    assert not viejo.exists()
    assert nuevo.exists()


def test_rotate_dir_inexistente_no_lanza(tmp_path, monkeypatch):
    monkeypatch.setattr(we, "EVENTS_DIR", str(tmp_path / "no_existe"))
    we._rotate_old_events()  # no debe lanzar


def test_emit_event_escribe_ndjson_valido(tmp_path, monkeypatch):
    destino = tmp_path / "ev.ndjson"
    monkeypatch.setenv("WRAPPER_EVENTS_FILE", str(destino))
    we._reset_events_for_tests()
    try:
        we._emit_event("prueba", valor=42)
        lineas = destino.read_text(encoding="utf-8").strip().splitlines()
        assert len(lineas) == 1
        evento = json.loads(lineas[0])
        assert evento["event"] == "prueba"
        assert evento["valor"] == 42
        assert isinstance(evento["ts"], int)
    finally:
        we._reset_events_for_tests()


def test_emit_event_reabre_al_cambiar_el_env(tmp_path, monkeypatch):
    """El wrapper (y los tests) pueden cambiar WRAPPER_EVENTS_FILE en runtime:
    el emisor debe cerrar el handle viejo y escribir en el nuevo."""
    primero = tmp_path / "a.ndjson"
    segundo = tmp_path / "b.ndjson"
    monkeypatch.setenv("WRAPPER_EVENTS_FILE", str(primero))
    we._reset_events_for_tests()
    try:
        we._emit_event("uno")
        monkeypatch.setenv("WRAPPER_EVENTS_FILE", str(segundo))
        we._emit_event("dos")

        assert json.loads(primero.read_text(encoding="utf-8").strip())["event"] == "uno"
        assert json.loads(segundo.read_text(encoding="utf-8").strip())["event"] == "dos"
    finally:
        we._reset_events_for_tests()


def test_emit_event_con_path_invalido_no_lanza(tmp_path, monkeypatch):
    """Un path que no se puede abrir (p. ej. un directorio) no debe tumbar al
    emisor: el contrato dice que nunca propaga."""
    monkeypatch.setenv("WRAPPER_EVENTS_FILE", str(tmp_path))
    we._reset_events_for_tests()
    try:
        we._emit_event("no-debe-crashear", valor=1)
    finally:
        we._reset_events_for_tests()


def test_events_path_standalone_es_estable(tmp_path, monkeypatch):
    """Sin WRAPPER_EVENTS_FILE, el path se genera UNA vez por proceso (no un
    NDJSON nuevo por evento)."""
    monkeypatch.delenv("WRAPPER_EVENTS_FILE", raising=False)
    monkeypatch.setattr(we, "EVENTS_DIR", str(tmp_path))
    we._reset_events_for_tests()
    try:
        primero = we._events_path()
        segundo = we._events_path()
        assert primero == segundo
        assert primero.startswith(str(tmp_path))
        assert primero.endswith(".ndjson")
    finally:
        we._reset_events_for_tests()
