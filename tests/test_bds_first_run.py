# -*- coding: utf-8 -*-
"""Tests del primer arranque por consola (tools/bds_first_run.py).

Cubren:
- Con bedrock_server.exe presente: no pregunta ni descarga (exit 0).
- Sin exe: [S/n] con Enter = Si, "n" cancela (exit 2) sin descargar.
- Descarga con fallo operativo: exit 1.
- Copia de server.properties.example cuando falta.
- _download_and_install_bds respeta el log_fn inyectado.
- iniciar_servidor.bat ejecuta el script antes del wrapper.
"""
import importlib.util
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gui_backend.config as config
import gui_backend.services.bds_update as bds_update

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_first_run():
    spec = importlib.util.spec_from_file_location(
        "bds_first_run", os.path.join(BASE_DIR, "tools", "bds_first_run.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fake_paths(monkeypatch, tmp_path):
    """SERVER_EXE/PROPS_PATH falsos dentro de tmp_path."""
    base = str(tmp_path)
    monkeypatch.setattr(config, "SERVER_EXE", os.path.join(base, "bedrock_server.exe"))
    monkeypatch.setattr(config, "PROPS_PATH", os.path.join(base, "server.properties"))
    monkeypatch.setattr(config, "BASE_DIR", base)
    return base


def test_con_exe_no_pregunta(monkeypatch, tmp_path):
    base = _fake_paths(monkeypatch, tmp_path)
    with open(config.SERVER_EXE, "wb") as f:
        f.write(b"fake")
    mod = _load_first_run()

    def fail_input(_prompt):
        raise AssertionError("no debe preguntar si el exe existe")

    monkeypatch.setattr("builtins.input", fail_input)
    assert mod.main() == 0


def test_sin_exe_responde_no(monkeypatch, tmp_path):
    _fake_paths(monkeypatch, tmp_path)
    mod = _load_first_run()
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    called = {"n": 0}
    monkeypatch.setattr(
        bds_update, "_download_and_install_bds",
        lambda *a, **k: called.__setitem__("n", called["n"] + 1) or (True, "1.0.0.0"),
    )
    assert mod.main() == 2
    assert called["n"] == 0


@pytest.mark.parametrize("respuesta", ["", "S", "si", "YES"])
def test_sin_exe_enter_o_si_descarga(monkeypatch, tmp_path, respuesta):
    base = _fake_paths(monkeypatch, tmp_path)
    mod = _load_first_run()
    monkeypatch.setattr("builtins.input", lambda _prompt: respuesta)
    llamadas = {"n": 0}
    monkeypatch.setattr(
        bds_update, "_download_and_install_bds",
        lambda *a, **k: llamadas.__setitem__("n", llamadas["n"] + 1) or (True, "1.26.43.1"),
    )
    assert mod.main() == 0
    assert llamadas["n"] == 1


def test_descarga_falla_operativo(monkeypatch, tmp_path):
    _fake_paths(monkeypatch, tmp_path)
    mod = _load_first_run()
    monkeypatch.setattr("builtins.input", lambda _prompt: "s")
    monkeypatch.setattr(bds_update, "_download_and_install_bds", lambda *a, **k: (False, None))
    assert mod.main() == 1


def test_copia_properties_si_faltan(monkeypatch, tmp_path):
    base = _fake_paths(monkeypatch, tmp_path)
    example = os.path.join(base, "server.properties.example")
    with open(example, "w", encoding="utf-8") as f:
        f.write("server-name=Test\n")
    mod = _load_first_run()
    monkeypatch.setattr(bds_update, "_download_and_install_bds", lambda *a, **k: (True, "1.0.0.0"))
    monkeypatch.setattr("builtins.input", lambda _prompt: "s")
    assert mod.main() == 0
    assert os.path.exists(config.PROPS_PATH)
    with open(config.PROPS_PATH, encoding="utf-8") as f:
        assert "server-name=Test" in f.read()


def test_log_fn_inyectado_recibe_mensajes(monkeypatch):
    """_download_and_install_bds sin red: el fallo viaja al log_fn, no a la GUI."""
    mensajes = []
    monkeypatch.setattr(bds_update, "_fetch_latest_bedrock_download", lambda: (None, None))
    ok, version = bds_update._download_and_install_bds(
        tag="[Test]", log_fn=lambda msg, _t=None: mensajes.append(msg)
    )
    assert ok is False and version is None
    assert any(
        "No se pudo obtener la URL" in m or "official download URL" in m
        for m in mensajes
    )


def test_bat_referencia_script(monkeypatch):
    bat_path = os.path.join(BASE_DIR, "iniciar_servidor.bat")
    assert os.path.isfile(bat_path), "Falta iniciar_servidor.bat"
    with open(bat_path, encoding="utf-8") as f:
        contenido = f.read()
    assert "tools\\bds_first_run.py" in contenido
    assert "server_wrapper.py" in contenido
