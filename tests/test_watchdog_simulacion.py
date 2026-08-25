# -*- coding: utf-8 -*-
"""Watchdog de la GUI con BDS simulado: ciclo de crash completo sin binario.

Estos tests NO necesitan bedrock_server.exe: el 'wrapper' es un Popen falso
cuyo stdout muere al instante (EOF = crash), pero pasa por la ruta REAL de
arranque (lifecycle.start_wrapper -> _spawn_wrapper_process con subprocess.Popen
parcheado + hilo lector real run_wrapper_thread). Así se verifica la coreografía
completa crash -> deteccion -> re-arranque -> backoff -> stop deliberado.

El resto de sustituciones sigue las convenciones de test_schedule_watchdog.py
(rutas de config/estado a tmp via monkeypatch; reloj inyectado en el tick).
"""
import io
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server_gui_server as gui
import gui_backend.config as config
import gui_backend.services.lifecycle as lifecycle
import gui_backend.services.watchdog as watchdog
import gui_backend.services.schedule_config as schedule_config
import gui_backend.supervisor as supervisor

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _reset_manager_state():
    gui.manager.is_running = False
    gui.manager.start_time = None
    gui.manager.wrapper_process = None
    gui.manager.update_in_progress = False
    gui.manager.backup_in_progress = False
    gui.manager.players_online.clear()
    gui.manager.wrapper_exit_event.set()
    gui.manager.server_stopped_event.set()


def _patch_paths(monkeypatch, tmp_path):
    cfg_path = os.path.join(str(tmp_path), "schedule_config.json")
    state_path = os.path.join(str(tmp_path), "schedule_state_gui.json")
    monkeypatch.setattr(schedule_config, "SCHEDULE_PATH", cfg_path)
    monkeypatch.setattr(watchdog, "STATE_PATH", state_path)
    return cfg_path, state_path


def _write_config(cfg_path, **overrides):
    import json
    cfg = dict(schedule_config.DEFAULTS)
    cfg.update(overrides)
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f)


def _reset_watchdog(monkeypatch, tmp_path):
    cfg_path, state_path = _patch_paths(monkeypatch, tmp_path)
    watchdog._reset_state_for_tests()
    _reset_manager_state()
    monkeypatch.setattr(config, "WATCHDOG_BACKOFF_SCHEDULE", (10,))
    monkeypatch.setattr(config, "WATCHDOG_STABLE_UPTIME_SEC", 60)
    return cfg_path, state_path


class _FakeStdin:
    def __init__(self):
        self.lines = []

    def write(self, s):
        self.lines.append(s)

    def flush(self):
        pass


class _CrashingProc:
    """'Wrapper simulado': stdout en EOF inmediato (el hilo lector termina al
    instante) y exit code 1. Sustituye a server_wrapper.py+BDS sin binario."""

    def __init__(self):
        self.stdin = _FakeStdin()
        self.stdout = io.StringIO("")
        self.returncode = None

    def wait(self):
        self.returncode = 1
        return 1

    def poll(self):
        return self.returncode


def _fake_popen_factory(spawned):
    def fake_popen(*args, **kwargs):
        proc = _CrashingProc()
        spawned.append(proc)
        return proc
    return fake_popen


