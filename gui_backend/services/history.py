"""Historial persistente en SQLite (data/gui_history.db): metricas, logs y sesiones.

Los escritores se enganchan por registro (manager.log_sinks /
manager.player_event_sinks) en start(): este modulo esta ARRIBA de state y
supervisor en la cadena de dependencias y no pueden importarlo hacia atras.
Todo falla a historial-vacio ante sqlite3.Error: la GUI nunca se rompe por
la persistencia.
"""

import os
import sqlite3
import threading
import time

from gui_backend import config
from gui_backend.state import manager

DB_PATH = os.path.join(config.BASE_DIR, "data", "gui_history.db")

METRICS_RETENTION_DAYS = 7
LOGS_RETENTION_DAYS = 7
SESSIONS_RETENTION_DAYS = 90
LOG_PRELOAD = 200          # logs recargados en log_history al arrancar la GUI
MAX_METRICS_POINTS = 300   # tope de puntos por consulta (downsample)

_lock = threading.Lock()
_conn = None
_started = False
_last_sweep_day = None


def _connect():
    global _conn
    if _conn is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute(
            "CREATE TABLE IF NOT EXISTS metrics ("
            " ts INTEGER PRIMARY KEY,"
            " ram_mb REAL, ram_pct REAL, cpu_pct REAL,"
            " disk_used_pct REAL, sys_used_pct REAL, running INTEGER)"
        )
        _conn.execute(
            "CREATE TABLE IF NOT EXISTS logs ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " ts INTEGER, time_text TEXT, type TEXT, text TEXT)"
        )
        _conn.execute(
            "CREATE TABLE IF NOT EXISTS sessions ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " player TEXT, xuid TEXT,"
            " started_ts INTEGER, ended_ts INTEGER, duration_sec INTEGER)"
        )
        _conn.commit()
    return _conn


def start():
    """Crea tablas, cierra sesiones huerfanas, precarga log_history y registra
    los sinks. Idempotente; llamado desde el lifespan de la GUI."""
    global _started
    if _started:
        return
    _started = True
    try:
        conn = _connect()
        with _lock, conn:
            # La GUI al morir mata wrapper+BDS (Job Object): toda sesion abierta
            # al arrancar es huerfana; se cierra con la hora actual como aprox.
            conn.execute(
                "UPDATE sessions SET ended_ts = ?, duration_sec = ? - started_ts "
                "WHERE ended_ts IS NULL",
                (int(time.time()), int(time.time())),
            )
        _preload_log_history()
        if _persist_log not in manager.log_sinks:
            manager.log_sinks.append(_persist_log)
        if _persist_session_event not in manager.player_event_sinks:
            manager.player_event_sinks.append(_persist_session_event)
    except sqlite3.Error:
        pass


def stop_for_tests():
    """Cierra la conexion y des-registra sinks (solo tests)."""
    global _conn, _started
    with _lock:
        if _conn is not None:
            try:
                _conn.close()
            except sqlite3.Error:
                pass
            _conn = None
    try:
        manager.log_sinks.remove(_persist_log)
    except ValueError:
        pass
    try:
        manager.player_event_sinks.remove(_persist_session_event)
    except ValueError:
        pass
    _started = False


# ── escritores ───────────────────────────────────────────────────────────
def record_metrics(hw, running):
    try:
        conn = _connect()
        with _lock, conn:
            conn.execute(
                "INSERT OR REPLACE INTO metrics "
                "(ts, ram_mb, ram_pct, cpu_pct, disk_used_pct, sys_used_pct, running) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    int(time.time()),
                    hw.get("ram_mb"), hw.get("ram_pct"), hw.get("cpu_pct"),
                    hw.get("disk_used_pct"), hw.get("system_used_pct"),
                    1 if running else 0,
                ),
            )
    except sqlite3.Error:
        pass


def _persist_log(entry):
    """Sink de manager.log_sinks: entry = {id, time, text, type}."""
    try:
        conn = _connect()
        with _lock, conn:
            conn.execute(
                "INSERT INTO logs (ts, time_text, type, text) VALUES (?, ?, ?, ?)",
                (int(time.time()), entry.get("time", ""), entry.get("type", "info"),
                 entry.get("text", "")),
            )
    except sqlite3.Error:
        pass


def _persist_session_event(name, xuid, online):
    """Sink de manager.player_event_sinks."""
    try:
        conn = _connect()
        now = int(time.time())
        with _lock, conn:
            if online:
                # Doble connect sin disconnect (reconexion rapida): reutiliza
                # la sesion abierta en vez de duplicarla.
                open_row = conn.execute(
                    "SELECT id FROM sessions WHERE player = ? AND ended_ts IS NULL",
                    (name,),
                ).fetchone()
                if open_row:
                    conn.execute(
                        "UPDATE sessions SET started_ts = ?, xuid = ? WHERE id = ?",
                        (now, xuid, open_row[0]),
                    )
                else:
                    conn.execute(
                        "INSERT INTO sessions (player, xuid, started_ts) VALUES (?, ?, ?)",
                        (name, xuid, now),
                    )
            else:
                conn.execute(
                    "UPDATE sessions SET ended_ts = ?, duration_sec = ? - started_ts "
                    "WHERE player = ? AND ended_ts IS NULL",
                    (now, now, name),
                )
    except sqlite3.Error:
        pass


