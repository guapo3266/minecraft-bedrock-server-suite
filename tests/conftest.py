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
