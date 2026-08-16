# -*- coding: utf-8 -*-
"""Aislamiento de datos reales para TODA la suite.

`data/gui_history.db` es dato de la instalación, no del repo: ningún test
debe escribirlo. El fixture autouse redirige DB_PATH a tmp en cada test;
los fixtures propios que ya parchean DB_PATH (p. ej. hist_env) corren
después y ganan.

stop_for_tests() antes y después descarta la conexion cacheada: sin eso,
un start() de un test anterior dejaria viva una conexion a la DB real y
los sinks seguirian escribiendo ahi aunque DB_PATH ya apuntara a tmp.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui_backend.services import history


@pytest.fixture(autouse=True)
def _db_historial_en_tmp(tmp_path, monkeypatch):
    history.stop_for_tests()
    monkeypatch.setattr(history, "DB_PATH", os.path.join(str(tmp_path), "gui_history.db"))
    yield
    history.stop_for_tests()
