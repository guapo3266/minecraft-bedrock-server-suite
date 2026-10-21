# -*- coding: utf-8 -*-
"""Regresiones de la revision del 2026-10-20 (10 hallazgos).

1. El restore no devuelve los packs que distribuye BDS (mezcla de versiones).
2. El watchdog no reinicia un arranque fresco ni repite el backup diario.
3. La fase 1 de stop/restart no cuenta el backup inicial previo a BDS.
4. Un progress.json activo sin actualizacion viva no bloquea la ventana.
5. Un fallo al guardar la version anterior no revierte una actualizacion BDS.
6. Los backups en caliente admiten mundos con coma en el nombre.
7. El editor de server.properties escribe con la misma regla que lee.
8. La restauracion por CLI detecta el wrapper aunque BDS no corra.
9. El guard de relevo de la suite no depende de una unica llamada de health.
10. GET /api/backups tolera ZIPs borrados por la rotacion a mitad del listado.

Revision de documentacion del mismo dia: las notas de Release reescriben los
enlaces relativos del CHANGELOG (tools/release_notes.py).
"""
import asyncio
import io
import json
import os
import threading
import time
import types
import zipfile
from pathlib import Path

import psutil
import pytest
from hypothesis import given, settings, strategies as st

import restore_backup
import restore_core
import server_gui_server as gui
import server_properties
import suite_release
import suite_updater
import windows_process_guard as wpg
import wrapper_console
import wrapper_schedule
import zip_safety
from gui_backend import config, supervisor
from gui_backend.services import backups as backups_service
from gui_backend.services import bds_update, lifecycle, schedule_config, suite_update, watchdog
from gui_backend.services import properties as properties_service
from gui_backend.state import manager
from tools import release_notes

ROOT = Path(__file__).resolve().parents[1]
URL_BDS = "https://www.minecraft.net/bedrockdedicatedserver/bin-win/bedrock-server-1.2.3.4.zip"


def _arbol(base, archivos):
    for rel, data in archivos.items():
        path = Path(base) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def _zip(path, entradas):
    with zipfile.ZipFile(path, "w") as zf:
        for nombre, data in entradas.items():
            zf.writestr(nombre, data)


# ═══════════════════════════════════════════════════════════════════════
# 1. Packs de BDS: el restore los deja en su version instalada
# ═══════════════════════════════════════════════════════════════════════
def _instalacion_con_packs(tmp_path):
    base = tmp_path / "inst"
    mundo = base / "worlds" / "Mundo"
    _arbol(base, {
        "worlds/Mundo/level.dat": b"MUNDO-ACTUAL",
        "behavior_packs/vanilla/entities.json": b"VANILLA-NUEVO",
        "behavior_packs/MiAddon/manifest.json": b"ADDON-ACTUAL",
    })
    return base, mundo


def test_restore_conserva_packs_de_bds_y_restaura_addons(tmp_path):
    base, mundo = _instalacion_con_packs(tmp_path)
    zpath = tmp_path / "backup.zip"
    _zip(zpath, {
        "level.dat": b"MUNDO-BACKUP",
        "server_behavior_packs/vanilla/entities.json": b"VANILLA-VIEJO",
        "server_resource_packs/vanilla_base/textures.json": b"VANILLA-BASE-VIEJO",
        "server_behavior_packs/MiAddon/manifest.json": b"ADDON-BACKUP",
    })
    logs = []

    restore_core.restore_from_zip(str(zpath), str(base), str(mundo), log_fn=logs.append)

    assert (mundo / "level.dat").read_bytes() == b"MUNDO-BACKUP"
    assert (base / "behavior_packs/MiAddon/manifest.json").read_bytes() == b"ADDON-BACKUP"
    # Sin registro, el nombre identifica los packs de Mojang: siguen como estaban.
    assert (base / "behavior_packs/vanilla/entities.json").read_bytes() == b"VANILLA-NUEVO"
    assert not (base / "resource_packs/vanilla_base").exists()
    assert sorted(os.listdir(base / "behavior_packs")) == ["MiAddon", "vanilla"]
    assert any("BDS packs kept" in m or "Packs de BDS conservados" in m for m in logs), logs


def test_restore_con_registro_decide_solo_el_registro(tmp_path):
    base, mundo = _instalacion_con_packs(tmp_path)
    _arbol(base, {"behavior_packs/pack_propio_de_bds/a.json": b"BDS-INSTALADO"})
    zip_safety.record_bds_shipped_packs(str(base), {"behavior_packs": ["Pack_Propio_De_BDS"]})
    zpath = tmp_path / "backup.zip"
    _zip(zpath, {
        "level.dat": b"MUNDO-BACKUP",
        "server_behavior_packs/pack_propio_de_bds/a.json": b"BDS-VIEJO",
        "server_behavior_packs/vanilla/entities.json": b"VANILLA-DEL-BACKUP",
    })

    restore_core.restore_from_zip(str(zpath), str(base), str(mundo), log_fn=lambda _m: None)

    assert (base / "behavior_packs/pack_propio_de_bds/a.json").read_bytes() == b"BDS-INSTALADO"
    # Con registro, un nombre "de Mojang" que BDS no instalo se restaura como addon.
    assert (base / "behavior_packs/vanilla/entities.json").read_bytes() == b"VANILLA-DEL-BACKUP"


