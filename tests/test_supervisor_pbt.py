# -*- coding: utf-8 -*-
"""Robustez del supervisor GUI: lector del canal NDJSON y clasificador de log.

Dos frentes (sugeridos por la Ronda 3 del bucle):

1. `_tail_events`: tolerancia a lineas corruptas a nivel BYTES. El emisor
   (`wrapper_events._emit_event`) escribe con `ensure_ascii=False`, asi que un
   nombre con acentos ocupa varios bytes; una escritura truncada (wrapper
   muerto a mitad de write, corte de luz) puede dejar una secuencia UTF-8
   incompleta en el NDJSON. El lector abre el archivo en modo texto: sin
   tolerancia, `readline()` lanza UnicodeDecodeError, el hilo muere y la GUI
   pierde la fuente AUTORITATIVA del estado (contrato
   docs/INFORME_IPC_EVENTOS_NDJSON.md). Propiedades aqui: basura binaria
   arbitraria jamas mata al lector ni pierde los eventos validos.

2. `classify_log_line`: funcion total (nunca lanza, siempre devuelve uno de
   los 5 tipos) y gate anti-spoofing H-01 en la capa GUI: toda linea cuyo
   texto sin prefijo empieza por `<` (chat) se clasifica "info", jamas
   join/leave.

Todo en tmp (conftest ya aisla WRAPPER_EVENTS_FILE); el data/ real nunca se
toca.
"""
import json
import os
import sys

import pytest
from hypothesis import given, settings, strategies as st, HealthCheck

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server_gui_server as gui
import gui_backend.supervisor as supervisor

LOG_TYPES = {"join", "leave", "backup", "error", "info"}


def _reset_manager_state():
    gui.manager.is_running = False
    gui.manager.start_time = None
    gui.manager.wrapper_process = None
    gui.manager.update_in_progress = False
    gui.manager.backup_in_progress = False
    gui.manager.players_online.clear()
    gui.manager.players_xuid.clear()
    gui.manager.wrapper_exit_event.set()
    gui.manager.server_stopped_event.set()
    gui.manager.events_alive = False
    gui.manager.events_file = None


@pytest.fixture
def canal_gui(tmp_path, monkeypatch):
    """Manager limpio + registro de jugadores aislado en tmp."""
    monkeypatch.setattr(supervisor, "KNOWN_PLAYERS_PATH",
                        os.path.join(str(tmp_path), "known_players.json"))
    _reset_manager_state()
    gui.manager.installed_version = None
    yield os.path.join(str(tmp_path), "ev.ndjson")
    _reset_manager_state()


# ═══════════════════════════════════════════════════════════════════════
# Lector del canal: tolerancia a corrupcion a nivel bytes (UTF-8 roto)
# ═══════════════════════════════════════════════════════════════════════
def test_tail_events_sobrevive_utf8_truncado(canal_gui):
    """Regresion: escritura truncada a mitad de un caracter multibyte.

    'Jose' con acento en UTF-8 son 2 bytes (0xC3 0xA9); si el wrapper muere
    tras el 0xC3, el archivo queda con una secuencia invalida. El lector debe
    saltarse esa linea (decode tolerante -> json falla -> continue) y seguir
    consumiendo los eventos validos posteriores; JAMAS morir dejando la GUI
    sin canal autoritativo hasta reiniciarla.
    """
    valido_1 = json.dumps({"event": "wrapper_started", "pid": 1}).encode("utf-8")
    valido_2 = json.dumps(
        {"event": "version_captured", "version": "1.26.33.2"}
    ).encode("utf-8")
    with open(canal_gui, "wb") as f:
        f.write(valido_1 + b"\n")
        f.write(b'{"event": "player_connected", "name": "Jos\xc3')  # 0xC3 solitario
        f.write(b"\n")
        f.write(valido_2 + b"\n")

    gui.manager.wrapper_exit_event.set()  # modo drenar-y-salir (como tests IPC)
    supervisor._tail_events(canal_gui)

    assert gui.manager.events_alive is True
    assert gui.manager.installed_version == "1.26.33.2"
    # El evento trunco no aplico ningun jugador fantasma
    assert gui.manager.players_online == set()


