# -*- coding: utf-8 -*-
"""Regresiones de la segunda revisión del 2026-10-20 (8 hallazgos).

1. El arranque de otra GUI (o del wrapper) recuperaba como interrumpida la
   operación en curso de otro proceso: exclusión por instalación.
2. Recuperar un rollback de BDS interrumpido dejaba data/bds_previous
   incompleto y se seguía ofreciendo: el manifiesto anota el staging.
3. La CLI de restore comprobaba una sola vez, antes de pedir confirmación.
4. Una junction en la raíz de packs hacía restaurar (y respaldar) fuera de la
   instalación.
5. El backup en caliente fallaba con archivos de más de 2 GiB (ZIP64).
6. Guardar parte de la programación borraba los demás ajustes.
7. La espera de la fase 1 miraba el flag del backup inicial una sola vez.
8. iniciar_servidor.bat con el runtime del ZIP no pasaba por el primer
   arranque de BDS.

Todo con directorios temporales: nunca toca la instalación real.
"""
import contextlib
import glob
import json
import os
import re
import shutil
import threading
import time
import zipfile

import pytest

import auto_backup
import restore_backup
import restore_core
import server_gui_server as gui
import windows_process_guard as wpg
import zip_safety
from fastapi import HTTPException
from gui_backend import config, supervisor
from gui_backend.services import backups as backups_service
from gui_backend.services import bds_update, external_probe, lifecycle, schedule_config
from gui_backend.state import manager

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _espera_corta(monkeypatch):
    # Una operación ajena real retiene el mutex; no hace falta esperar 2 s.
    monkeypatch.setattr(wpg, "_OPS_TIMEOUT_MS", 100)


