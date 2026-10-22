# -*- coding: utf-8 -*-
"""Aislamiento de datos reales para TODA la suite.

`data/gui_history.db` es dato de la instalación, no del repo: ningún test
debe escribirlo. El fixture autouse redirige DB_PATH a tmp en cada test;
los fixtures propios que ya parchean DB_PATH (p. ej. hist_env) corren
después y ganan.

Lo mismo aplica al canal NDJSON del wrapper: los tests que ejercitan rutas
del lado wrapper (`read_stdout`, `execute_backup_worker`, ...) disparan
`_emit_event`; sin aislamiento cada corrida de la suite escribía
`be_*.ndjson` en el `data/wrapper_events/` REAL de la instalación.

stop_for_tests() antes y después descarta la conexion cacheada: sin eso,
un start() de un test anterior dejaria viva una conexion a la DB real y
los sinks seguirian escribiendo ahi aunque DB_PATH ya apuntara a tmp.
"""
import os
import sys

import pytest
from hypothesis import settings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui_backend.services import history
import wrapper_events

# Perfil global de Hypothesis sin deadline (2026-10-19): muchas propiedades
# tocan disco y la primera E/S en frio (antivirus/NTFS) superaba los 200 ms
# por defecto -> DeadlineExceeded/FlakyFailure intermitentes en tests sanos
# (test_rotate_old_survivors_bounded_by_recent_layer, test_read_value_*).
# Los @settings de cada test siguen fijando max_examples.
settings.register_profile("suite", deadline=None)
settings.load_profile("suite")


@pytest.fixture(autouse=True)
def _db_historial_en_tmp(tmp_path, monkeypatch):
    history.stop_for_tests()
    monkeypatch.setattr(history, "DB_PATH", os.path.join(str(tmp_path), "gui_history.db"))
    yield
    history.stop_for_tests()


@pytest.fixture(autouse=True)
def _eventos_wrapper_en_tmp(tmp_path, monkeypatch):
    """Canal de eventos NDJSON del wrapper aislado en tmp (dato real intacto).

    Los fixtures propios que ya fijan WRAPPER_EVENTS_FILE (p. ej. events_env
    de test_ipc_events) corren después y ganan. El reset del handle cierra
    cualquier archivo quedado abierto por el test anterior: el handle es
    global a wrapper_events y sin esto un fallo podria dejarlo apuntando a
    un tmp ya borrado.
    """
    monkeypatch.setenv(
        "WRAPPER_EVENTS_FILE", os.path.join(str(tmp_path), "ev.ndjson")
    )
    wrapper_events._reset_events_for_tests()
    yield
    wrapper_events._reset_events_for_tests()


@pytest.fixture(autouse=True)
def _estado_diario_del_wrapper_en_tmp(tmp_path, monkeypatch):
    """El backup diario del wrapper se anota en data/schedule_state_wrapper.json.

    El watchdog de la GUI lo lee para no repetir en frio el backup diario que
    el wrapper ya hizo en caliente (2026-10-20): ningun test debe leer ni
    escribir el estado real. Los tests que fijan su propia ruta
    (test_wrapper_schedule_unit) corren despues y ganan.
    """
    import wrapper_schedule

    monkeypatch.setattr(
        wrapper_schedule, "SCHEDULE_STATE_PATH",
        os.path.join(str(tmp_path), "schedule_state_wrapper.json"),
    )
    yield


@pytest.fixture(autouse=True, scope="session")
def _watchdog_de_fondo_desactivado():
    """Desactiva el loop de fondo del watchdog durante TODA la suite (F1).

    El watchdog de la GUI es un hilo daemon que arranca con el lifespan del
    primer TestClient y sobrevive a los monkeypatches de cada test. Si un test
    deja temporalmente un config con `auto_restart_on_crash` (o `daily_*_time`)
    y el estado del manager queda en "wrapper ausente y salida no solicitada",
    el hilo lanza wrappers REALES contra la instalacion: backups reales, BDS
    real, mutex del wrapper retenido (409 en otros tests) y mutex de backup
    ocupado (fallos falsos del worker). Los tests ejercitan `_watchdog_tick` y
    sus helpers directamente; el loop de fondo solo hace falta en produccion.
    """
    from gui_backend.services import watchdog

    original_start = watchdog.start
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(watchdog, "start", lambda: None)
        # Seam para tests que necesitan ejercitar la implementacion real (p. ej.
        # idempotencia del arranque) sin reactivar el loop de fondo de la suite.
        mp.setattr(watchdog, "_start_real", original_start, raising=False)
        yield


@pytest.fixture(autouse=True, scope="session")
def _espera_del_wrapper_no_depende_del_mundo_real():
    """La espera de fase 2 de la GUI escala con el tamano del mundo.

    `lifecycle.wrapper_exit_timeout_sec` suma al piso de config lo que el mundo
    anade al cierre del wrapper. Los tests de restart/stop_and_wait fijan el
    piso en fracciones de segundo; si midieran el `worlds/` REAL de la
    instalacion (puede pesar GB), la espera efectiva seria de minutos y la suite
    dependeria de la maquina. Aqui el tamano es 0; los tests de la escala
    parchean `lifecycle._estimate_world_bytes` con su propio valor.
    """
    from gui_backend.services import lifecycle

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(lifecycle, "_estimate_world_bytes", lambda: 0)
        yield


@pytest.fixture(autouse=True, scope="session")
def _host_header_de_tests_permitido():
    """El TestClient de Starlette manda `Host: testserver`; el guard anti
    DNS-rebinding (S1b, 2026-09-25) rechaza hostnames que no son loopback/
    IP privada, asi que la suite lo habilita explicitamente. En produccion
    GUI_ALLOWED_HOSTS no se define y el guard solo admite loopback (o IP
    privada con GUI_ALLOW_LAN=1)."""
    os.environ["GUI_ALLOWED_HOSTS"] = "testserver"
    yield
    os.environ.pop("GUI_ALLOWED_HOSTS", None)