def test_registro_vacio_no_desactiva_el_patron_de_nombres(tmp_path):
    # Un registro sin nombres no aporta nada: se lee como ausente...
    ruta = Path(zip_safety.bds_packs_record_path(str(tmp_path)))
    ruta.parent.mkdir(parents=True)
    ruta.write_text(json.dumps({"behavior_packs": [], "resource_packs": []}), encoding="utf-8")
    assert zip_safety.read_bds_shipped_packs(str(tmp_path)) is None
    assert zip_safety.is_bds_pack("behavior_packs", "vanilla",
                                  zip_safety.read_bds_shipped_packs(str(tmp_path))) is True
    # ...y no se escribe uno nuevo si no hay nada que anotar.
    ruta.unlink()
    zip_safety.record_bds_shipped_packs(str(tmp_path), {"behavior_packs": [], "resource_packs": []})
    assert not ruta.exists()


@pytest.mark.parametrize("nombre,esperado", [
    ("vanilla", True), ("vanilla_base", True), ("vanilla_1.21.40", True),
    ("Vanilla_1.16.100", True), ("chemistry", True), ("chemistry_1.20.50", True),
    ("editor", True), ("experimental_y_2026_drop_3", True), ("server_library", True),
    ("server_ui_library", True), ("server_editor_library", True),
    ("vanilla_tweaks", False), ("MiAddon", False), ("ThatMob's Verity by PnTMC [BP]", False),
    ("editor_plus", False), ("", False),
])
def test_patron_de_packs_de_bds_sin_registro(nombre, esperado):
    assert zip_safety.is_bds_pack("behavior_packs", nombre, None) is esperado


def _zip_bds(carpetas_de_pack):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("bedrock_server.exe", b"exe")
        for carpeta in carpetas_de_pack:
            zf.writestr(carpeta + "/manifest.json", b"{}")
    return buf.getvalue()


class _RespZip:
    def __init__(self, contenido):
        self.status_code = 200
        self.headers = {"Content-Length": str(len(contenido))}
        self._contenido = contenido

    def iter_content(self, chunk_size=8192):
        for i in range(0, len(self._contenido), chunk_size):
            yield self._contenido[i:i + chunk_size]