def _esperar_sin_wrapper(timeout=5.0):
    """Espera a que el hilo lector real cierre la sesion del wrapper simulado."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not gui.manager.is_running and gui.manager.wrapper_exit_event.is_set():
            return True
        time.sleep(0.01)
    return False


# ═══════════════════════════════════════════════════════════════════════
# Ciclo completo de crash con la ruta REAL de arranque (BDS simulado)
# ═══════════════════════════════════════════════════════════════════════
def test_watchdog_ciclo_crash_completo_sin_binario(monkeypatch, tmp_path):
    """Simulacion integral sin bedrock_server.exe: el wrapper 'crashea' solo,
    el watchdog lo detecta y re-arranca por la ruta real de la GUI, respeta el
    backoff entre intentos y respeta el stop deliberado."""
    cfg_path, _ = _reset_watchdog(monkeypatch, tmp_path)
    _write_config(cfg_path, auto_restart_on_crash=True)

    spawned = []
    monkeypatch.setattr(supervisor.subprocess, "Popen", _fake_popen_factory(spawned))
    from gui_backend.services import external_probe
    monkeypatch.setattr(external_probe, "detect_external_bds", lambda: (False, ""))

    gui.manager.stop_requested = False  # estado de "crash evidente"
    t0 = 1_000_000.0

    # Tick 1: wrapper muerto + nadie pidio pararlo -> relanza por la ruta real.
    watchdog._watchdog_tick(now=t0)
    assert len(spawned) == 1
    assert watchdog.crash_restarts == 1
    # El watchdog jamas escribe en el stdin del wrapper que lanza.
    assert spawned[0].stdin.lines == []

    # El wrapper simulado muere solo: el hilo lector REAL cierra la sesion.
    assert _esperar_sin_wrapper(), "la sesión del wrapper simulado no se cerró"
    assert gui.manager.stop_requested is False  # su salida fue un crash

    # Tick dentro del backoff (10 s en el config parcheado): no reintenta aun.
    watchdog._watchdog_tick(now=t0 + 5)
    assert len(spawned) == 1

    # Tick fuera del backoff: segundo arranque (crash_restarts escala).
    watchdog._watchdog_tick(now=t0 + 11)
    assert len(spawned) == 2
    assert watchdog.crash_restarts == 2
    assert spawned[1].stdin.lines == []
    assert _esperar_sin_wrapper()

    # Stop deliberado desde la GUI: la ausencia del wrapper ya NO es un crash.
    gui.manager.stop_requested = True
    watchdog._watchdog_tick(now=t0 + 1000)
    assert len(spawned) == 2  # ningun re-arranque extra
    assert watchdog.crash_restarts == 2


def test_watchdog_excepcion_en_start_cuenta_como_fallo_con_backoff(monkeypatch, tmp_path):
    """Si start_wrapper lanza (p. ej. la sonda de instancias falla), el intento
    cuenta para el backoff: sin esto el watchdog martillaba start cada 5 s y
    nadie veia el motivo en el historial."""
    cfg_path, _ = _reset_watchdog(monkeypatch, tmp_path)
    _write_config(cfg_path, auto_restart_on_crash=True)

    calls = {"n": 0}

    def exploding_start():
        calls["n"] += 1
        raise RuntimeError("sonda explotó")

    monkeypatch.setattr(lifecycle, "start_wrapper", exploding_start)
    logs = []
    monkeypatch.setattr(gui.manager, "add_log", lambda *a, **k: logs.append(a[0]))

    gui.manager.stop_requested = False
    t0 = 1_000_000.0
    watchdog._watchdog_tick(now=t0)
    assert calls["n"] == 1
    assert watchdog.crash_restarts == 1
    # Asercion neutra al idioma (L() devuelve EN sin WRAPPER_LANG): el prefijo
    # del watchdog y el texto de la excepcion aparecen en ambas traducciones.
    assert any("[Watchdog]" in str(x) and "sonda explotó" in str(x) for x in logs)

    # Backoff: el reintento inmediato no vuelve a llamar a start_wrapper...
    watchdog._watchdog_tick(now=t0 + 5)
    assert calls["n"] == 1
    # ...y el segundo intento llega tras el backoff, con log rate-limitado aparte.
    watchdog._watchdog_tick(now=t0 + 11)
    assert calls["n"] == 2
    assert watchdog.crash_restarts == 2


# ═══════════════════════════════════════════════════════════════════════
# Aislamiento de ramas del tick + rate-limit del log de errores internos
# ═══════════════════════════════════════════════════════════════════════
def test_watchdog_ramas_del_tick_aisladas(monkeypatch, tmp_path):
    """Un excepcion en una rama del tick no salta las demas: el backup diario
    en frio sigue disparandose aunque la rama de crash-restart reviente."""
    cfg_path, _ = _reset_watchdog(monkeypatch, tmp_path)
    _write_config(cfg_path, auto_restart_on_crash=True, daily_backup_time="04:00")

    def exploding_branch(now):
        raise RuntimeError("rama explotó")

    monkeypatch.setattr(watchdog, "_tick_crash_restart", exploding_branch)
    colds = []
    monkeypatch.setattr(lifecycle, "cold_backup", lambda trigger: colds.append(trigger))
    logs = []
    monkeypatch.setattr(gui.manager, "add_log", lambda *a, **k: logs.append(a[0]))

    gui.manager.is_running = False
    t_0430 = time.mktime((2026, 8, 16, 4, 30, 0, 0, 0, -1))
    watchdog._watchdog_tick(now=t_0430)

    # La rama siguiente a la que fallo SI corrio...
    assert colds == ["scheduled"]
    # ...y el fallo quedo visible en el historial (antes se tragaba en silencio).
    # Asercion neutra al idioma: el nombre de la rama viaja en ES y EN.
    errores = [x for x in logs if "auto_restart_on_crash" in str(x)]
    assert len(errores) == 1


def test_watchdog_log_de_errores_rate_limitado(monkeypatch):
    """Maximo 1 mensaje de error interno cada 60 s: un fallo persistente no
    inunda el historial de la GUI."""
    _reset_manager_state()
    watchdog._reset_state_for_tests()
    logs = []
    monkeypatch.setattr(gui.manager, "add_log", lambda *a, **k: logs.append(a[0]))

    t_base = 1_000_000.0
    watchdog._log_watchdog_error("rama_x", RuntimeError("e1"), t_base)
    watchdog._log_watchdog_error("rama_x", RuntimeError("e2"), t_base + 30)
    assert len(logs) == 1  # dentro de la ventana: suprimido

    watchdog._log_watchdog_error("rama_y", RuntimeError("e3"), t_base + 61)
    assert len(logs) == 2   # pasada la ventana: visible otra vez
    assert "rama_y" in logs[1]