@contextlib.contextmanager
def _otro_proceso_opera(base_dir):
    """Retiene el mutex de operación desde otro hilo (como otro proceso).

    Los mutex de Windows pertenecen al hilo: para este proceso, un hilo
    distinto que lo retiene es indistinguible de otro proceso.
    """
    listo, soltar = threading.Event(), threading.Event()

    def _retener():
        mutex = wpg.NamedMutex(wpg.installation_ops_mutex_name(str(base_dir)))
        mutex.acquire(timeout_ms=-1)
        listo.set()
        soltar.wait(10)
        mutex.close()

    hilo = threading.Thread(target=_retener, daemon=True)
    hilo.start()
    assert listo.wait(5)
    try:
        yield
    finally:
        soltar.set()
        hilo.join(5)


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def _read(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None


# ═══════════════════════════════════════════════════════════════════════
# 1. Exclusión por instalación entre recovery y operaciones
# ═══════════════════════════════════════════════════════════════════════
def test_operacion_ocupada_por_otro_proceso(tmp_path):
    with _otro_proceso_opera(tmp_path):
        with pytest.raises(wpg.InstallationBusy):
            with wpg.installation_operation(str(tmp_path)):
                pytest.fail("no debía entrar con otro titular")
        assert wpg.installation_busy_by_other(str(tmp_path)) is True
    assert wpg.installation_busy_by_other(str(tmp_path)) is False
    with wpg.installation_operation(str(tmp_path)):
        pass


def test_la_operacion_propia_no_cuenta_como_ajena(tmp_path):
    dentro, salir = threading.Event(), threading.Event()

    def _operar():
        with wpg.installation_operation(str(tmp_path)):
            dentro.set()
            salir.wait(5)

    hilo = threading.Thread(target=_operar, daemon=True)
    hilo.start()
    assert dentro.wait(5)
    try:
        # p. ej. el restore de la GUI en el threadpool y la sonda en otro hilo
        assert wpg.installation_busy_by_other(str(tmp_path)) is False
    finally:
        salir.set()
        hilo.join(5)


def test_recovery_de_otra_gui_no_revierte_una_actualizacion_en_curso(tmp_path, monkeypatch):
    base = tmp_path / "base"
    staging = tmp_path / "staging"
    _write(str(base / "bedrock_server.exe"), b"EXE-v1")
    _write(str(base / "lib.dll"), b"DLL-v1")
    _write(str(staging / "bedrock_server.exe"), b"EXE-v2")
    _write(str(staging / "lib.dll"), b"DLL-v2")
    monkeypatch.setattr(config, "BASE_DIR", str(base))
    logs = []
    monkeypatch.setattr(manager, "add_log", lambda msg, *a, **k: logs.append(msg))

    real_replace = os.replace
    disparado = []

    def _replace(src, dst):
        # A mitad de la fase 2 arranca otra GUI de la misma instalación.
        if not disparado and str(src).startswith(str(staging)):
            disparado.append(True)
            hilo = threading.Thread(target=gui._recover_installation)
            hilo.start()
            hilo.join(10)
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", _replace)
    bds_update._apply_staged_update(str(staging), str(base), set(), set())

    assert disparado
    assert _read(str(base / "bedrock_server.exe")) == b"EXE-v2"
    assert _read(str(base / "lib.dll")) == b"DLL-v2"
    assert not list(base.glob("bds_update_prev_*"))
    assert any("No se revisan" in m or "are not checked" in m for m in logs)


def test_recovery_de_arranque_corre_si_nadie_opera(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    llamadas = []
    monkeypatch.setattr(auto_backup, "recover_interrupted_restores", lambda *a, **k: llamadas.append("restores"))
    monkeypatch.setattr(bds_update, "recover_interrupted_updates", lambda *a, **k: llamadas.append("bds"))

    gui._recover_installation()
    assert llamadas == ["restores", "bds"]

    llamadas.clear()
    monkeypatch.setattr(manager, "add_log", lambda *a, **k: None)
    with _otro_proceso_opera(tmp_path):
        gui._recover_installation()
    assert llamadas == []


def test_aplicar_bds_con_otra_operacion_no_toca_archivos(tmp_path):
    base, staging = tmp_path / "base", tmp_path / "staging"
    _write(str(base / "bedrock_server.exe"), b"EXE-v1")
    _write(str(staging / "bedrock_server.exe"), b"EXE-v2")

    with _otro_proceso_opera(base):
        with pytest.raises(wpg.InstallationBusy):
            bds_update._apply_staged_update(str(staging), str(base), set(), set())

    assert _read(str(base / "bedrock_server.exe")) == b"EXE-v1"
    assert _read(str(staging / "bedrock_server.exe")) == b"EXE-v2"
    assert not list(base.glob("bds_update_prev_*"))


def test_restore_de_la_gui_rechaza_si_otro_proceso_opera(tmp_path, monkeypatch):
    monkeypatch.setattr(auto_backup, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(manager, "is_running", False)
    llamado = []
    monkeypatch.setattr(auto_backup, "restore_backup", lambda *a: llamado.append(a))

    with _otro_proceso_opera(tmp_path):
        with pytest.raises(HTTPException) as exc:
            backups_service.restore_backup_under_lock(manager, "auto_backup_x.zip")

    assert exc.value.status_code == 409
    assert llamado == []


def test_la_sonda_ve_una_operacion_de_otro_proceso(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "is_running", False)
    assert external_probe.detect_external_bds(str(tmp_path)) == (False, None)
    with _otro_proceso_opera(tmp_path):
        assert external_probe.detect_external_bds(str(tmp_path)) == (True, "installation_busy")


def test_el_wrapper_recupera_bajo_la_exclusion_y_aborta_si_esta_ocupada():
    with open(os.path.join(BASE_DIR, "server_wrapper.py"), encoding="utf-8") as f:
        fuente = f.read()
    main = fuente[fuente.index('if __name__ == "__main__":'):]
    exclusion = main.index("wpg.installation_operation(wstate.BASE_DIR)")
    recovery = main.index("auto_backup.recover_interrupted_restores(wstate.BASE_DIR)")
    ocupada = main.index("except wpg.InstallationBusy")
    assert exclusion < recovery < ocupada
    assert "sys.exit(1)" in main[ocupada:ocupada + 300]
    # El mutex propio del wrapper va antes: un restore posterior lo verá vivo.
    assert main.index("wrapper_mutex.acquire") < exclusion


# ═══════════════════════════════════════════════════════════════════════
# 2. Recovery de un rollback de BDS interrumpido
# ═══════════════════════════════════════════════════════════════════════
class _Muerte(BaseException):
    """El proceso muere: ni except ni el resto del flujo llegan a correr."""


def _instalacion_con_resguardo(base):
    prev = base / "data" / "bds_previous"
    _write(str(base / "bedrock_server.exe"), b"EXE-v2")
    _write(str(base / "lib.dll"), b"DLL-v2")
    _write(str(prev / "bedrock_server.exe"), b"EXE-v1")
    _write(str(prev / "lib.dll"), b"DLL-v1")
    (prev / "bds_previous.json").write_text(json.dumps({"version": "v1"}), encoding="utf-8")
    return prev


def test_rollback_interrumpido_devuelve_al_resguardo_lo_ya_aplicado(tmp_path, monkeypatch):
    base = tmp_path / "base"
    imagen = tmp_path / "imagen"  # estado en disco en el instante de la muerte
    prev = _instalacion_con_resguardo(base)

    real_replace = os.replace
    fase2 = []

    def _replace(src, dst):
        if str(src).startswith(str(prev)) and not str(src).endswith(".json"):
            fase2.append(src)
            if len(fase2) == 2:  # el primer archivo ya salió del resguardo
                shutil.copytree(base, imagen)
                raise _Muerte()
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", _replace)
    with pytest.raises(_Muerte):
        bds_update._apply_staged_update(str(prev), str(base), set(), set(),
                                        keep_prev_dir=str(prev), prev_version="v2",
                                        preserve_staging_on_failure=True)
    monkeypatch.setattr(os, "replace", real_replace)

    resguardos = list(imagen.glob("bds_update_prev_*"))
    assert len(resguardos) == 1
    with open(resguardos[0] / bds_update._UPDATE_MANIFEST_NAME, encoding="utf-8") as f:
        assert json.load(f)["staging"] == "data/bds_previous"

    imagen_prev = imagen / "data" / "bds_previous"
    bds_update.recover_interrupted_updates(str(imagen))

    # La instalación vuelve entera a v2 y el resguardo conserva v1 completo.
    assert _read(str(imagen / "bedrock_server.exe")) == b"EXE-v2"
    assert _read(str(imagen / "lib.dll")) == b"DLL-v2"
    assert _read(str(imagen_prev / "bedrock_server.exe")) == b"EXE-v1"
    assert _read(str(imagen_prev / "lib.dll")) == b"DLL-v1"
    assert not list(imagen.glob("bds_update_prev_*"))

    # Un segundo rollback deja v1 completo, sin mezclar versiones.
    bds_update._apply_staged_update(str(imagen_prev), str(imagen), set(), set(),
                                    keep_prev_dir=str(imagen_prev), prev_version="v2",
                                    preserve_staging_on_failure=True)
    assert _read(str(imagen / "bedrock_server.exe")) == b"EXE-v1"
    assert _read(str(imagen / "lib.dll")) == b"DLL-v1"


def test_recovery_con_staging_es_idempotente(tmp_path):
    """Una recuperación cortada a medias se puede repetir."""
    base = tmp_path
    prev = base / "data" / "bds_previous"
    crash = base / "bds_update_prev_x"
    # Fase 2 a medias: EXE-v1 aplicado, DLL-v1 aún en el resguardo.
    _write(str(base / "bedrock_server.exe"), b"EXE-v1")
    _write(str(prev / "lib.dll"), b"DLL-v1")
    _write(str(crash / "bedrock_server.exe"), b"EXE-v2")
    _write(str(crash / "lib.dll"), b"DLL-v2")
    (crash / bds_update._UPDATE_MANIFEST_NAME).write_text(json.dumps({
        "staging": "data/bds_previous",
        "entries": [{"path": "bedrock_server.exe", "had_previous": True},
                    {"path": "lib.dll", "had_previous": True},
                    {"path": "nuevo.dll", "had_previous": False}],
    }), encoding="utf-8")
    _write(str(base / "nuevo.dll"), b"NUEVO-v1")  # aplicado sin original

    bds_update.recover_interrupted_updates(str(base))
    bds_update.recover_interrupted_updates(str(base))

    assert _read(str(base / "bedrock_server.exe")) == b"EXE-v2"
    assert _read(str(base / "lib.dll")) == b"DLL-v2"
    assert _read(str(base / "nuevo.dll")) is None
    assert _read(str(prev / "bedrock_server.exe")) == b"EXE-v1"
    assert _read(str(prev / "lib.dll")) == b"DLL-v1"
    assert _read(str(prev / "nuevo.dll")) == b"NUEVO-v1"
    assert not crash.exists()


@pytest.mark.parametrize("staging", ["../fuera", "C:/Windows", "data/a:b"])
def test_staging_inseguro_conserva_el_resguardo(tmp_path, staging):
    crash = tmp_path / "bds_update_prev_y"
    crash.mkdir()
    (crash / bds_update._UPDATE_MANIFEST_NAME).write_text(json.dumps({
        "staging": staging, "entries": [{"path": "x.dll", "had_previous": False}],
    }), encoding="utf-8")
    _write(str(tmp_path / "x.dll"), b"X")

    bds_update.recover_interrupted_updates(str(tmp_path))

    assert crash.exists()
    assert _read(str(tmp_path / "x.dll")) == b"X"


def test_la_actualizacion_normal_no_anota_staging(tmp_path, monkeypatch):
    base, staging = tmp_path / "base", tmp_path / "base" / "staging"
    _write(str(base / "a.dll"), b"old")
    _write(str(staging / "a.dll"), b"new")
    vistos = []
    real_replace = os.replace

    def _replace(src, dst):
        if str(dst).endswith(bds_update._UPDATE_MANIFEST_NAME):
            with open(src, encoding="utf-8") as f:
                vistos.append(json.load(f))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", _replace)
    bds_update._apply_staged_update(str(staging), str(base), set(), set())
    assert vistos and vistos[0]["staging"] is None


# ═══════════════════════════════════════════════════════════════════════
# 3. CLI de restore: re-chequeo y exclusión durante la operación
# ═══════════════════════════════════════════════════════════════════════
@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    world = tmp_path / "worlds" / "Mundo"
    backups = tmp_path / "backups"
    world.mkdir(parents=True)
    backups.mkdir()
    (world / "level.dat").write_bytes(b"VIEJO")
    with zipfile.ZipFile(backups / "auto_backup_test_ok.zip", "w") as zf:
        zf.writestr("level.dat", b"NUEVO")
    monkeypatch.setattr(restore_backup, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(restore_backup, "WORLD_DIR", str(world))
    monkeypatch.setattr(restore_backup, "BACKUP_DIR", str(backups))
    monkeypatch.setattr(restore_backup.os, "system", lambda *_a, **_k: 0)
    respuestas = iter(["1", "SI", ""])
    monkeypatch.setattr("builtins.input", lambda _p="": next(respuestas))
    llamadas = []
    monkeypatch.setattr(auto_backup, "recover_interrupted_restores", lambda *a, **k: llamadas.append("recover"))
    return tmp_path, world, llamadas


def test_cli_rechequea_tras_la_confirmacion(cli_env, monkeypatch):
    _base, world, llamadas = cli_env
    estados = iter([False, True])  # arranca mientras se escribe SI
    monkeypatch.setattr(restore_backup, "_server_is_running", lambda: next(estados))
    monkeypatch.setattr(restore_core, "restore_from_zip", lambda *a, **k: llamadas.append("restore"))

    restore_backup.list_and_restore()

    assert llamadas == []
    assert (world / "level.dat").read_bytes() == b"VIEJO"


def test_cli_rechaza_si_otro_proceso_opera(cli_env, monkeypatch):
    base, world, llamadas = cli_env
    monkeypatch.setattr(restore_backup, "_server_is_running", lambda: False)
    monkeypatch.setattr(restore_core, "restore_from_zip", lambda *a, **k: llamadas.append("restore"))

    with _otro_proceso_opera(base):
        restore_backup.list_and_restore()

    assert llamadas == []
    assert (world / "level.dat").read_bytes() == b"VIEJO"


def test_cli_retiene_la_exclusion_durante_el_restore(cli_env, monkeypatch):
    base, _world, llamadas = cli_env
    monkeypatch.setattr(restore_backup, "_server_is_running", lambda: False)
    vista_desde_fuera = []

    def _restaurar(*_a, **_k):
        hilo = threading.Thread(target=lambda: vista_desde_fuera.append(
            wpg.mutex_held_by_other(wpg.installation_ops_mutex_name(str(base)))))
        hilo.start()
        hilo.join(5)
        llamadas.append("restore")

    monkeypatch.setattr(restore_core, "restore_from_zip", _restaurar)
    restore_backup.list_and_restore()

    assert llamadas == ["recover", "restore"]
    assert vista_desde_fuera == [True]


# ═══════════════════════════════════════════════════════════════════════
# 4. Junctions en la raíz de los packs
# ═══════════════════════════════════════════════════════════════════════
def _junction(link, target):
    import _winapi
    _winapi.CreateJunction(str(target), str(link))


@pytest.fixture
def raiz_de_packs_redirigida(tmp_path):
    if os.name != "nt":
        pytest.skip("junctions de Windows")
    base = tmp_path / "base"
    externo = tmp_path / "externo"
    (base / "worlds" / "Mundo").mkdir(parents=True)
    (base / "worlds" / "Mundo" / "level.dat").write_bytes(b"VIEJO")
    _write(str(externo / "addon" / "manifest.json"), b"VIEJO")
    _write(str(externo / "addon" / "personal.txt"), b"MIO")
    _junction(base / "resource_packs", externo)
    try:
        yield base, externo
    finally:
        os.rmdir(base / "resource_packs")  # quita la junction, no su destino


def test_is_redirected_path(raiz_de_packs_redirigida, tmp_path):
    base, _externo = raiz_de_packs_redirigida
    assert zip_safety.is_redirected_path(str(base), str(base / "resource_packs")) is True
    assert zip_safety.is_redirected_path(str(base), str(base / "resource_packs" / "addon")) is True
    assert zip_safety.is_redirected_path(str(base), str(base / "behavior_packs" / "addon")) is False
    assert zip_safety.is_redirected_path(str(base), str(base / "worlds" / "Mundo")) is False


def test_restore_no_escribe_fuera_por_una_junction(raiz_de_packs_redirigida, tmp_path):
    base, externo = raiz_de_packs_redirigida
    zip_path = tmp_path / "auto_backup_x.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("level.dat", b"NUEVO")
        zf.writestr("server_resource_packs/addon/manifest.json", b"DEL BACKUP")
        zf.writestr("server_behavior_packs/mod/manifest.json", b"MOD")
    logs = []

    restore_core.restore_from_zip(str(zip_path), str(base), str(base / "worlds" / "Mundo"), log_fn=logs.append)

    assert (base / "worlds" / "Mundo" / "level.dat").read_bytes() == b"NUEVO"
    assert (externo / "addon" / "manifest.json").read_bytes() == b"VIEJO"
    assert (externo / "addon" / "personal.txt").read_bytes() == b"MIO"
    assert (base / "behavior_packs" / "mod" / "manifest.json").read_bytes() == b"MOD"
    assert sorted(os.listdir(externo)) == ["addon"]
    assert any("resource_packs/addon" in m for m in logs)


def test_backup_no_incluye_una_raiz_de_packs_redirigida(raiz_de_packs_redirigida, monkeypatch, tmp_path):
    base, _externo = raiz_de_packs_redirigida
    _write(str(base / "behavior_packs" / "mod" / "manifest.json"), b"MOD")
    monkeypatch.setattr(auto_backup, "BASE_DIR", str(base))
    with zipfile.ZipFile(tmp_path / "b.zip", "w") as zf:
        auto_backup._write_server_packs(zf, 0, None)
        nombres = zf.namelist()
    assert nombres == ["server_behavior_packs/mod/manifest.json"]


def test_recovery_no_borra_dentro_de_una_raiz_redirigida(raiz_de_packs_redirigida):
    base, externo = raiz_de_packs_redirigida
    ajeno = externo / "algo.restore_staging_0123abcd"
    ajeno.mkdir()
    auto_backup.recover_interrupted_restores(str(base))
    assert ajeno.exists()


# ═══════════════════════════════════════════════════════════════════════
# 5. ZIP64 en el backup en caliente
# ═══════════════════════════════════════════════════════════════════════
def test_backup_en_caliente_con_archivos_mayores_que_zip64_limit(tmp_path, monkeypatch):
    base = tmp_path / "base"
    world = base / "worlds" / "Bedrock level"
    _write(str(world / "level.dat"), b"W" * 100)
    _write(str(world / "db" / "CURRENT"), b"MANIFEST-000001\n")
    _write(str(world / "db" / "000005.ldb"), b"L" * 5000)
    backups = tmp_path / "backups"
    backups.mkdir()
    monkeypatch.setattr(auto_backup, "BASE_DIR", str(base))
    monkeypatch.setattr(auto_backup, "WORLD_DIR", str(world))
    monkeypatch.setattr(auto_backup, "BACKUP_DIR", str(backups))
    # Mismo límite reducido que la reproducción: 1000 bytes en vez de 2 GiB.
    monkeypatch.setattr(zipfile, "ZIP64_LIMIT", 1000)

    resultado = auto_backup.create_backup("test", file_snapshot=[
        ("level.dat", 100), ("db/CURRENT", 16), ("db/000005.ldb", 5000)])

    assert resultado
    with zipfile.ZipFile(resultado) as zf:
        assert zf.read("db/000005.ldb") == b"L" * 5000
        assert zf.testzip() is None


# ═══════════════════════════════════════════════════════════════════════
# 6. Guardado parcial de la programación
# ═══════════════════════════════════════════════════════════════════════
def test_guardar_una_clave_conserva_las_demas(tmp_path, monkeypatch):
    monkeypatch.setattr(schedule_config, "SCHEDULE_PATH", str(tmp_path / "schedule_config.json"))
    ok, _cfg, _ = schedule_config.save({
        "backup_interval_min": 30, "backup_only_with_players": False,
        "daily_backup_time": "04:00", "auto_restart_on_crash": True, "daily_restart_time": "05:30",
    })
    assert ok

    ok, cfg, detalle = schedule_config.save({"backup_interval_min": 15})

    assert ok, detalle
    assert cfg == {
        "backup_interval_min": 15, "backup_only_with_players": False,
        "daily_backup_time": "04:00", "auto_restart_on_crash": True, "daily_restart_time": "05:30",
    }
    assert schedule_config.load() == cfg


def test_guardado_parcial_invalido_no_escribe(tmp_path, monkeypatch):
    ruta = tmp_path / "schedule_config.json"
    monkeypatch.setattr(schedule_config, "SCHEDULE_PATH", str(ruta))
    assert schedule_config.save({"auto_restart_on_crash": True})[0]
    antes = ruta.read_bytes()

    assert schedule_config.save({"backup_interval_min": 1})[0] is False
    assert schedule_config.save(["no", "es", "objeto"])[0] is False
    assert ruta.read_bytes() == antes


def test_sin_archivo_las_claves_omitidas_toman_el_default(tmp_path, monkeypatch):
    monkeypatch.setattr(schedule_config, "SCHEDULE_PATH", str(tmp_path / "schedule_config.json"))
    ok, cfg, _ = schedule_config.save({"daily_backup_time": "03:00"})
    assert ok
    assert cfg == {**schedule_config.DEFAULTS, "daily_backup_time": "03:00"}


# ═══════════════════════════════════════════════════════════════════════
# 7. Fase 1: el flag del backup inicial se observa durante la espera
# ═══════════════════════════════════════════════════════════════════════
@pytest.fixture
def fase1(monkeypatch):
    evento = threading.Event()
    monkeypatch.setattr(manager, "server_stopped_event", evento)
    monkeypatch.setattr(manager, "is_running", True)
    monkeypatch.setattr(manager, "wrapper_pre_bds", False)
    monkeypatch.setattr(manager, "events_alive", False)
    monkeypatch.setattr(config, "SERVER_STOP_TIMEOUT_SEC", 0.3)
    monkeypatch.setattr(lifecycle, "_PRE_BDS_POLL_SEC", 0.05)
    return evento


def test_fase1_ve_el_backup_inicial_aunque_wrapper_started_llegue_tarde(fase1):
    def wrapper():
        time.sleep(0.1)  # el stop se pidió antes de leer wrapper_started
        supervisor._apply_event({"event": "wrapper_started", "pid": 1, "initial_backup": True})
        time.sleep(0.6)  # backup inicial más largo que el plazo de 0.3 s
        supervisor._apply_event({"event": "bds_launched", "pid": 2})
        time.sleep(0.1)
        fase1.set()

    hilo = threading.Thread(target=wrapper, daemon=True)
    hilo.start()
    detenido, esperado = lifecycle._wait_server_stopped()
    hilo.join(5)

    assert detenido is True
    assert esperado >= 0.7


def test_fase1_sin_backup_inicial_conserva_el_plazo(fase1):
    supervisor._apply_event({"event": "wrapper_started", "pid": 1, "initial_backup": False})
    inicio = time.monotonic()
    detenido, _ = lifecycle._wait_server_stopped()
    assert detenido is False
    assert 0.25 <= time.monotonic() - inicio < 1.0


def test_fase1_sin_canal_de_eventos_conserva_el_plazo(fase1):
    """Un wrapper sin eventos (events_alive nunca llega) espera lo de siempre."""
    inicio = time.monotonic()
    detenido, _ = lifecycle._wait_server_stopped()
    assert detenido is False
    assert 0.25 <= time.monotonic() - inicio < 1.0


@pytest.mark.parametrize("pre_bds,margen,total", [(False, 0, 75), (True, 10, 85)])
def test_fase1_descuenta_el_plazo_por_espera_no_por_reloj(monkeypatch, pre_bds, margen, total):
    """Un wait que vuelve al instante agota el plazo sin girar 75 s de reloj."""
    monkeypatch.setattr(manager, "is_running", True)
    monkeypatch.setattr(manager, "wrapper_pre_bds", pre_bds)
    monkeypatch.setattr(manager, "events_alive", False)
    monkeypatch.setattr(config, "SERVER_STOP_TIMEOUT_SEC", 75)
    monkeypatch.setattr(lifecycle, "_pre_bds_allowance_sec", lambda: margen)
    esperas = []
    monkeypatch.setattr(manager.server_stopped_event, "wait",
                        lambda timeout=None: esperas.append(timeout) or False)
    inicio = time.monotonic()

    assert lifecycle._wait_server_stopped()[0] is False
    assert time.monotonic() - inicio < 2
    assert sum(esperas) == pytest.approx(total)


def test_wrapper_started_fija_el_flag_antes_de_events_alive():
    with open(os.path.join(BASE_DIR, "gui_backend", "supervisor.py"), encoding="utf-8") as f:
        fuente = f.read()
    bloque = fuente[fuente.index('if event == "wrapper_started":'):]
    bloque = bloque[:bloque.index("elif event")]
    assert bloque.index("manager.wrapper_pre_bds =") < bloque.index("manager.events_alive = True")


# ═══════════════════════════════════════════════════════════════════════
# 8. iniciar_servidor.bat con el runtime del ZIP
# ═══════════════════════════════════════════════════════════════════════
def test_lanzador_del_zip_pasa_por_el_primer_arranque():
    with open(os.path.join(BASE_DIR, "iniciar_servidor.bat"), encoding="utf-8") as f:
        bat = f.read()
    rama = bat[bat.index('if exist "%~dp0runtime\\python.exe" ('):]
    rama = rama[:rama.index(")")]
    assert "server_wrapper.py" not in rama
    assert "goto :first_run" in rama
    assert 'set "RUN_PY=%~dp0runtime\\python.exe"' in rama

    etiqueta = bat.index("\n:first_run")
    primer_arranque = bat.index('"%RUN_PY%" %PY_FLAGS% tools\\bds_first_run.py')
    wrapper = bat.index('"%RUN_PY%" %PY_FLAGS% server_wrapper.py')
    assert etiqueta < primer_arranque < wrapper
    entre = bat[primer_arranque:wrapper]
    assert "if errorlevel 2" in entre and "if errorlevel 1" in entre
    # El idioma por defecto se fija antes de la rama del runtime.
    assert bat.index('set "WRAPPER_LANG=es"') < bat.index('if exist "%~dp0runtime\\python.exe" (')


def _echos_con_parentesis_en_bloques(texto):
    """Lineas `echo` dentro de un bloque ( ... ) con un ')' sin escapar.

    cmd analiza el bloque entero antes de ejecutarlo: ese ')' lo cierra antes
    de tiempo. En iniciar_servidor.bat abortaba con "No se esperaba . en este
    momento." tras el primer arranque, sin lanzar nunca el wrapper (desde el
    2026-08-16); en iniciar_gui_lan.bat el aviso de fallo del firewall salia
    siempre.
    """
    malas, nivel = [], 0
    for numero, linea in enumerate(texto.splitlines(), 1):
        limpia = linea.strip()
        if limpia.lower().startswith(("::", "rem ")):
            continue
        if limpia.startswith(")"):
            nivel = max(0, nivel - 1)
        if nivel and limpia.lower().startswith("echo") and re.search(r"(?<!\^)\)", limpia):
            malas.append((numero, limpia))
        if limpia.endswith("("):
            nivel += 1
    return malas


@pytest.mark.parametrize("nombre", sorted(
    os.path.basename(p) for p in glob.glob(os.path.join(BASE_DIR, "*.bat"))))
def test_bat_sin_parentesis_sin_escapar_en_bloques(nombre):
    with open(os.path.join(BASE_DIR, nombre), encoding="utf-8", errors="replace") as f:
        assert _echos_con_parentesis_en_bloques(f.read()) == []


def test_detector_de_parentesis_ve_el_fallo_original():
    bloque = 'if errorlevel 2 (\n    echo [INFO] cancelada (sin respuesta o "no"). Vuelve\n)\n'
    assert _echos_con_parentesis_en_bloques(bloque) == [
        (2, 'echo [INFO] cancelada (sin respuesta o "no"). Vuelve')]
    escapado = bloque.replace("(sin", "^(sin").replace('"no")', '"no"^)')
    assert _echos_con_parentesis_en_bloques(escapado) == []
