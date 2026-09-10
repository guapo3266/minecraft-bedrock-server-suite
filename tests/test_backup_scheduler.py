# -*- coding: utf-8 -*-
"""Una iteracion real de `backup_scheduler` por rama (IDLE, HOLDING, watchdog).

El loop es `while True` con `time.sleep(1)`: se corre el cuerpo una vez y se
corta el segundo sleep lanzando KeyboardInterrupt. Sin BDS ni mundo real.
"""
import threading
import time

import pytest

import server_wrapper as sw
import wrapper_state as wstate

_CAMPOS = (
    "backup_in_progress", "backup_dispatched", "watchdog_fired",
    "save_query_ready_seen", "last_backup_completed_time", "save_hold_timestamp",
    "last_save_snapshot", "last_snapshot_update_time", "snapshot_retry_at",
    "snapshot_retry_count", "expecting_list_names", "server_process",
    "shutting_down", "backup_cancel_event", "active_compress_process",
)


class _ProcesoVivo:
    def poll(self):
        return None


class _ProcesoMuerto:
    def poll(self):
        return 1


@pytest.fixture
def scheduler_env(tmp_path, monkeypatch):
    previo = {c: getattr(wstate, c) for c in _CAMPOS}
    previo_players = set(wstate.players_online)
    monkeypatch.setattr(
        sw.wrapper_schedule, "SCHEDULE_CONFIG_PATH", str(tmp_path / "no_existe.json")
    )
    wstate.players_online.clear()
    with wstate.state_lock:
        wstate.backup_in_progress = False
        wstate.backup_dispatched = False
        wstate.watchdog_fired = False
        wstate.save_query_ready_seen = False
        wstate.last_backup_completed_time = time.time()
        wstate.save_hold_timestamp = 0.0
        wstate.last_save_snapshot = []
        wstate.last_snapshot_update_time = 0.0
        wstate.snapshot_retry_at = 0.0
        wstate.snapshot_retry_count = 0
        wstate.expecting_list_names = False
        wstate.server_process = _ProcesoVivo()
        wstate.shutting_down = False
        wstate.backup_cancel_event = None
        wstate.active_compress_process = None
    yield
    wstate.players_online.clear()
    wstate.players_online.update(previo_players)
    with wstate.state_lock:
        for campo, valor in previo.items():
            setattr(wstate, campo, valor)


def _una_iteracion(monkeypatch):
    llamadas = {"sleep": 0}

    def _sleep(_segundos):
        llamadas["sleep"] += 1
        if llamadas["sleep"] >= 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(sw.time, "sleep", _sleep)
    with pytest.raises(KeyboardInterrupt):
        sw.backup_scheduler()


def test_idle_con_jugador_e_intervalo_vencido_inicia_save_hold(
    scheduler_env, monkeypatch
):
    comandos = []
    monkeypatch.setattr(sw, "send_command", comandos.append)
    with wstate.state_lock:
        wstate.last_backup_completed_time = time.time() - 31 * 60
    wstate.players_online.add("Alice")

    _una_iteracion(monkeypatch)

    assert "save hold" in comandos
    with wstate.state_lock:
        assert wstate.backup_in_progress is True
        assert wstate.save_query_ready_seen is False
        assert wstate.watchdog_fired is False


def test_idle_sin_jugadores_solo_skippea(scheduler_env, monkeypatch):
    comandos = []
    monkeypatch.setattr(sw, "send_command", comandos.append)
    with wstate.state_lock:
        wstate.last_backup_completed_time = time.time() - 31 * 60

    _una_iteracion(monkeypatch)

    assert "save hold" not in comandos
    with wstate.state_lock:
        assert wstate.backup_in_progress is False
        assert wstate.last_backup_completed_time > time.time() - 5  # consumio el vencimiento


def test_holding_sin_respuesta_dispara_watchdog_y_resume(scheduler_env, monkeypatch):
    comandos = []
    monkeypatch.setattr(sw, "send_command", comandos.append)
    with wstate.state_lock:
        wstate.backup_in_progress = True
        wstate.backup_dispatched = False
        wstate.save_query_ready_seen = False
        wstate.save_hold_timestamp = time.time() - 61

    _una_iteracion(monkeypatch)

    assert "save resume" in comandos
    with wstate.state_lock:
        assert wstate.backup_in_progress is False
        assert wstate.watchdog_fired is True


def test_holding_con_snapshot_listo_despacha_worker(scheduler_env, monkeypatch):
    despachos = []
    listo = threading.Event()

    def _worker(snapshot, cancel_event):
        despachos.append(snapshot)
        listo.set()

    monkeypatch.setattr(sw.wrapper_backup, "execute_backup_worker", _worker)
    with wstate.state_lock:
        wstate.backup_in_progress = True
        wstate.backup_dispatched = False
        wstate.save_query_ready_seen = True
        wstate.last_save_snapshot = [("level.dat", 10)]
        wstate.last_snapshot_update_time = time.time() - 6
        wstate.save_hold_timestamp = time.time() - 6

    _una_iteracion(monkeypatch)

    assert listo.wait(timeout=5), "el worker no se despacho"
    assert despachos == [[("level.dat", 10)]]
    with wstate.state_lock:
        assert wstate.backup_dispatched is True
        assert wstate.save_query_ready_seen is False


def test_proceso_muerto_corta_el_loop_sin_comandos(scheduler_env, monkeypatch):
    comandos = []
    monkeypatch.setattr(sw, "send_command", comandos.append)
    wstate.server_process = _ProcesoMuerto()
    monkeypatch.setattr(sw.time, "sleep", lambda _s: None)

    sw.backup_scheduler()  # retorna al ver poll() != None

    assert comandos == []