@pytest.fixture(autouse=True, scope="session")
def _recuperaciones_no_tocan_la_instalacion_real():
    """Los lifespans de TestClient no recuperan residuos de la instalacion real.

    `server_gui_server.lifespan` llama en cada TestClient a
    `auto_backup.recover_interrupted_restores(BASE_DIR)` y
    `bds_update.recover_interrupted_updates()` sobre la carpeta REAL. Hoy son
    no-ops (no hay staging/`.bak_*`), pero si el usuario tuviera una
    restauracion o actualizacion interrumpida de verdad, correr la suite
    podria consumirla. El guard solo bloquea las llamadas cuyo `base_dir`
    apunta a la instalacion real; los tests que llaman con `tmp_path`
    (test_backup_fixes) siguen ejercitando la implementacion real.
    """
    import auto_backup
    import gui_backend.services.bds_update as bds_update
    from gui_backend import config

    real = os.path.normcase(os.path.abspath(config.BASE_DIR))
    orig_restores = auto_backup.recover_interrupted_restores
    orig_updates = bds_update.recover_interrupted_updates

    def _es_instalacion_real(base_dir):
        return os.path.normcase(os.path.abspath(base_dir)) == real

    def guarded_restores(base_dir=None):
        bd = base_dir if base_dir is not None else auto_backup.BASE_DIR
        if _es_instalacion_real(bd):
            return []
        return orig_restores(base_dir)

    def guarded_updates(base_dir=None):
        bd = base_dir if base_dir is not None else bds_update.config.BASE_DIR
        if _es_instalacion_real(bd):
            return
        return orig_updates(base_dir)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(auto_backup, "recover_interrupted_restores", guarded_restores)
        mp.setattr(bds_update, "recover_interrupted_updates", guarded_updates)
        yield


@pytest.fixture(autouse=True, scope="session")
def _identidad_y_config_bds_no_tocan_la_instalacion_real():
    """data/installation_id.json, el dueño de la carpeta de backups y el
    registro de configuración de fábrica de BDS (2026-10-21) son datos reales.

    Los tests con `tmp_path` siguen ejercitando las escrituras; las que irían a
    la instalación real o a su carpeta de backups predeterminada se descartan.
    """
    from gui_backend import backup_location, config
    from gui_backend.services import bds_update

    real = os.path.normcase(os.path.abspath(config.BASE_DIR))
    raiz_real = os.path.normcase(backup_location.default_root(config.BASE_DIR))

    def _es_real(path):
        p = os.path.normcase(os.path.abspath(path))
        return p == real or p.startswith(real + os.sep) or p.startswith(raiz_real + os.sep)

    orig_write = backup_location._write_dict

    def guarded_write(path, data):
        if _es_real(path):
            return False
        return orig_write(path, data)

    def _guard(fn):
        def wrapper(base_dir, *args, **kwargs):
            if _es_real(base_dir):
                return None
            return fn(base_dir, *args, **kwargs)
        return wrapper

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(backup_location, "_write_dict", guarded_write)
        for name in ("record_shipped_config", "forget_shipped_config", "save_config_defaults"):
            mp.setattr(bds_update, name, _guard(getattr(bds_update, name)))
        yield


@pytest.fixture(autouse=True, scope="session")
def _version_anterior_de_bds_no_toca_la_instalacion_real():
    """data/bds_previous (la version de BDS a la que se revierte) es dato real.

    `bds_update.PREVIOUS_VERSION_DIR` se calcula al importar desde la instalacion
    real: un test que parchea `config.BASE_DIR` pero no esa constante movia su
    resguardo a la carpeta real y apartaba la version anterior verdadera
    (test_setup_initial, hallado el 2026-10-21). Aqui falla en voz alta en vez
    de escribir: el test debe parchear PREVIOUS_VERSION_DIR.
    """
    from gui_backend import config
    from gui_backend.services import bds_update

    real = os.path.normcase(os.path.abspath(config.BASE_DIR))
    orig_save = bds_update._save_prev_dir

    def guarded_save(prev_dir, keep_prev_dir, prev_version):
        destino = os.path.normcase(os.path.abspath(keep_prev_dir))
        if destino == real or destino.startswith(real + os.sep):
            pytest.fail(f"un test iba a escribir la version anterior de BDS en la instalacion real: {keep_prev_dir}")
        return orig_save(prev_dir, keep_prev_dir, prev_version)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(bds_update, "_save_prev_dir", guarded_save)
        yield


@pytest.fixture(autouse=True, scope="session")
def _registro_de_packs_bds_no_toca_la_instalacion_real():
    """El registro de packs de BDS (data/bds_shipped_packs.json) es dato real.

    Algunos tests recorren el pipeline de actualizacion con `config.BASE_DIR`
    real y el apply simulado (test_review_hallazgos): sin este guard, el
    registro se escribia en la instalacion con las carpetas del ZIP falso. Los
    tests con `tmp_path` siguen ejercitando la escritura real.
    """
    import zip_safety
    from gui_backend import config

    real = os.path.normcase(os.path.abspath(config.BASE_DIR))
    orig_record = zip_safety.record_bds_shipped_packs

    def guarded_record(base_dir, packs):
        if os.path.normcase(os.path.abspath(base_dir)) == real:
            return None
        return orig_record(base_dir, packs)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(zip_safety, "record_bds_shipped_packs", guarded_record)
        yield
