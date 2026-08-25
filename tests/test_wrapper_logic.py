# -*- coding: utf-8 -*-
"""Lógica del hilo lector del wrapper (`read_stdout`): regresiones como tests pytest REALES.

HISTORIAL: este archivo era un script manual (funciones t1..t9 ejecutadas por
`run_case()` al importarse, que imprimía [PASS]/[FAIL] tragándose los
AssertionError): pytest recolectaba 0 tests y estas regresiones críticas del
parser NO podían fallar jamás. Además, al importarse durante la suite, los
`_emit_event` de `read_stdout` escribían en el directorio REAL
`data/wrapper_events/` de la instalación. Migrado a funciones `test_*`
(pendiente documentado en docs/INFORME_COLGADO_SPAWN_WORKER.md §8.3).
Los ejemplos de `_resolve_snapshot_path` del antiguo t7-t9 NO se duplican aquí:
esas propiedades ya viven, con más fuerza, en tests/test_pbt_properties.py
(test_resolve_path_traversal incluye "../../../etc/passwd" y
"C:/Windows/System32" como @example, y test_resolve_known_paths cubre las
rutas válidas).

Escenarios (regresiones históricas del parser, antes sin cobertura efectiva):
- list normal y con ruido de logs entre encabezado y nombres.
- 'list' pendiente cuando arranca un backup (bug original de contaminación).
- abandono de la ventana de continuación tras >10 líneas de ruido.
- connect/disconnect actualiza players_online.
- xuid sin espacio durante la ventana de snapshot (sin entradas espurias).
- reintentos de save query no acumulan snapshots viejos.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server_wrapper as sw
import wrapper_state as wstate


class _FakeStdout:
    def __init__(self, lines):
        self._lines = list(lines)

    def readline(self):
        return self._lines.pop(0) if self._lines else ""


class _FakeProcess:
    def __init__(self, lines):
        self.stdout = _FakeStdout(lines)


def _reset_wstate():
    """Estado que muta read_stdout, limpio antes y después de cada test."""
    wstate.players_online.clear()
    wstate.backup_in_progress = False
    wstate.backup_dispatched = False
    wstate.save_query_ready_seen = False
    wstate.last_save_snapshot = []
    wstate.expecting_list_names = False
    wstate.last_snapshot_update_time = 0.0
    wstate.server_process = None


@pytest.fixture
def wrapper_env(monkeypatch, tmp_path):
    """Canal de eventos NDJSON aislado en tmp + estado del wrapper limpio.

    read_stdout emite eventos por el canal NDJSON: sin este aislamiento cada
    corrida de la suite escribía archivos be_*.ndjson en data/wrapper_events/
    de la instalación real (dato de instalación, no del repo).
    """
    monkeypatch.setenv("WRAPPER_EVENTS_FILE", os.path.join(str(tmp_path), "ev.ndjson"))
    sw._reset_events_for_tests()
    _reset_wstate()
    yield
    _reset_wstate()
    sw._reset_events_for_tests()


def _feed(lines):
    wstate.server_process = _FakeProcess(lines)
    sw.read_stdout()


def test_list_normal_header_y_nombres_en_linea_siguiente(wrapper_env):
    _feed([
        "[INFO] list\n",
        "There are 2/10 players online:\n",
        "Alice, Bob\n",
    ])
    assert wstate.players_online == {"Alice", "Bob"}
    assert wstate.expecting_list_names is False


def test_list_con_ruido_de_logs_entre_header_y_nombres(wrapper_env):
    _feed([
        "There are 2/10 players online:\n",
        "[2026-07-23 10:00:00:001 INFO] Chunk loaded at (10,20)\n",
        "[2026-07-23 10:00:00:002 INFO] Autosave tick\n",
        "Alice, Bob\n",
    ])
    assert wstate.players_online == {"Alice", "Bob"}
    assert wstate.expecting_list_names is False


def test_lista_pendiente_mas_arranque_backup_no_contamina_players(wrapper_env):
    """Bug original: un encabezado 'There are X/Y players online:' dejaba la
    ventana de nombres pendiente; si el scheduler arrancaba un backup, la
    línea 'Data saved...' entraba como nombre de jugador."""
    _feed([
        "There are 1/10 players online:\n",  # deja expecting_list_names=True
    ])
    assert wstate.expecting_list_names is True
    # El scheduler arranca un backup caliente y limpia la ventana pendiente
    # (mismo fix que aplica backup_scheduler antes de mandar 'save hold').
    with wstate.state_lock:
        wstate.backup_in_progress = True
        wstate.expecting_list_names = False
    _feed([
        "Data saved. Files are now ready to be copied.\n",
        "level.dat:6304, db/000030.ldb:1917505\n",
    ])
    assert "Data saved. Files are now ready to be copied." not in wstate.players_online
    assert wstate.save_query_ready_seen is True
    assert ("level.dat", 6304) in wstate.last_save_snapshot
    assert ("db/000030.ldb", 1917505) in wstate.last_save_snapshot


def test_ventana_de_nombres_pendientes_se_abandona_tras_ruido(wrapper_env):
    """Un encabezado 'list' con nombres en línea siguiente que nunca llega no
    debe dejar la ventana abierta para siempre: tras >10 líneas de ruido la
    continuación se abandona (si no, cualquier línea suelta posterior podría
    entrar como lista de jugadores)."""
    ruido = ["[2026-07-23 10:00:00:%03d INFO] Tick %d\n" % (i, i) for i in range(11)]
    _feed(["There are 2/10 players online:\n"] + ruido)
    assert wstate.expecting_list_names is False
    assert wstate.players_online == set()


def test_connect_y_disconnect_actualizan_players(wrapper_env):
    _feed([
        "[INFO] Player connected: Steve, xuid: 123456789012345\n",
        "[INFO] Player connected: Alex, xuid: 987654321098765\n",
        "[INFO] Player disconnected: Steve, xuid: 123456789012345\n",
    ])
    assert wstate.players_online == {"Alex"}


def test_xuid_sin_espacio_durante_snapshot_no_agrega_espurios(wrapper_env):
    """Regresión: 'Player connected: Bob, xuid:123' (sin espacio) puede casar
    con el patrón texto:numero de save query; durante la ventana de snapshot
    activa NO debe agregarse entrada espuria alguna al snapshot (el guard
    excluye líneas de conexión/desconexión)."""
    wstate.backup_in_progress = True
    wstate.backup_dispatched = False
    wstate.save_query_ready_seen = True
    wstate.last_save_snapshot = [("level.dat", 100)]
    wstate.last_snapshot_update_time = __import__("time").time()
    _feed([
        "[INFO] Player connected: Bob, xuid:12345678901234567\n",
    ])
    assert wstate.last_save_snapshot == [("level.dat", 100)]
    assert wstate.players_online == {"Bob"}


def test_reintentos_de_save_query_no_acumulan_snapshots_viejos(wrapper_env):
    """Un segundo 'Data saved' (reintento de save query) reinicia el snapshot:
    los archivos del intento anterior no deben mezclarse con los del nuevo."""
    wstate.backup_in_progress = True
    wstate.backup_dispatched = False
    _feed([
        "Data saved. Files are now ready to be copied.\n",
        "level.dat:100\n",
        "Data saved. Files are now ready to be copied.\n",  # reintento
        "level.dat:100, level.dat_old:100\n",
    ])
    assert wstate.last_save_snapshot == [("level.dat", 100), ("level.dat_old", 100)]
