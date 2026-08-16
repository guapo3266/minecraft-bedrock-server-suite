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
