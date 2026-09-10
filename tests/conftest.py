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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui_backend.services import history
import wrapper_events


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
