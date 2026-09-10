# -*- coding: utf-8 -*-
"""Unitarios del scheduler del wrapper (wrapper_schedule): coerciones,
recarga por mtime, estado diario y semantica de _crossed_daily_time."""
import json
import time

import pytest

import wrapper_schedule as ws


@pytest.fixture
def sched_paths(tmp_path, monkeypatch):
    cfg = tmp_path / "schedule_config.json"
    state = tmp_path / "schedule_state_wrapper.json"
    monkeypatch.setattr(ws, "SCHEDULE_CONFIG_PATH", str(cfg))
    monkeypatch.setattr(ws, "SCHEDULE_STATE_PATH", str(state))
    monkeypatch.setattr(ws, "_schedule_cfg_cache",
                        {"mtime": None, "cfg": dict(ws.SCHEDULE_DEFAULTS)})
    monkeypatch.setattr(ws, "last_daily_backup_date", None)
    return cfg, state


def _config(**overrides):
    cfg = dict(ws.SCHEDULE_DEFAULTS)
    cfg.update(overrides)
    return json.dumps(cfg)


def test_config_ausente_da_defaults(sched_paths):
    assert ws._load_schedule_config() == ws.SCHEDULE_DEFAULTS


def test_config_corrupta_da_defaults(sched_paths):
    cfg, _ = sched_paths
    cfg.write_text("{no-json", encoding="utf-8")
    assert ws._load_schedule_config() == ws.SCHEDULE_DEFAULTS


def test_config_se_relee_al_cambiar(sched_paths):
    cfg, _ = sched_paths
    cfg.write_text(_config(backup_interval_min=10), encoding="utf-8")
    assert ws._load_schedule_config()["backup_interval_min"] == 10
    time.sleep(0.02)
    cfg.write_text(_config(backup_interval_min=45), encoding="utf-8")
    assert ws._load_schedule_config()["backup_interval_min"] == 45


@pytest.mark.parametrize("value,esperado", [
    (10, 10), (" 30 ", 30), ("45.0", 45), (60.0, 60),
    (4, 30), (1441, 30), (True, 30), ("abc", 30), ("", 30),
    (30.5, 30), (None, 30),
])
def test_coerce_intervalo(value, esperado):
    assert ws._coerce_schedule_value("backup_interval_min", value) == esperado


@pytest.mark.parametrize("value,esperado", [
    (True, True), (False, False), ("yes", True), ("OFF", False),
    ("1", True), ("0", False), (None, True), (5, True),
])
def test_coerce_bool_only_players(value, esperado):
    # El default de la clave es True; cualquier valor no reconocido cae ahi.
    assert ws._coerce_schedule_value("backup_only_with_players", value) is esperado


@pytest.mark.parametrize("value,esperado", [
    ("04:00", "04:00"), (" 23:59 ", "23:59"),
    ("24:00", None), ("4:00", None), (None, None), (4, None), ("", None),
])
def test_coerce_hora_diaria(value, esperado):
    assert ws._coerce_schedule_value("daily_backup_time", value) == esperado


def test_estado_diario_roundtrip(sched_paths):
    assert ws._load_last_daily_backup_date() is None
    ws._save_last_daily_backup_date("2026-09-10")
    assert ws._load_last_daily_backup_date() == "2026-09-10"


def test_estado_diario_corrupto_o_ajeno_devuelve_none(sched_paths):
    _, state = sched_paths
    state.write_text("{roto", encoding="utf-8")
    assert ws._load_last_daily_backup_date() is None
    state.write_text(json.dumps({"otra": 1}), encoding="utf-8")
    assert ws._load_last_daily_backup_date() is None


def test_crossed_daily_time_semantica():
    lt = time.struct_time((2026, 9, 10, 4, 0, 0, 0, 0, -1))
    assert ws._crossed_daily_time(lt, "04:00", None) is True
    assert ws._crossed_daily_time(lt, "03:59", None) is True
    assert ws._crossed_daily_time(lt, "04:01", None) is False
    assert ws._crossed_daily_time(lt, "04:00", "2026-09-10") is False
    assert ws._crossed_daily_time(lt, None, None) is False
    assert ws._crossed_daily_time(lt, "aa:bb", None) is False