@settings(max_examples=100, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
@given(st.binary(max_size=512))
def test_tail_events_basura_binaria_no_mata_lector(garbage):
    """PBT: cualquier basura binaria entre dos eventos validos es inocua.

    Propiedad: `_tail_events` nunca lanza, aplica ambos eventos libro y no
    deja jugadores fantasmas, sea cual sea el contenido corrupto intermedio
    (incluidos \\n, \\r, bytes UTF-8 invalidos y fragmentos de JSON).

    Sin fixtures de pytest (no se combinan bien con @given): montaje manual
    hermetico en %TEMP% y reset del manager en finally.
    """
    import shutil
    import tempfile
    mp = pytest.MonkeyPatch()
    tmpdir = tempfile.mkdtemp(prefix="ev_pbt_")
    mp.setattr(supervisor, "KNOWN_PLAYERS_PATH",
               os.path.join(tmpdir, "known_players.json"))
    try:
        _reset_manager_state()
        gui.manager.installed_version = None
        valido_1 = json.dumps({"event": "wrapper_started", "pid": 1}).encode("utf-8")
        valido_2 = json.dumps(
            {"event": "version_captured", "version": "9.9.9.9"}
        ).encode("utf-8")
        path = os.path.join(tmpdir, "ev_pbt.bin")
        with open(path, "wb") as f:
            f.write(valido_1 + b"\n")
            f.write(garbage)
            f.write(b"\n")  # la basura queda confinada a su(s) propia(s) linea(s)
            f.write(valido_2 + b"\n")

        gui.manager.wrapper_exit_event.set()
        supervisor._tail_events(path)

        assert gui.manager.events_alive is True
        assert gui.manager.installed_version == "9.9.9.9"
        assert gui.manager.players_online == set()
    finally:
        mp.undo()
        _reset_manager_state()
        shutil.rmtree(tmpdir, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════
# Clasificador de log (color en la GUI): totalidad y gate anti-spoofing
# ═══════════════════════════════════════════════════════════════════════
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
@given(st.text())
def test_classify_log_line_es_total(linea):
    """Funcion total: nunca lanza y siempre devuelve uno de los 5 tipos."""
    resultado = supervisor.classify_log_line(linea)
    assert resultado in LOG_TYPES


@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
@given(st.text())
def test_classify_log_line_gate_chat_siempre_info(sufijo):
    """Gate H-01 en la capa GUI: chat (<Jugador> ...) jamas es join/leave.

    Aunque el cuerpo del mensaje contenga un marcador completo de conexion o
    version falsificado por un jugador, la clasificacion es "info".
    """
    linea = "<Suplantador> Player connected: Fake, xuid: 1 -- " + sufijo
    assert supervisor.classify_log_line(linea) == "info"


def test_classify_log_line_marcadores_conocidos():
    """Mapa de marcadores reales (ES/EN) a tipo de log."""
    assert supervisor.classify_log_line(
        "[INFO] Player connected: Alice, xuid: 111") == "join"
    assert supervisor.classify_log_line(
        "[2026-08-24 10:00:00:000 INFO] Player connected: Alice, xuid: 111") == "join"
    assert supervisor.classify_log_line(
        "Player connected: Bob, xuid: 222") == "join"
    assert supervisor.classify_log_line(
        "[INFO] Player disconnected: Alice, xuid: 111") == "leave"
    # Fallback bilingue de backups (marcadores de consola del wrapper)
    assert supervisor.classify_log_line(
        "Iniciando compresion de archivos en proceso separado") == "backup"
    assert supervisor.classify_log_line(
        "Starting compression in a separate process") == "backup"
    assert supervisor.classify_log_line("Backup finalizado") == "backup"
    assert supervisor.classify_log_line("Backup finished") == "backup"
    assert supervisor.classify_log_line("[INFO] ERROR loading level") == "error"
    assert supervisor.classify_log_line("WARN algo raro") == "error"
