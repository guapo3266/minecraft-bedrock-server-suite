# -*- coding: utf-8 -*-
"""Lector tolerante de server.properties y su integracion en los parsers."""

import auto_backup as ab
import restore_backup as rb
import server_properties as sp
import server_wrapper as sw
import wrapper_state as wstate
from gui_backend import config
from gui_backend.services import players as players_service


def test_read_value_tolera_espacios_comentarios_y_mayusculas(tmp_path):
    props = tmp_path / "server.properties"
    props.write_text(
        "# comentario\n"
        "level-name = Mundo Con Espacios\n"
        "allow-list=true\n"
        "; otro comentario\n"
        "SERVER-PORT=19132\n",
        encoding="utf-8",
    )

    assert sp.read_value(str(props), "level-name") == "Mundo Con Espacios"
    assert sp.read_value(str(props), "level-NAME") == "Mundo Con Espacios"
    assert sp.read_value(str(props), "allow-list") == "true"
    assert sp.read_value(str(props), "server-port") == "19132"
    assert sp.read_value(str(props), "no-existe") is None
    assert sp.read_value(str(props), "no-existe", "defecto") == "defecto"


def test_read_value_archivo_inexistente(tmp_path):
    assert sp.read_value(str(tmp_path / "no.properties"), "x", "defecto") == "defecto"


def test_get_world_name_con_espacios(tmp_path):
    (tmp_path / "server.properties").write_text("level-name = MundoX\n", encoding="utf-8")

    assert ab.get_world_name(str(tmp_path)) == "MundoX"
    assert rb._world_name(str(tmp_path)) == "MundoX"


def test_should_run_initial_backup_con_espacios(tmp_path, monkeypatch):
    (tmp_path / "server.properties").write_text("backup-inicio = false\n", encoding="utf-8")
    monkeypatch.setattr(wstate, "BASE_DIR", str(tmp_path))

    assert sw.should_run_initial_backup() is False


def test_allow_list_enabled_con_espacios(tmp_path, monkeypatch):
    props = tmp_path / "server.properties"
    props.write_text("allow-list = true\n", encoding="utf-8")
    monkeypatch.setattr(config, "PROPS_PATH", str(props))

    assert players_service._allow_list_enabled() is True
