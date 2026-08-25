# -*- coding: utf-8 -*-
"""Backups programables + watchdog: config, helpers puros del wrapper y ciclo.

Solo se sustituyen E/S (rutas de config/estado via monkeypatch, arranque del
wrapper, reloj). Los tests de fuentes (watchdog sin stdin) siguen el estilo
de inspeccion de test_review_hallazgos.py.
"""
import json
import os
import re
import sys
import tempfile
import time

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server_wrapper as sw
import wrapper_schedule
import server_gui_server as gui
import gui_backend.config as config
import gui_backend.supervisor as supervisor
import gui_backend.services.lifecycle as lifecycle
import gui_backend.services.watchdog as watchdog
import gui_backend.services.schedule_config as schedule_config

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
    """Config y estado del watchdog aislados en tmp (nunca el data/ real)."""
    cfg_path = os.path.join(str(tmp_path), "schedule_config.json")
    state_path = os.path.join(str(tmp_path), "schedule_state_gui.json")
    monkeypatch.setattr(schedule_config, "SCHEDULE_PATH", cfg_path)
    monkeypatch.setattr(watchdog, "STATE_PATH", state_path)
    return cfg_path, state_path


def _write_config(cfg_path, **overrides):
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


# ═══════════════════════════════════════════════════════════════════════
# schedule_config: defaults, validacion, persistencia
# ═══════════════════════════════════════════════════════════════════════
def test_schedule_defaults_sin_archivo(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    cfg = schedule_config.load()
    assert cfg == schedule_config.DEFAULTS


def test_schedule_load_corrupto_caen_defaults(monkeypatch, tmp_path):
    cfg_path, _ = _patch_paths(monkeypatch, tmp_path)
    with open(cfg_path, "w", encoding="utf-8") as f:
        f.write("{no json")
    assert schedule_config.load() == schedule_config.DEFAULTS


def test_schedule_save_y_load_roundtrip(monkeypatch, tmp_path):
    cfg_path, _ = _patch_paths(monkeypatch, tmp_path)
    ok, cfg, detalle = schedule_config.save({
        "backup_interval_min": 120,
        "daily_backup_time": "04:00",
        "auto_restart_on_crash": True,
    })
    assert ok, detalle
    assert cfg["backup_interval_min"] == 120
    assert cfg["backup_only_with_players"] is True  # clave no enviada -> default
    assert schedule_config.load() == cfg
    # atomico: sin .tmp remanentes
    assert not [p for p in os.listdir(str(tmp_path)) if ".tmp_" in p]


@pytest.mark.parametrize("payload, fragmen_error", [
    ({"backup_interval_min": 4}, "entre 5"),
    ({"backup_interval_min": 20000}, "entre 5"),
    ({"backup_interval_min": "x"}, "entero"),
    ({"backup_only_with_players": "si"}, "true o false"),
    ({"auto_restart_on_crash": 1}, "true o false"),
    ({"daily_backup_time": "4:00"}, "HH:MM"),
    ({"daily_backup_time": "25:00"}, "HH:MM"),
    ({"daily_restart_time": "07:60"}, "HH:MM"),
])
def test_schedule_validacion_rechaza(payload, fragmen_error, monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    ok, cfg, detalle = schedule_config.save(payload)
    assert not ok and cfg is None
    assert fragmen_error in detalle
    # nada escrito tras un rechazo
    assert not os.path.exists(schedule_config.SCHEDULE_PATH)


def test_defaults_wrapper_y_gui_coinciden():
    """Anti-drift: el wrapper lee el archivo con sus propios defaults; si
    divergen de los de la GUI, un mismo archivo significa cosas distintas
    segun quien lo lea."""
    assert dict(sw.SCHEDULE_DEFAULTS) == dict(schedule_config.DEFAULTS)


def test_load_schedule_config_coerciona_tipos_invalidos(monkeypatch, tmp_path):
    """Regresion: una edicion manual con tipos invalidos no debe romper el
    tick del scheduler (string en backup_interval_min hacia lanzar TypeError
    en la comparacion del intervalo; daily_backup_time numerico, AttributeError
    en .split): en ambos casos el tick abortaba cada segundo y los backups
    programados dejaban de dispararse."""
    cfg_path = os.path.join(str(tmp_path), "schedule_config.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({
            "backup_interval_min": "45",            # numerica como string: coercer
            "backup_only_with_players": "false",    # bool como string: coercer
            "auto_restart_on_crash": "true",        # bool como string: coercer
            "daily_backup_time": 5,                 # tipo invalido: default (None)
            "daily_restart_time": "25:99",          # hora invalida: default (None)
        }, f)
    monkeypatch.setattr(wrapper_schedule, "SCHEDULE_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(
        wrapper_schedule,
        "_schedule_cfg_cache",
        {"mtime": None, "cfg": dict(sw.SCHEDULE_DEFAULTS)},
    )
    cfg = sw._load_schedule_config()
    assert cfg["backup_interval_min"] == 45
    assert cfg["backup_only_with_players"] is False
    assert cfg["auto_restart_on_crash"] is True
    assert cfg["daily_backup_time"] is None
    assert cfg["daily_restart_time"] is None
    # el tick del scheduler ya no lanza con estos valores
    interval_due = (time.time() - 0) > (cfg["backup_interval_min"] * 60)
    assert interval_due is True
    assert sw._crossed_daily_time(time.localtime(), cfg["daily_backup_time"], None) is False


# ═══════════════════════════════════════════════════════════════════════
# Helpers puros del wrapper
# ═══════════════════════════════════════════════════════════════════════
def _cfg(**over):
    cfg = dict(sw.SCHEDULE_DEFAULTS)
    cfg.update(over)
    return cfg


@pytest.mark.parametrize("interval_due, retry_due, daily_due, players, only, expected", [
    (False, False, False, 3, True, "no"),        # nada vencido
    (True, False, False, 3, True, "start"),      # intervalo + jugadores
    (True, False, False, 0, True, "skip"),       # intervalo sin jugadores (historico)
    (False, True, False, 0, True, "skip"),       # reintento sin jugadores
    (True, False, False, 0, False, "start"),     # intervalo sin requisito de jugadores
    (False, False, True, 0, True, "start"),      # hora fija diaria: aunque no haya jugadores
    (False, False, True, 3, True, "start"),
])
def test_should_start_backup(interval_due, retry_due, daily_due, players, only, expected):
    cfg = _cfg(backup_only_with_players=only)
    assert sw._should_start_backup(interval_due, retry_due, daily_due, players, cfg) == expected


def _localtime(y, mo, d, h, mi):
    return time.localtime(time.mktime((y, mo, d, h, mi, 0, 0, 0, -1)))


def test_crossed_daily_time():
    lt_0430 = _localtime(2026, 8, 16, 4, 30)
    assert sw._crossed_daily_time(lt_0430, None, None) is False      # sin hora fijada
    assert sw._crossed_daily_time(lt_0430, "05:00", None) is False   # aun no llega
    assert sw._crossed_daily_time(lt_0430, "04:30", None) is True    # justo en la hora
    assert sw._crossed_daily_time(lt_0430, "04:00", None) is True    # ya paso
    assert sw._crossed_daily_time(lt_0430, "04:00", "2026-08-16") is False  # ya disparo hoy
    assert sw._crossed_daily_time(lt_0430, "04:00", "2026-08-15") is True   # ayer no cuenta
    assert sw._crossed_daily_time(lt_0430, "garbage", None) is False  # hhmm invalido


def test_crossed_daily_time_medianoche():
    # 00:10 con hora fijada 23:50: hoy todavia no llega (dispara a las 23:50)
    lt_0010 = _localtime(2026, 8, 16, 0, 10)
    assert sw._crossed_daily_time(lt_0010, "23:50", None) is False


# ═══════════════════════════════════════════════════════════════════════
# Endpoints /api/schedule
# ═══════════════════════════════════════════════════════════════════════
def test_schedule_endpoints_roundtrip(monkeypatch, tmp_path):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    _patch_paths(monkeypatch, tmp_path)
    _reset_manager_state()
    client = TestClient(gui.app, client=("127.0.0.1", 50000))

    r = client.get("/api/schedule")
    assert r.status_code == 200
    assert r.json() == schedule_config.DEFAULTS

    r = client.post("/api/schedule", json={"backup_interval_min": 120, "daily_backup_time": "04:00"})
    assert r.status_code == 200
    assert r.json()["config"]["backup_interval_min"] == 120

    r = client.get("/api/schedule")
    assert r.json()["daily_backup_time"] == "04:00"

    r = client.post("/api/schedule", json={"backup_interval_min": 1})
    assert r.status_code == 400


# ═══════════════════════════════════════════════════════════════════════
# Watchdog: ciclo
# ═══════════════════════════════════════════════════════════════════════
def _fake_start_counter(spawned, status="starting"):
    def fake():
        spawned["n"] += 1
        return status, ""
    return fake


def test_watchdog_sin_config_nunca_arranca(monkeypatch, tmp_path):
    _reset_watchdog(monkeypatch, tmp_path)
    spawned = {"n": 0}
    monkeypatch.setattr(lifecycle, "start_wrapper", _fake_start_counter(spawned))
    gui.manager.stop_requested = False  # "crash" evidente
    watchdog._watchdog_tick()
    assert spawned["n"] == 0


def test_watchdog_rearranca_tras_crash_con_backoff(monkeypatch, tmp_path):
    cfg_path, _ = _reset_watchdog(monkeypatch, tmp_path)
    _write_config(cfg_path, auto_restart_on_crash=True)
    spawned = {"n": 0}
    monkeypatch.setattr(lifecycle, "start_wrapper", _fake_start_counter(spawned))

    gui.manager.stop_requested = False
    t0 = 1_000_000.0
    watchdog._watchdog_tick(now=t0)
    assert spawned["n"] == 1

    # backoff (10s tras el config parcheado): ticks inmediatos no reintentan
    watchdog._watchdog_tick(now=t0 + 5)
    assert spawned["n"] == 1
    watchdog._watchdog_tick(now=t0 + 11)
    assert spawned["n"] == 2
    assert watchdog.crash_restarts == 2


def test_watchdog_no_rearranca_stop_deliberado(monkeypatch, tmp_path):
    cfg_path, _ = _reset_watchdog(monkeypatch, tmp_path)
    _write_config(cfg_path, auto_restart_on_crash=True)
    spawned = {"n": 0}
    monkeypatch.setattr(lifecycle, "start_wrapper", _fake_start_counter(spawned))

    gui.manager.stop_requested = True  # la GUI (o un 'stop' en consola) lo paro
    watchdog._watchdog_tick(now=1_000_000.0)
    assert spawned["n"] == 0


def test_watchdog_uptime_estable_resetea_backoff(monkeypatch, tmp_path):
    cfg_path, _ = _reset_watchdog(monkeypatch, tmp_path)
    _write_config(cfg_path, auto_restart_on_crash=True)
    spawned = {"n": 0}
    monkeypatch.setattr(lifecycle, "start_wrapper", _fake_start_counter(spawned))

    watchdog.crash_restarts = 3
    gui.manager.is_running = True
    gui.manager.start_time = time.time() - 3600  # 1h corriendo: estable
    watchdog._watchdog_tick()
    assert watchdog.crash_restarts == 0
    assert spawned["n"] == 0


def test_watchdog_reinicio_diario_dispara_una_vez(monkeypatch, tmp_path):
    cfg_path, state_path = _reset_watchdog(monkeypatch, tmp_path)
    _write_config(cfg_path, daily_restart_time="04:00")
    calls = {"restart": 0, "cold": 0}
    monkeypatch.setattr(lifecycle, "restart_wrapper", lambda: calls.__setitem__("restart", calls["restart"] + 1))
    monkeypatch.setattr(lifecycle, "cold_backup", lambda trigger: calls.__setitem__("cold", calls["cold"] + 1))

    gui.manager.is_running = True
    gui.manager.stop_requested = False
    t_0430 = time.mktime((2026, 8, 16, 4, 30, 0, 0, 0, -1))
    watchdog._watchdog_tick(now=t_0430)
    assert calls["restart"] == 1
    assert calls["cold"] == 0  # servidor corriendo: el backup diario lo hace el wrapper

    watchdog._watchdog_tick(now=t_0430 + 60)
    assert calls["restart"] == 1  # ya disparo hoy

    # persistido: un reinicio de la GUI no re-dispara
    watchdog._reset_state_for_tests()
    watchdog._load_gui_state()
    watchdog._watchdog_tick(now=t_0430 + 120)
    assert calls["restart"] == 1
    assert os.path.exists(state_path)


def test_watchdog_backup_diario_frio_servidor_apagado(monkeypatch, tmp_path):
    cfg_path, _ = _reset_watchdog(monkeypatch, tmp_path)
    _write_config(cfg_path, daily_backup_time="04:00")
    calls = {"cold": []}
    monkeypatch.setattr(lifecycle, "cold_backup", lambda trigger: calls["cold"].append(trigger))

    gui.manager.is_running = False
    gui.manager.stop_requested = True  # apagado a proposito: el cold backup SI corresponde
    t_0430 = time.mktime((2026, 8, 16, 4, 30, 0, 0, 0, -1))
    watchdog._watchdog_tick(now=t_0430)
    assert calls["cold"] == ["scheduled"]

    watchdog._watchdog_tick(now=t_0430 + 60)
    assert calls["cold"] == ["scheduled"]  # una vez por dia


# ═══════════════════════════════════════════════════════════════════════
# Flag stop_requested en los endpoints
# ═══════════════════════════════════════════════════════════════════════
class _FakeStdin:
    def __init__(self):
        self.lines = []

    def write(self, s):
        self.lines.append(s)

    def flush(self):
        pass


class _FakeStdout:
    def readline(self):
        return ""


class _FakeProc:
    def __init__(self):
        self.stdin = _FakeStdin()
        self.stdout = _FakeStdout()

    def wait(self):
        return 0

    def poll(self):
        return None


@pytest.mark.parametrize("via", ["action_stop", "command_stop"])
def test_stop_por_gui_marca_stop_requested(via, monkeypatch, tmp_path):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    _patch_paths(monkeypatch, tmp_path)
    _reset_manager_state()
    gui.manager.is_running = True
    gui.manager.wrapper_process = _FakeProc()
    gui.manager.stop_requested = False

    client = TestClient(gui.app, client=("127.0.0.1", 50000))
    if via == "action_stop":
        r = client.post("/api/action/stop")
        assert r.json()["status"] == "stopping"
    else:
        r = client.post("/api/command", json={"command": "stop  "})
        assert r.json()["status"] == "ok"
    assert gui.manager.stop_requested is True
    assert "stop\n" in gui.manager.wrapper_process.stdin.lines


def test_start_limpia_stop_requested(monkeypatch):
    """_spawn_wrapper_process (todas las rutas de arranque pasan por el) resetea
    el flag: la salida de un wrapper NUEVO solo es crash si nadie lo paro."""
    from gui_backend.services import external_probe

    fake_proc = _FakeProc()
    monkeypatch.setattr(external_probe, "detect_external_bds", lambda: (False, ""))
    # Popen parcheado (no _spawn_wrapper_process): el reset del flag vive DENTRO
    # de la funcion real y el test debe ejecutarla.
    monkeypatch.setattr(supervisor.subprocess, "Popen", lambda *a, **k: fake_proc)

    _reset_manager_state()
    gui.manager.stop_requested = True
    status, _ = lifecycle.start_wrapper()
    assert status == "starting"
    assert gui.manager.stop_requested is False
    assert gui.manager.is_running is True
    assert gui.manager.wrapper_process is fake_proc


# ═══════════════════════════════════════════════════════════════════════
# PBT: schedule_config interval 5-1440, HH:MM y watchdog backoff (P0-1)
# ═══════════════════════════════════════════════════════════════════════

_valid_hhmm = st.builds(lambda h, m: f"{h:02d}:{m:02d}", st.integers(0, 23), st.integers(0, 59))
_valid_interval = st.integers(min_value=5, max_value=1440)
_invalid_interval = st.one_of(st.integers(max_value=4), st.integers(min_value=1441, max_value=10000))


@given(_valid_interval)
@settings(max_examples=150, suppress_health_check=[HealthCheck.too_slow])
def test_pbt_interval_valido_aceptado(interval):
    cfg, detalle = schedule_config.validate({"backup_interval_min": interval})
    assert cfg is not None and detalle == ""
    assert cfg["backup_interval_min"] == interval
    # wrapper coercion coincide para valores validos (int y str numerico)
    assert wrapper_schedule._coerce_schedule_value("backup_interval_min", interval) == interval
    assert wrapper_schedule._coerce_schedule_value("backup_interval_min", str(interval)) == interval


@given(_invalid_interval)
@settings(max_examples=150, suppress_health_check=[HealthCheck.too_slow])
def test_pbt_interval_invalido_rechazado(interval):
    cfg, detalle = schedule_config.validate({"backup_interval_min": interval})
    assert cfg is None
    assert "entre 5" in detalle
    # wrapper cae a default para fuera de rango
    assert wrapper_schedule._coerce_schedule_value("backup_interval_min", interval) == schedule_config.DEFAULTS["backup_interval_min"]
    assert wrapper_schedule._coerce_schedule_value("backup_interval_min", str(interval)) == schedule_config.DEFAULTS["backup_interval_min"]


@given(st.one_of(st.booleans(), st.just(None), st.floats(allow_nan=False, allow_infinity=False), st.text(min_size=1, max_size=10)))
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_pbt_interval_tipos_no_enteros_rechazados(value):
    assume(not isinstance(value, int) or isinstance(value, bool))
    # bool debe ser rechazado por wrapper (default) y floats/texto tambien segun validacion
    if isinstance(value, bool) or value is None or isinstance(value, float):
        coerced = wrapper_schedule._coerce_schedule_value("backup_interval_min", value)
        # bool -> default, float con int() puede truncar pero fuera de rango bool ya cubierto
        if isinstance(value, bool):
            assert coerced == schedule_config.DEFAULTS["backup_interval_min"]
    # GUI validate solo acepta int en rango; texto no numerico debe fallar
    if isinstance(value, str) and not re.match(r"^-?\d+$", value.strip()):
        cfg, detalle = schedule_config.validate({"backup_interval_min": value})
        assert cfg is None and "entero" in detalle


@given(_valid_hhmm)
@settings(max_examples=150, suppress_health_check=[HealthCheck.too_slow])
def test_pbt_hhmm_valido_aceptado(hhmm):
    assert schedule_config.is_valid_time(hhmm) is not None
    assert re.match(r"^([01]\d|2[0-3]):[0-5]\d$", hhmm)
    cfg, detalle = schedule_config.validate({"daily_backup_time": hhmm, "daily_restart_time": hhmm})
    assert cfg is not None, detalle
    assert cfg["daily_backup_time"] == hhmm
    assert wrapper_schedule._coerce_schedule_value("daily_backup_time", hhmm) == hhmm
    # con espacios debe trimear wrapper pero GUI es estricta (sin trim)
    assert wrapper_schedule._coerce_schedule_value("daily_backup_time", f"  {hhmm}  ") == hhmm
    assert schedule_config.is_valid_time(f"  {hhmm}  ") is None or not schedule_config.is_valid_time(f"  {hhmm}  ")


@given(st.text(min_size=1, max_size=12))
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_pbt_hhmm_invalido_rechazado(txt):
    # Para wrapper el trim cuenta: solo es invalido si tras strip sigue sin matchear
    assume(not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", txt.strip()))
    # GUI es estricta sin trim
    assert not schedule_config.is_valid_time(txt.strip()) or not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", txt)
    # si txt tiene espacios extra, GUI lo rechaza aunque wrapper lo aceptaria tras strip;
    # por eso solo testeamos wrapper con strip y GUI con raw si no tiene espacios
    if txt == txt.strip():
        assert not schedule_config.is_valid_time(txt)
        cfg, detalle = schedule_config.validate({"daily_backup_time": txt})
        assert cfg is None and "HH:MM" in detalle
    # wrapper cae a None para cualquier invalido tras strip
    assert wrapper_schedule._coerce_schedule_value("daily_backup_time", txt) is None
    assert wrapper_schedule._coerce_schedule_value("daily_restart_time", txt) is None


def test_pbt_hhmm_casos_borde():
    # Bordes explicitos que Hypothesis podria no generar
    for ok in ["00:00", "23:59", "09:05", "12:30"]:
        assert schedule_config.is_valid_time(ok)
        assert wrapper_schedule._coerce_schedule_value("daily_backup_time", ok) == ok
    # wrapper es permisivo con trim, GUI no
    assert wrapper_schedule._coerce_schedule_value("daily_backup_time", "04:00 ") == "04:00"
    assert wrapper_schedule._coerce_schedule_value("daily_backup_time", " 04:00") == "04:00"
    assert not schedule_config.is_valid_time("04:00 ")
    assert not schedule_config.is_valid_time(" 04:00")
    for bad in ["24:00", "00:60", "4:00", "04:0", "99:99", "", "ab:cd", None, 123]:
        assert not schedule_config.is_valid_time(bad) if bad is not None else True
        if isinstance(bad, str):
            assert wrapper_schedule._coerce_schedule_value("daily_backup_time", bad) is None


@given(st.integers(min_value=0, max_value=20))
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_pbt_watchdog_backoff_monotono_y_acotado(failures):
    backoff = watchdog._backoff_sec(failures)
    schedule = config.WATCHDOG_BACKOFF_SCHEDULE
    if failures == 0:
        assert backoff == 0
    else:
        assert backoff in schedule
        assert 0 < backoff <= max(schedule)
        # monotono no decreciente
        if failures > 1:
            assert watchdog._backoff_sec(failures) >= watchdog._backoff_sec(failures - 1)
        # cap maximo
        if failures > len(schedule):
            assert backoff == schedule[-1]


def test_pbt_watchdog_schedule_constantes():
    schedule = config.WATCHDOG_BACKOFF_SCHEDULE
    assert isinstance(schedule, tuple) and len(schedule) == 4
    assert schedule == tuple(sorted(schedule))
    assert all(isinstance(v, int) and v > 0 for v in schedule)
    assert config.WATCHDOG_STABLE_UPTIME_SEC == 600
    assert config.WATCHDOG_POLL_SEC == 5


def test_pbt_defaults_anti_drift_extendido():
    # DEFAULTS iguales (ya existe test basico) + intervalo bounds
    assert dict(wrapper_schedule.SCHEDULE_DEFAULTS) == dict(schedule_config.DEFAULTS)
    assert wrapper_schedule.MIN_INTERVAL_MIN == schedule_config.MIN_INTERVAL_MIN
    assert wrapper_schedule.MAX_INTERVAL_MIN == schedule_config.MAX_INTERVAL_MIN
    # watchdog schedule no deriva entre wrapper y GUI (wrapper no tiene duplicado)
    assert config.WATCHDOG_BACKOFF_SCHEDULE == (30, 60, 120, 300)


@given(st.text(max_size=20), st.text(max_size=20))
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_pbt_crossed_daily_never_crash(hhmm, fired):
    # Nunca lanza con entradas arbitrarias
    lt = time.localtime()
    try:
        result = wrapper_schedule._crossed_daily_time(lt, hhmm, fired)
        assert isinstance(result, bool)
        result2 = wrapper_schedule._crossed_daily_time(lt, hhmm, None)
        assert isinstance(result2, bool)
    except Exception as e:
        raise AssertionError(f"crash con hhmm={hhmm!r} fired={fired!r}: {e}")


@given(_valid_interval, _valid_hhmm, _valid_hhmm, st.booleans(), st.booleans())
@settings(max_examples=80, suppress_health_check=[HealthCheck.too_slow], deadline=None)
def test_pbt_gui_save_wrapper_load_coherentes(interval, t1, t2, only_players, auto_restart):
    # Config valida guardada por GUI debe ser leida identica por el wrapper
    cfg = {
        "backup_interval_min": interval,
        "backup_only_with_players": only_players,
        "daily_backup_time": t1,
        "auto_restart_on_crash": auto_restart,
        "daily_restart_time": t2,
    }
    with tempfile.TemporaryDirectory() as tmp:
        gui_path = os.path.join(tmp, "schedule_config.json")
        wrapper_path = os.path.join(tmp, "schedule_config_wrapper.json")
        # guardar via GUI (validate estricta)
        import gui_backend.services.schedule_config as sc
        orig = sc.SCHEDULE_PATH
        w_orig = wrapper_schedule.SCHEDULE_CONFIG_PATH
        w_cache = dict(wrapper_schedule._schedule_cfg_cache)
        try:
            sc.SCHEDULE_PATH = gui_path
            ok, saved, _ = sc.save(cfg)
            assert ok
            # leer via GUI load
            loaded_gui = sc.load()
            assert loaded_gui == saved
            # leer via wrapper _load (copiar archivo y resetear cache)
            import shutil
            shutil.copy(gui_path, wrapper_path)
            wrapper_schedule.SCHEDULE_CONFIG_PATH = wrapper_path
            wrapper_schedule._schedule_cfg_cache = {"mtime": None, "cfg": dict(wrapper_schedule.SCHEDULE_DEFAULTS)}
            loaded_wrapper = wrapper_schedule._load_schedule_config()
            assert loaded_wrapper == loaded_gui, f"drift GUI {loaded_gui} vs wrapper {loaded_wrapper}"
        finally:
            sc.SCHEDULE_PATH = orig
            wrapper_schedule.SCHEDULE_CONFIG_PATH = w_orig
            wrapper_schedule._schedule_cfg_cache = w_cache


# ═══════════════════════════════════════════════════════════════════════
# Inspeccion de fuentes (estilo test_review_hallazgos)
# ═══════════════════════════════════════════════════════════════════════
def test_watchdog_no_escribe_stdin():
    """El watchdog re-arranca procesos; jamas escribe al stdin del wrapper.
    Mantiene el invariante writes==6 de test_review_hallazgos."""
    src = open(os.path.join(BASE_DIR, "gui_backend", "services", "watchdog.py"), encoding="utf-8").read()
    assert "stdin" not in src
    # lifecycle: restart_wrapper (1) + stop_and_wait compartido con update y
    # rollback (1). El total global sigue siendo 6 (test_review_hallazgos).
    lifecycle_src = open(os.path.join(BASE_DIR, "gui_backend", "services", "lifecycle.py"), encoding="utf-8").read()
    assert lifecycle_src.count("manager.wrapper_process.stdin.write") == 2