def sweep(now=None):
    """Barrido de retencion (llamado 1 vez/dia desde el sampler)."""
    now = time.time() if now is None else now
    try:
        conn = _connect()
        with _lock, conn:
            conn.execute(
                "DELETE FROM metrics WHERE ts < ?",
                (int(now - METRICS_RETENTION_DAYS * 86400),),
            )
            conn.execute(
                "DELETE FROM logs WHERE ts < ?",
                (int(now - LOGS_RETENTION_DAYS * 86400),),
            )
            conn.execute(
                "DELETE FROM sessions WHERE started_ts < ?",
                (int(now - SESSIONS_RETENTION_DAYS * 86400),),
            )
    except sqlite3.Error:
        pass


def maybe_sweep():
    """Ejecuta sweep() como maximo una vez por dia civil."""
    global _last_sweep_day
    today = time.strftime("%Y-%m-%d")
    if _last_sweep_day == today:
        return
    _last_sweep_day = today
    sweep()


# ── lectores ─────────────────────────────────────────────────────────────
def query_metrics(hours):
    """Serie de las ultimas `hours` horas, downsampleada a <= MAX_METRICS_POINTS."""
    since = int(time.time() - hours * 3600)
    try:
        conn = _connect()
        with _lock:
            rows = conn.execute(
                "SELECT ts, ram_mb, ram_pct, cpu_pct, disk_used_pct, sys_used_pct, running "
                "FROM metrics WHERE ts >= ? ORDER BY ts",
                (since,),
            ).fetchall()
    except sqlite3.Error:
        return []
    if len(rows) <= MAX_METRICS_POINTS:
        return [
            {"ts": r[0], "ram_mb": r[1], "ram_pct": r[2], "cpu_pct": r[3],
             "disk_used_pct": r[4], "sys_used_pct": r[5], "running": bool(r[6])}
            for r in rows
        ]
    bucket = (len(rows) + MAX_METRICS_POINTS - 1) // MAX_METRICS_POINTS
    out = []
    for i in range(0, len(rows), bucket):
        chunk = rows[i:i + bucket]
        n = len(chunk)
        out.append({
            "ts": chunk[-1][0],
            "ram_mb": sum(r[1] or 0 for r in chunk) / n,
            "ram_pct": sum(r[2] or 0 for r in chunk) / n,
            "cpu_pct": sum(r[3] or 0 for r in chunk) / n,
            "disk_used_pct": sum(r[4] or 0 for r in chunk) / n,
            "sys_used_pct": sum(r[5] or 0 for r in chunk) / n,
            "running": any(r[6] for r in chunk),
        })
    return out


def query_logs(limit):
    """Ultimos `limit` logs, en orden cronologico (mas viejo primero)."""
    try:
        conn = _connect()
        with _lock:
            rows = conn.execute(
                "SELECT ts, time_text, type, text FROM logs "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    except sqlite3.Error:
        return []
    rows.reverse()
    return [
        {"ts": r[0], "time": r[1], "type": r[2], "text": r[3]}
        for r in rows
    ]


def query_sessions(days):
    """Sesiones de los ultimos `days` dias + tiempo total por jugador."""
    since = int(time.time() - days * 86400)
    try:
        conn = _connect()
        with _lock:
            rows = conn.execute(
                "SELECT player, xuid, started_ts, ended_ts, duration_sec "
                "FROM sessions WHERE started_ts >= ? ORDER BY started_ts DESC",
                (since,),
            ).fetchall()
            totals = conn.execute(
                "SELECT player, SUM(COALESCE(duration_sec, 0)), COUNT(*) "
                "FROM sessions WHERE started_ts >= ? GROUP BY player "
                "ORDER BY 2 DESC",
                (since,),
            ).fetchall()
    except sqlite3.Error:
        return {"sessions": [], "totals": []}
    return {
        "sessions": [
            {"player": r[0], "xuid": r[1] or "", "started_ts": r[2],
             "ended_ts": r[3], "duration_sec": r[4]}
            for r in rows
        ],
        "totals": [
            {"player": t[0], "total_sec": t[1] or 0, "sessions": t[2]}
            for t in totals
        ],
    }


def _preload_log_history():
    """Repuebla manager.log_history con los ultimos logs tras un reinicio.

    Bajo manager.lock y continuando _log_seq: los ids siguen siendo unicos y
    crecientes, y el init del WebSocket ya entrega historial sin cambios.
    """
    rows = query_logs(LOG_PRELOAD)
    with manager.lock:
        if manager.log_history:
            return  # ya hay logs en memoria (p. ej. lifespan re-cargado)
        for r in rows:
            manager._log_seq += 1
            manager.log_history.append({
                "id": manager._log_seq,
                "time": r["time"],
                "text": r["text"],
                "type": r["type"],
            })
        if rows:
            # Separador de sesion: marca el corte entre el historial recargado
            # y los logs en vivo de esta sesion. Se anade directo a log_history
            # (sin pasar por add_log) para que no dispare los sinks ni se
            # persista en SQLite: en el siguiente arranque no debe reaparecer.
            manager._log_seq += 1
            manager.log_history.append({
                "id": manager._log_seq,
                "time": "",
                "type": "session_start",
                "text": "",
            })
