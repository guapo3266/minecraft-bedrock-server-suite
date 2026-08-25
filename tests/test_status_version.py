# -*- coding: utf-8 -*-
"""El payload de status expone la version de BDS instalada.

`installed_version` la llena el supervisor via evento NDJSON
`version_captured` (fallback stdout); build_public_status debe publicarla
tal cual (None mientras no haya arranque del wrapper).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server_gui_server as gui
from gui_backend.state import build_public_status


@pytest.fixture
def version_env():
    prev = gui.manager.installed_version
    gui.manager.installed_version = None
    yield gui.manager
    gui.manager.installed_version = prev


def test_status_sin_arranque_version_none(version_env):
    assert build_public_status(gui.manager)["installed_version"] is None


def test_status_publica_version_capturada(version_env):
    gui.manager.installed_version = "1.26.43.1"
    assert build_public_status(gui.manager)["installed_version"] == "1.26.43.1"


def test_fallback_stdout_usa_el_mismo_patron_version_del_wrapper():
    """Anti-drift (D5): la captura de version por stdout en la GUI (fallback
    sin canal NDJSON) usa el MISMO patron compilado que el wrapper
    (`_RE_VERSION`, fuente unica). Antes la GUI tenia una copia literal del
    regex: si Mojang cambiaba el formato y se actualizaba una sola copia,
    wrapper y GUI divergian en silencio (installed_version None o stale)."""
    import server_wrapper as sw
    from gui_backend import supervisor

    assert supervisor._RE_VERSION is sw._RE_VERSION
    m = supervisor._RE_VERSION.search("Version: 1.26.33.2")
    assert m is not None and m.group(1) == "1.26.33.2"