def _instalar_bds_desde(monkeypatch, tmp_path, contenido):
    monkeypatch.setattr(bds_update.config, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(bds_update, "PREVIOUS_VERSION_DIR", str(tmp_path / "data" / "bds_previous"))
    monkeypatch.setattr(bds_update, "_fetch_latest_bedrock_download", lambda: (URL_BDS, "1.2.3.4"))
    monkeypatch.setattr(bds_update.requests, "get", lambda *a, **k: _RespZip(contenido))
    monkeypatch.setattr(manager, "installed_version", None)


def test_instalar_bds_registra_sus_packs_y_acumula(monkeypatch, tmp_path):
    _instalar_bds_desde(monkeypatch, tmp_path, _zip_bds(["behavior_packs/vanilla", "resource_packs/vanilla_base"]))
    ok, _version = bds_update._download_and_install_bds(log_fn=lambda *a: None)
    assert ok is True
    assert zip_safety.read_bds_shipped_packs(str(tmp_path)) == {
        "behavior_packs": {"vanilla"}, "resource_packs": {"vanilla_base"},
    }

    # Una actualizacion posterior suma sus carpetas (union): las anteriores
    # siguen siendo de BDS aunque el ZIP nuevo ya no las traiga.
    monkeypatch.setattr(bds_update.requests, "get",
                        lambda *a, **k: _RespZip(_zip_bds(["behavior_packs/experimental_nuevo"])))
    ok, _version = bds_update._download_and_install_bds(log_fn=lambda *a: None)
    assert ok is True
    assert zip_safety.read_bds_shipped_packs(str(tmp_path))["behavior_packs"] == {"vanilla", "experimental_nuevo"}


# ═══════════════════════════════════════════════════════════════════════
# 2. Watchdog diario: sin reinicio de un arranque fresco ni backup duplicado
# ═══════════════════════════════════════════════════════════════════════
@pytest.fixture
def watchdog_aislado(monkeypatch, tmp_path):
    def preparar(**cfg):
        cfg_path = tmp_path / "schedule_config.json"
        datos = dict(schedule_config.DEFAULTS)
        datos.update(cfg)
        cfg_path.write_text(json.dumps(datos), encoding="utf-8")
        monkeypatch.setattr(schedule_config, "SCHEDULE_PATH", str(cfg_path))
        monkeypatch.setattr(watchdog, "STATE_PATH", str(tmp_path / "schedule_state_gui.json"))
        watchdog._reset_state_for_tests()
        monkeypatch.setattr(manager, "is_running", False)
        monkeypatch.setattr(manager, "start_time", None)
        monkeypatch.setattr(manager, "stop_requested", True)
        logs = []
        monkeypatch.setattr(manager, "add_log", lambda *a, **k: logs.append(a[0]))
        return logs

    yield preparar
    watchdog._reset_state_for_tests()


def _hora(h, m, dia=16):
    return time.mktime((2026, 8, dia, h, m, 0, 0, 0, -1))


def test_reinicio_diario_omitido_si_el_servidor_arranco_despues(watchdog_aislado, monkeypatch):
    logs = watchdog_aislado(daily_restart_time="04:00")
    reinicios = []
    monkeypatch.setattr(lifecycle, "restart_wrapper", lambda: reinicios.append(1))
    # Apagado a las 04:00; el usuario lo arranca a las 09:59 de ese dia.
    monkeypatch.setattr(manager, "is_running", True)
    monkeypatch.setattr(manager, "start_time", _hora(9, 59))

    watchdog._watchdog_tick(now=_hora(10, 0))
    watchdog._watchdog_tick(now=_hora(10, 1))

    assert reinicios == []
    assert watchdog.last_daily_restart_date == "2026-08-16"
    assert any("skipped" in m or "omitido" in m for m in logs), logs


def test_reinicio_diario_sigue_si_el_servidor_ya_corria_a_la_hora(watchdog_aislado, monkeypatch):
    watchdog_aislado(daily_restart_time="04:00")
    reinicios = []
    monkeypatch.setattr(lifecycle, "restart_wrapper", lambda: reinicios.append(1))
    monkeypatch.setattr(manager, "is_running", True)
    monkeypatch.setattr(manager, "start_time", _hora(23, 0, dia=15))  # desde la noche anterior

    watchdog._watchdog_tick(now=_hora(4, 0))
    watchdog._watchdog_tick(now=_hora(4, 1))

    assert reinicios == [1]


def test_backup_diario_en_frio_no_repite_el_del_wrapper(watchdog_aislado, monkeypatch):
    watchdog_aislado(daily_backup_time="04:00")
    frios = []
    monkeypatch.setattr(lifecycle, "cold_backup", lambda trigger: frios.append(trigger))
    # Encendido a las 04:00: el wrapper hizo (y anoto) el backup diario en caliente.
    wrapper_schedule._save_last_daily_backup_date("2026-08-16")

    watchdog._watchdog_tick(now=_hora(22, 0))  # primer tick tras detenerlo

    assert frios == []
    assert watchdog.last_daily_cold_backup_date == "2026-08-16"


def test_backup_diario_en_frio_sigue_si_el_wrapper_no_lo_hizo(watchdog_aislado, monkeypatch):
    watchdog_aislado(daily_backup_time="04:00")
    frios = []
    monkeypatch.setattr(lifecycle, "cold_backup", lambda trigger: frios.append(trigger))
    wrapper_schedule._save_last_daily_backup_date("2026-08-15")

    watchdog._watchdog_tick(now=_hora(22, 0))

    assert frios == ["scheduled"]


def test_launch_wrapper_fija_el_arranque_de_la_sesion_nueva(monkeypatch):
    monkeypatch.setattr(manager, "is_running", False)
    monkeypatch.setattr(manager, "wrapper_process", None)
    monkeypatch.setattr(manager, "start_time", 1.0)  # sesion anterior
    monkeypatch.setattr(manager, "wrapper_exit_event", threading.Event())
    monkeypatch.setattr(manager, "server_stopped_event", threading.Event())
    monkeypatch.setattr(supervisor, "_spawn_wrapper_process", lambda: types.SimpleNamespace(stdin=None))
    monkeypatch.setattr(supervisor, "run_wrapper_thread", lambda *a, **k: None)
    antes = time.time()

    status, _detalle = lifecycle._launch_wrapper()

    assert status == "starting"
    assert manager.start_time >= antes


# ═══════════════════════════════════════════════════════════════════════
# 3. Fase 1: el backup inicial previo a BDS no consume el plazo
# ═══════════════════════════════════════════════════════════════════════
def test_eventos_marcan_la_ventana_previa_a_bds(monkeypatch):
    monkeypatch.setattr(manager, "wrapper_pre_bds", False)
    monkeypatch.setattr(manager, "events_alive", False)
    monkeypatch.setattr(manager, "installed_version", None)

    supervisor._apply_event({"event": "wrapper_started", "pid": 1, "initial_backup": True})
    assert manager.wrapper_pre_bds is True
    supervisor._apply_event({"event": "bds_launched", "pid": 2})
    assert manager.wrapper_pre_bds is False

    supervisor._apply_event({"event": "wrapper_started", "pid": 1, "initial_backup": False})
    assert manager.wrapper_pre_bds is False

    supervisor._apply_event({"event": "wrapper_started", "pid": 1, "initial_backup": True})
    supervisor._apply_event({"event": "version_captured", "version": "1.2.3.4"})
    assert manager.wrapper_pre_bds is False


def _fase1(monkeypatch, timeout, pre_bds):
    evento = threading.Event()
    monkeypatch.setattr(manager, "server_stopped_event", evento)
    monkeypatch.setattr(manager, "is_running", True)
    monkeypatch.setattr(manager, "wrapper_pre_bds", pre_bds)
    monkeypatch.setattr(config, "SERVER_STOP_TIMEOUT_SEC", timeout)
    monkeypatch.setattr(lifecycle, "_PRE_BDS_POLL_SEC", 0.05)
    return evento


def test_fase1_no_cuenta_el_backup_inicial(monkeypatch):
    evento = _fase1(monkeypatch, 0.3, True)

    def wrapper():
        time.sleep(0.8)  # backup inicial mas largo que el plazo de 0.3 s
        manager.wrapper_pre_bds = False  # bds_launched
        time.sleep(0.1)
        evento.set()  # BDS proceso el stop encolado

    hilo = threading.Thread(target=wrapper, daemon=True)
    hilo.start()
    detenido, esperado = lifecycle._wait_server_stopped()
    hilo.join(5)

    assert detenido is True
    assert esperado >= 0.8


def test_fase1_margen_del_backup_inicial_acotado(monkeypatch):
    _fase1(monkeypatch, 0.2, True)
    monkeypatch.setattr(lifecycle, "_pre_bds_allowance_sec", lambda: 0.4)
    inicio = time.monotonic()

    detenido, _esperado = lifecycle._wait_server_stopped()

    assert detenido is False
    assert 0.5 <= time.monotonic() - inicio < 3


def test_fase1_sin_backup_inicial_espera_lo_de_siempre(monkeypatch):
    _fase1(monkeypatch, 75, False)
    # El canal ya confirmo la sesion sin backup inicial (wrapper_started leido):
    # antes de eso se sondea (ronda 2, test_revision_2026-10-20_ronda2.py).
    monkeypatch.setattr(manager, "events_alive", True)
    llamadas = []
    monkeypatch.setattr(manager.server_stopped_event, "wait",
                        lambda timeout=None: llamadas.append(timeout) or False)

    detenido, _esperado = lifecycle._wait_server_stopped()

    assert detenido is False
    assert llamadas == [75]


class _StdinEspia:
    def __init__(self):
        self.lineas = []

    def write(self, s):
        self.lineas.append(s)

    def flush(self):
        pass


def test_restart_durante_backup_inicial_relanza_el_wrapper(monkeypatch):
    evento_stop = _fase1(monkeypatch, 0.3, True)
    salida = threading.Event()
    monkeypatch.setattr(manager, "wrapper_exit_event", salida)
    monkeypatch.setattr(config, "WRAPPER_EXIT_TIMEOUT_SEC", 3)
    monkeypatch.setattr(manager, "stop_requested", False)
    monkeypatch.setattr(manager, "start_time", None)
    stdin = _StdinEspia()
    monkeypatch.setattr(manager, "wrapper_process", types.SimpleNamespace(stdin=stdin))
    lanzados = []
    monkeypatch.setattr(supervisor, "_spawn_wrapper_process",
                        lambda: lanzados.append(1) or types.SimpleNamespace(stdin=None))
    monkeypatch.setattr(supervisor, "run_wrapper_thread", lambda *a, **k: None)
    logs = []
    monkeypatch.setattr(manager, "add_log", lambda *a, **k: logs.append(a[0]))

    def wrapper():
        time.sleep(0.8)  # termina el backup inicial y lanza BDS
        manager.wrapper_pre_bds = False
        evento_stop.set()  # BDS lee el stop encolado y muere
        time.sleep(0.1)
        manager.is_running = False  # backup final y salida del wrapper
        salida.set()

    threading.Thread(target=wrapper, daemon=True).start()
    lifecycle.restart_wrapper()

    assert stdin.lineas == ["stop\n"]
    assert lanzados == [1], logs
    assert not any("did not stop" in m or "no se detuvo" in m for m in logs), logs


def test_wrapper_emite_bds_launched_tras_lanzar_bds():
    src = (ROOT / "server_wrapper.py").read_text(encoding="utf-8")
    main = src.split('if __name__ == "__main__":')[1]
    i_job = main.index("create_job_object_for_process")
    i_evento = main.index('_emit_event("bds_launched"')
    i_stdin = main.index("target=read_stdin")
    assert i_job < i_evento < i_stdin


# ═══════════════════════════════════════════════════════════════════════
# 4. progress.json activo sin actualizacion viva
# ═══════════════════════════════════════════════════════════════════════
def _area_actualizacion(monkeypatch, tmp_path, progreso, request=None):
    monkeypatch.setattr(suite_update.config, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(suite_update, "_early_progress", None)
    monkeypatch.setattr(manager, "suite_update_in_progress", False)
    job = tmp_path / "data" / "suite_updates" / "recovery"
    suite_release.write_json(job / "progress.json", progreso)
    if request is not None:
        suite_release.write_json(job / "request.json", request)
    return job


@pytest.mark.parametrize("fase", ["downloading", "verifying", "stopping", "waiting_gui",
                                  "applying", "checking", "rolling_back"])
def test_fase_activa_sin_actualizacion_viva_es_interrupcion(monkeypatch, tmp_path, fase):
    _area_actualizacion(monkeypatch, tmp_path, {"phase": fase},
                        {"helper_pid": 0, "helper_created": 0})

    progreso = suite_update.last_progress()

    assert progreso["phase"] == "error"
    assert progreso["interrupted_phase"] == fase
    assert progreso["detail"]


def test_fase_activa_con_auxiliar_vivo_se_respeta(monkeypatch, tmp_path):
    yo = psutil.Process()
    _area_actualizacion(monkeypatch, tmp_path, {"phase": "applying"},
                        {"helper_pid": yo.pid, "helper_created": yo.create_time()})

    assert suite_update.last_progress() == {"phase": "applying"}


def test_fase_activa_de_esta_gui_se_respeta(monkeypatch, tmp_path):
    _area_actualizacion(monkeypatch, tmp_path, {"phase": "stopping"})
    monkeypatch.setattr(manager, "suite_update_in_progress", True)

    assert suite_update.last_progress() == {"phase": "stopping"}


def test_fase_final_se_devuelve_tal_cual(monkeypatch, tmp_path):
    _area_actualizacion(monkeypatch, tmp_path, {"phase": "complete", "version": "9.9.9"})

    assert suite_update.last_progress() == {"phase": "complete", "version": "9.9.9"}


@pytest.mark.parametrize("diario,fase_esperada", [
    # El auxiliar de 2.1.0 no pudo guardar el ultimo aviso: la entrega SI termino.
    ("complete", "complete"),
    ("rolled_back", "rolled_back"),
    ("prepared", "error"),
    # Reemplazo a medias sin auxiliar vivo: toca Recuperar_suite.bat.
    ("applying", "rollback_failed"),
    ("checking", "rollback_failed"),
])
def test_fase_activa_obsoleta_se_resuelve_con_el_diario(monkeypatch, tmp_path, diario, fase_esperada):
    job = _area_actualizacion(monkeypatch, tmp_path, {"phase": "checking", "version": "9.9.9"},
                              {"helper_pid": 0, "helper_created": 0})
    suite_release.write_json(job / "journal.json", {"phase": diario})

    progreso = suite_update.last_progress()

    assert progreso["phase"] == fase_esperada
    assert progreso["interrupted_phase"] == "checking"
    # Nunca con "version": el navegador recargaria en bucle si no coincide.
    assert "version" not in progreso
    if fase_esperada == "rollback_failed":
        assert "Recuperar_suite.bat" in progreso["detail"]


# ═══════════════════════════════════════════════════════════════════════
# 5. Version anterior de BDS: un fallo al guardarla no revierte nada
# ═══════════════════════════════════════════════════════════════════════
def test_fallo_al_guardar_version_anterior_no_revierte_la_actualizacion(monkeypatch, tmp_path):
    base, staging = tmp_path / "inst", tmp_path / "staging"
    keep = base / "data" / "bds_previous"
    _arbol(base, {"bedrock_server.exe": b"VIEJO", "lib.dll": b"VIEJO"})
    _arbol(staging, {"bedrock_server.exe": b"NUEVO", "lib.dll": b"NUEVO", "nuevo.txt": b"NUEVO"})
    _arbol(keep, {"bedrock_server.exe": b"ANTERIOR", "bds_previous.json": b'{"version": "0.9"}'})
    replace_real = os.replace

    def replace_bloqueado(src, dst):
        # Simula data/bds_previous retenido: no se puede colocar el resguardo.
        if (os.path.basename(str(src)).startswith("bds_update_prev_")
                and os.path.normcase(str(dst)) == os.path.normcase(str(keep))):
            raise PermissionError("acceso denegado")
        return replace_real(src, dst)

    with monkeypatch.context() as mp:
        mp.setattr(os, "replace", replace_bloqueado)
        with pytest.raises(bds_update.PreviousVersionNotSaved):
            bds_update._apply_staged_update(str(staging), str(base), set(), set(),
                                            keep_prev_dir=str(keep), prev_version="1.0")

    assert (base / "bedrock_server.exe").read_bytes() == b"NUEVO"
    assert (base / "nuevo.txt").read_bytes() == b"NUEVO"
    # La version anterior previa sigue entera (no quedo a medias).
    assert (keep / "bedrock_server.exe").read_bytes() == b"ANTERIOR"
    # El resguardo queda para revision, ya sin manifiesto de recuperacion...
    resguardos = list(base.glob("bds_update_prev_*"))
    assert len(resguardos) == 1
    assert not (resguardos[0] / bds_update._UPDATE_MANIFEST_NAME).exists()
    # ...asi que el siguiente arranque de la GUI NO revierte la actualizacion.
    bds_update.recover_interrupted_updates(str(base))
    assert (base / "bedrock_server.exe").read_bytes() == b"NUEVO"
    assert (base / "nuevo.txt").exists()


def test_guardar_version_anterior_aparta_la_previa_sin_dejar_restos(tmp_path):
    keep = tmp_path / "data" / "bds_previous"
    prev = tmp_path / "bds_update_prev_x"
    _arbol(keep, {"viejo.dll": b"V"})
    _arbol(prev, {"bedrock_server.exe": b"P"})

    bds_update._save_prev_dir(str(prev), str(keep), "1.0")

    assert (keep / "bedrock_server.exe").read_bytes() == b"P"
    assert not (keep / "viejo.dll").exists()
    assert json.loads((keep / "bds_previous.json").read_text(encoding="utf-8"))["version"] == "1.0"
    assert not prev.exists()
    assert list((tmp_path / "data").glob("bds_previous.old_*")) == []


def test_actualizacion_sin_version_anterior_se_informa_como_exito(monkeypatch, tmp_path):
    _instalar_bds_desde(monkeypatch, tmp_path, _zip_bds([]))

    def apply_sin_resguardo(*_a, **_k):
        raise bds_update.PreviousVersionNotSaved("resguardo bloqueado")

    monkeypatch.setattr(bds_update, "_apply_staged_update", apply_sin_resguardo)
    logs = []

    ok, version = bds_update._download_and_install_bds(log_fn=lambda m, t=None: logs.append(m))

    assert ok is True and version == "1.2.3.4"
    assert any("resguardo bloqueado" in m for m in logs), logs


# ═══════════════════════════════════════════════════════════════════════
# 6. save query con comas en el nombre del mundo
# ═══════════════════════════════════════════════════════════════════════
def test_save_query_con_coma_en_el_nombre_del_mundo():
    linea = "Mi mundo, el mejor/db/000005.ldb:1234, Mi mundo, el mejor/level.dat:2048"

    assert wrapper_console.parse_save_query_files(linea) == [
        ("Mi mundo, el mejor/db/000005.ldb", 1234),
        ("Mi mundo, el mejor/level.dat", 2048),
    ]


_segmento = st.text(
    alphabet=st.characters(blacklist_categories=("Zs", "Zl", "Zp", "Cc", "Cs"),
                           blacklist_characters=":,\r\n/\\<"),
    min_size=1, max_size=12,
)


@st.composite
def _linea_con_comas_en_el_mundo(draw):
    mundo = ", ".join(draw(st.lists(_segmento, min_size=1, max_size=3)))
    pares = draw(st.lists(
        st.tuples(st.lists(_segmento, min_size=1, max_size=3).map("/".join),
                  st.integers(min_value=0, max_value=2**31 - 1)),
        min_size=1, max_size=8,
    ))
    entradas = [(f"{mundo}/{rel}", n) for rel, n in pares]
    return ", ".join(f"{p}:{n}" for p, n in entradas), entradas


@given(_linea_con_comas_en_el_mundo())
@settings(max_examples=200)
def test_save_query_roundtrip_con_comas_en_el_mundo(data):
    linea, esperado = data
    assert wrapper_console.parse_save_query_files(linea) == esperado


# ═══════════════════════════════════════════════════════════════════════
# 7. server.properties: el editor escribe con la regla del lector
# ═══════════════════════════════════════════════════════════════════════
def _props(monkeypatch, tmp_path, contenido):
    path = tmp_path / "server.properties"
    path.write_bytes(contenido)
    monkeypatch.setattr(properties_service.config, "PROPS_PATH", str(path))
    return path


def test_guardar_properties_con_bytes_ansi_no_falla_y_conserva_la_linea(monkeypatch, tmp_path):
    original = "server-name=Servidor de Mar\xeda".encode("cp1252")
    path = _props(monkeypatch, tmp_path, original + b"\nmax-players=10\n")

    properties_service._write_props_values({"max-players": "12"})

    assert path.read_bytes() == original + b"\nmax-players=12\n"
    assert server_properties.read_value(str(path), "max-players") == "12"


def test_guardar_properties_reemplaza_la_clave_que_ve_el_lector(monkeypatch, tmp_path):
    path = _props(monkeypatch, tmp_path,
                  b"Server-Name = Viejo\r\ngamemode=survival\r\nserver-name=Duplicada\r\n")

    properties_service._write_props_values({"server-name": "Nuevo", "difficulty": "hard"})

    assert path.read_bytes() == (b"server-name=Nuevo\r\ngamemode=survival\r\n"
                                 b"server-name=Nuevo\r\ndifficulty=hard\r\n")
    assert properties_service._read_props_values()["server-name"] == "Nuevo"


def test_guardar_properties_con_bom_y_sin_salto_final(monkeypatch, tmp_path):
    path = _props(monkeypatch, tmp_path, b"\xef\xbb\xbfserver-name=Viejo\nmax-players=10")

    properties_service._write_props_values({"server-name": "Nuevo", "online-mode": "true"})

    assert path.read_bytes() == b"\xef\xbb\xbfserver-name=Nuevo\nmax-players=10\nonline-mode=true\n"
    assert server_properties.read_value(str(path), "server-name") == "Nuevo"


def test_guardar_properties_ignora_claves_comentadas(monkeypatch, tmp_path):
    path = _props(monkeypatch, tmp_path, b"; server-name=Comentada\n# max-players=5\n")

    properties_service._write_props_values({"server-name": "Activa"})

    assert path.read_bytes() == b"; server-name=Comentada\n# max-players=5\nserver-name=Activa\n"


# ═══════════════════════════════════════════════════════════════════════
# 8. CLI de restauracion: el wrapper vivo veta aunque BDS no corra
# ═══════════════════════════════════════════════════════════════════════
@pytest.mark.skipif(os.name != "nt", reason="mutex nombrado de Windows")
def test_sonda_de_mutex_detecta_un_titular_real():
    nombre = "BDS_Wrapper_revision_2026_10_20_" + os.urandom(4).hex()
    tomado, soltar = threading.Event(), threading.Event()

    def titular():
        # Otro hilo: los mutex de Windows son reentrantes en el mismo hilo.
        mutex = wpg.NamedMutex(nombre)
        try:
            if mutex.acquire(timeout_ms=1000):
                tomado.set()
                soltar.wait(5)
        finally:
            mutex.close()

    hilo = threading.Thread(target=titular, daemon=True)
    hilo.start()
    assert tomado.wait(5)
    try:
        assert wpg.mutex_held_by_other(nombre) is True
    finally:
        soltar.set()
        hilo.join(5)
    assert wpg.mutex_held_by_other(nombre) is False


def test_cli_no_restaura_con_el_wrapper_vivo_sin_bds(monkeypatch):
    if restore_backup.psutil is None:
        pytest.skip("sin psutil la CLI ya aborta (fail-closed)")
    monkeypatch.setattr(restore_backup.psutil, "process_iter", lambda attrs: [])
    monkeypatch.setattr(restore_backup, "_wrapper_holds_mutex", lambda: True)

    assert restore_backup._server_is_running() is True


def test_cli_sonda_del_wrapper_usa_el_mutex_de_la_instalacion(monkeypatch):
    vistos = []
    monkeypatch.setattr(restore_backup.wpg, "mutex_held_by_other",
                        lambda nombre: vistos.append(nombre) or False)

    assert restore_backup._wrapper_holds_mutex() is False
    assert vistos == [wpg.wrapper_mutex_name(restore_backup.BASE_DIR)]


def test_cli_sonda_del_wrapper_fail_closed(monkeypatch):
    def sonda_rota(_nombre):
        raise OSError("sin acceso")

    monkeypatch.setattr(restore_backup.wpg, "mutex_held_by_other", sonda_rota)

    assert restore_backup._wrapper_holds_mutex() is True


# ═══════════════════════════════════════════════════════════════════════
# 9. Guard de relevo de la suite
# ═══════════════════════════════════════════════════════════════════════
def _guard_tomado(monkeypatch, tmp_path, fase=None):
    monkeypatch.setattr(suite_update.config, "BASE_DIR", str(tmp_path))
    lock = threading.Lock()
    lock.acquire()
    monkeypatch.setattr(manager, "op_lock", lock)
    monkeypatch.setattr(manager, "suite_update_in_progress", True)
    monkeypatch.setattr(suite_update, "_handoff_guard", True)
    if fase is not None:
        suite_release.write_json(tmp_path / "data/suite_updates/recovery/journal.json", {"phase": fase})
    return lock


def test_guard_de_relevo_tolera_diario_ausente_y_se_conserva(monkeypatch, tmp_path):
    lock = _guard_tomado(monkeypatch, tmp_path)

    assert suite_update.release_handoff_guard() is False
    assert lock.locked() and manager.suite_update_in_progress is True


def test_guard_de_relevo_no_se_libera_antes_de_complete(monkeypatch, tmp_path):
    lock = _guard_tomado(monkeypatch, tmp_path, "checking")

    assert suite_update.release_handoff_guard() is False
    assert lock.locked()


def test_guard_de_relevo_se_libera_con_complete(monkeypatch, tmp_path):
    lock = _guard_tomado(monkeypatch, tmp_path, "complete")

    assert suite_update.release_handoff_guard() is True
    assert not lock.locked()
    assert manager.suite_update_in_progress is False
    assert suite_update.release_handoff_guard() is False  # idempotente


class _CorteDelLoop(BaseException):
    """Sale del loop de metricas (su except Exception no lo atrapa)."""


def test_loop_de_metricas_intenta_liberar_el_guard(monkeypatch):
    llamadas = []
    monkeypatch.setattr(gui.suite_update_service, "release_handoff_guard",
                        lambda: llamadas.append(1) or False)
    monkeypatch.setattr(gui.external_probe_service, "update_external_instance_state",
                        lambda: (False, None))

    def cortar():
        raise _CorteDelLoop()

    monkeypatch.setattr(manager, "update_status", cortar)

    with pytest.raises(_CorteDelLoop):
        asyncio.run(gui.hardware_metrics_loop())
    assert llamadas == [1]


def test_auxiliar_reintenta_la_confirmacion_del_relevo(monkeypatch):
    intentos = []

    def get_json(port, route, body=None):
        intentos.append(route)
        if len(intentos) < 3:
            raise OSError("GUI ocupada")
        return {"version": "9.9.9"}

    monkeypatch.setattr(suite_updater, "get_json", get_json)

    suite_updater.confirm_handoff(8000, delay=0)

    assert intentos == ["/api/suite_update/health"] * 3


def test_auxiliar_agota_los_reintentos_y_propaga(monkeypatch):
    def caida(*_a, **_k):
        raise OSError("GUI caida")

    monkeypatch.setattr(suite_updater, "get_json", caida)

    with pytest.raises(OSError):
        suite_updater.confirm_handoff(8000, attempts=3, delay=0)


# ═══════════════════════════════════════════════════════════════════════
# 10. Listado de backups durante una rotacion
# ═══════════════════════════════════════════════════════════════════════
def test_listado_de_backups_tolera_un_zip_borrado_por_la_rotacion(monkeypatch, tmp_path):
    viejo, nuevo = tmp_path / "auto_backup_a.zip", tmp_path / "auto_backup_b.zip"
    viejo.write_bytes(b"x" * 10)
    nuevo.write_bytes(b"y" * 20)
    os.utime(viejo, (1_000_000, 1_000_000))
    os.utime(nuevo, (2_000_000, 2_000_000))
    rotado = str(tmp_path / "auto_backup_rotado.zip")  # ya no existe
    monkeypatch.setattr(backups_service, "_list_backup_files",
                        lambda _d: [str(viejo), rotado, str(nuevo)])

    info = backups_service.list_backup_info(str(tmp_path))

    assert [b["filename"] for b in info] == ["auto_backup_b.zip", "auto_backup_a.zip"]


# ═══════════════════════════════════════════════════════════════════════
# Revision de documentacion: notas de Release con enlaces que resuelven
# ═══════════════════════════════════════════════════════════════════════
def test_notas_de_release_reescriben_enlaces_relativos():
    texto = ("Ver [guia](docs/ACTUALIZACIONES_SUITE.md), [ancla](./docs/VERSIONADO.md#elegir), "
             "[web](https://example.com/x), [local](#seccion) y [fuera](../otro.md).")
    base = f"https://github.com/{suite_release.REPOSITORY}/blob/main/"

    resultado = release_notes.absolute_links(texto)

    assert f"[guia]({base}docs/ACTUALIZACIONES_SUITE.md)" in resultado
    assert f"[ancla]({base}docs/VERSIONADO.md#elegir)" in resultado
    assert "[web](https://example.com/x)" in resultado
    assert "[local](#seccion)" in resultado
    assert "[fuera](../otro.md)" in resultado


def test_notas_de_release_de_la_version_actual_no_llevan_rutas_relativas():
    notas = release_notes.release_notes()

    assert notas.startswith("# Bedrock Suite ")
    assert "](docs/" not in notas and "](./" not in notas
