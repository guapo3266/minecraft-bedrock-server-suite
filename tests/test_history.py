# -*- coding: utf-8 -*-
"""Historial persistente: sinks del manager, servicio SQLite y endpoints.

La DB siempre va a tmp (patch de DB_PATH): los tests nunca tocan data/ real.
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server_gui_server as gui
import gui_backend.services.history as history


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


@pytest.fixture
def hist_env(monkeypatch, tmp_path):
    # Por si un test anterior arranco el lifespan (history.start() cachea
    # _conn y registra sinks en el singleton manager): reset completo.
    history.stop_for_tests()
    gui.manager.log_sinks.clear()
    gui.manager.player_event_sinks.clear()
    db = os.path.join(str(tmp_path), "gui_history.db")
    monkeypatch.setattr(history, "DB_PATH", db)
    _reset_manager_state()
    gui.manager.log_history.clear()
    gui.manager._log_seq = 0
    yield history
    history.stop_for_tests()
    gui.manager.log_sinks.clear()
    gui.manager.player_event_sinks.clear()


@pytest.fixture
def isolated_sinks():
    """Sinks del manager aislados (sin DB): para los tests de mecanica pura."""
    saved_log = list(gui.manager.log_sinks)
    saved_pe = list(gui.manager.player_event_sinks)
    gui.manager.log_sinks.clear()
    gui.manager.player_event_sinks.clear()
    yield
    gui.manager.log_sinks.clear()
    gui.manager.log_sinks.extend(saved_log)
    gui.manager.player_event_sinks.clear()
    gui.manager.player_event_sinks.extend(saved_pe)


# ═══════════════════════════════════════════════════════════════════════
# Sinks del manager
# ═══════════════════════════════════════════════════════════════════════
def test_add_log_invoca_sinks_y_aguanta_errores(isolated_sinks):
    seen = []

    def good(entry):
        seen.append(entry["text"])

    def boom(entry):
        raise RuntimeError("sink roto")

    gui.manager.log_sinks.extend([boom, good])
    gui.manager.add_log("hola", "info")
    assert seen == ["hola"]  # el sink roto no corto la cadena


def test_player_event_sink_invocado(isolated_sinks):
    seen = []
    sink = lambda n, x, on: seen.append((n, x, on))
    gui.manager.player_event_sinks.append(sink)
    sink("Alice", "111", True)
    assert seen == [("Alice", "111", True)]


# ═══════════════════════════════════════════════════════════════════════
# Servicio: metricas
# ═══════════════════════════════════════════════════════════════════════
def test_metrics_record_y_query(hist_env):
    # El escritor real (smoke): una muestra via record_metrics
    hist_env.record_metrics(
        {"ram_mb": 500.0, "ram_pct": 25.0, "cpu_pct": 5.0,
         "disk_used_pct": 50.0, "system_used_pct": 60.0},
        running=True,
    )
    # Serie historica con ts explicitos (el PK es ts en segundos: dos muestras
    # del mismo segundo se reemplazan, igual que en produccion con 30s de paso)
    base = time.time() - 600
    conn = hist_env._connect()
    with hist_env._lock, conn:
        for i in range(5):
            conn.execute(
                "INSERT OR REPLACE INTO metrics VALUES (?, ?, ?, ?, ?, ?, ?)",
                (int(base + i * 60), 100.0 + i, 10.0 + i, 5.0, 50.0, 60.0, 1 if i % 2 == 0 else 0),
            )
    points = hist_env.query_metrics(1)
    assert len(points) == 6  # 5 historicas + la muestra del escritor
    assert points[0]["ram_mb"] == pytest.approx(100.0)
    assert points[1]["running"] is False  # i=1
    assert points[2]["running"] is True   # i=2
    # la muestra del escritor tambien esta (ts actual, dentro de la hora)
    assert any(p["ram_mb"] == pytest.approx(500.0) for p in points)


def test_metrics_downsample_limite(hist_env, monkeypatch):
    # Muchos puntos: el bucket promedia y nunca supera MAX_METRICS_POINTS
    base = time.time() - 7200
    conn = hist_env._connect()
    with hist_env._lock, conn:
        for i in range(1000):
            conn.execute(
                "INSERT OR REPLACE INTO metrics VALUES (?, ?, ?, ?, ?, ?, ?)",
                (int(base + i * 4), 100.0 + i, 10.0, 5.0, 50.0, 60.0, 1),
            )
    monkeypatch.setattr(hist_env, "MAX_METRICS_POINTS", 300)
    points = hist_env.query_metrics(24)
    assert 0 < len(points) <= 300
    assert points[0]["ram_mb"] < points[-1]["ram_mb"]  # promedio ascendente


def test_metrics_query_respecta_rango(hist_env):
    base = time.time()
    conn = hist_env._connect()
    with hist_env._lock, conn:
        conn.execute("INSERT INTO metrics VALUES (?, 1, 1, 1, 1, 1, 0)", (int(base - 10 * 86400),))
        conn.execute("INSERT INTO metrics VALUES (?, 2, 2, 2, 2, 2, 1)", (int(base - 60),))
    points = hist_env.query_metrics(1)
    assert len(points) == 1 and points[0]["ram_mb"] == pytest.approx(2.0)


# ═══════════════════════════════════════════════════════════════════════
# Servicio: logs y precarga
# ═══════════════════════════════════════════════════════════════════════
def test_logs_roundtrip_y_orden_cronologico(hist_env):
    hist_env._persist_log({"id": 1, "time": "10:00:01", "type": "info", "text": "uno"})
    time.sleep(0.01)
    hist_env._persist_log({"id": 2, "time": "10:00:02", "type": "error", "text": "dos"})
    logs = hist_env.query_logs(10)
    assert [l["text"] for l in logs] == ["uno", "dos"]  # viejo primero
    assert logs[1]["type"] == "error"


def test_start_precarga_log_history(hist_env):
    for i in range(hist_env.LOG_PRELOAD + 50):
        hist_env._persist_log({"id": i, "time": "10:00:00", "type": "info", "text": f"linea {i}"})
    assert gui.manager.log_history == []
    hist_env.start()
    # LOG_PRELOAD logs de la sesion anterior + 1 separador de sesion al final
    assert len(gui.manager.log_history) == hist_env.LOG_PRELOAD + 1
    separador = gui.manager.log_history[-1]
    assert separador["type"] == "session_start"
    assert separador["text"] == ""
    # el separador vive solo en memoria: no se persiste ni reaparece luego
    assert all(l["type"] != "session_start" for l in hist_env.query_logs(500))
    ids = [e["id"] for e in gui.manager.log_history]
    assert ids == sorted(ids) and ids[0] == 1
    # ids continuos para add_log posteriores (sin colision de React keys)
    gui.manager.add_log("nuevo", "info")
    assert gui.manager.log_history[-1]["id"] == ids[-1] + 1
    assert gui.manager.log_history[-1]["text"] == "nuevo"


def test_start_registra_sinks_una_vez(hist_env):
    hist_env.start()
    hist_env.start()
    assert gui.manager.log_sinks.count(hist_env._persist_log) == 1
    assert gui.manager.player_event_sinks.count(hist_env._persist_session_event) == 1


# ═══════════════════════════════════════════════════════════════════════
# Servicio: sesiones
# ═══════════════════════════════════════════════════════════════════════
def test_sesion_abre_cierra_y_agrega(hist_env):
    hist_env._persist_session_event("Alice", "111", True)
    time.sleep(0.01)
    hist_env._persist_session_event("Alice", "111", False)
    hist_env._persist_session_event("Bob", "222", True)
    data = hist_env.query_sessions(7)
    by_player = {s["player"]: s for s in data["sessions"]}
    assert by_player["Alice"]["ended_ts"] is not None
    assert by_player["Alice"]["duration_sec"] >= 0
    assert by_player["Bob"]["ended_ts"] is None  # sigue online
    totals = {t["player"]: t for t in data["totals"]}
    assert totals["Alice"]["sessions"] == 1
    assert totals["Alice"]["total_sec"] >= 0
    assert totals["Bob"]["sessions"] == 1


def test_doble_connect_no_duplica_sesion(hist_env):
    hist_env._persist_session_event("Alice", "111", True)
    hist_env._persist_session_event("Alice", "111", True)  # reconexion
    data = hist_env.query_sessions(7)
    assert len([s for s in data["sessions"] if s["player"] == "Alice"]) == 1


def test_start_cierra_sesiones_huerfanas(hist_env):
    hist_env._persist_session_event("Alice", "111", True)
    hist_env.start()
    data = hist_env.query_sessions(7)
    alice = [s for s in data["sessions"] if s["player"] == "Alice"][0]
    assert alice["ended_ts"] is not None


# ═══════════════════════════════════════════════════════════════════════
# Retención
# ═══════════════════════════════════════════════════════════════════════
def test_sweep_respeta_retenciones(hist_env):
    now = time.time()
    conn = hist_env._connect()
    with hist_env._lock, conn:
        conn.execute("INSERT INTO metrics VALUES (?, 1, 1, 1, 1, 1, 0)", (int(now - 8 * 86400),))
        conn.execute("INSERT INTO metrics VALUES (?, 2, 2, 2, 2, 2, 1)", (int(now - 3600),))
        conn.execute("INSERT INTO logs (ts, time_text, type, text) VALUES (?, 'x', 'info', 'viejo')", (int(now - 8 * 86400),))
        conn.execute("INSERT INTO logs (ts, time_text, type, text) VALUES (?, 'x', 'info', 'nuevo')", (int(now - 3600),))
        conn.execute("INSERT INTO sessions (player, xuid, started_ts) VALUES ('Viejo', '9', ?)", (int(now - 91 * 86400),))
        conn.execute("INSERT INTO sessions (player, xuid, started_ts) VALUES ('Nuevo', '8', ?)", (int(now - 3600),))
    hist_env.sweep(now=now)
    assert len(hist_env.query_metrics(24)) == 1
    assert [l["text"] for l in hist_env.query_logs(10)] == ["nuevo"]
    players = [s["player"] for s in hist_env.query_sessions(90)["sessions"]]
    assert "Viejo" not in players and "Nuevo" in players


# ═══════════════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════════════
def test_history_endpoints_validacion(hist_env):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    _reset_manager_state()
    client = TestClient(gui.app, client=("127.0.0.1", 50000))
    assert client.get("/api/history/metrics?hours=24").status_code == 200
    assert client.get("/api/history/metrics?hours=5").status_code == 400
    assert client.get("/api/history/logs?limit=10").json()["logs"] == []
    assert client.get("/api/history/logs?limit=0").status_code == 400
    assert client.get("/api/history/sessions?days=7").json()["sessions"] == []
    assert client.get("/api/history/sessions?days=0").status_code == 400


def test_history_endpoints_datos(hist_env):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    _reset_manager_state()
    hist_env.record_metrics({"ram_mb": 500.0, "ram_pct": 25.0, "cpu_pct": 5.0,
                             "disk_used_pct": 50.0, "system_used_pct": 60.0}, running=True)
    hist_env._persist_log({"id": 1, "time": "10:00:00", "type": "info", "text": "hola"})
    hist_env._persist_session_event("Alice", "111", True)

    client = TestClient(gui.app, client=("127.0.0.1", 50000))
    points = client.get("/api/history/metrics?hours=1").json()["points"]
    assert points and points[0]["ram_mb"] == pytest.approx(500.0)
    logs = client.get("/api/history/logs?limit=5").json()["logs"]
    assert logs[0]["text"] == "hola"
    sessions = client.get("/api/history/sessions?days=1").json()
    assert sessions["sessions"][0]["player"] == "Alice"
