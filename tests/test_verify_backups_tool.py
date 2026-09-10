# -*- coding: utf-8 -*-
"""tests del verificador batch de backups (tools/verify_backups.py)."""

import importlib.util
import os
import zipfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_tool():
    spec = importlib.util.spec_from_file_location(
        "verify_backups_tool", os.path.join(BASE_DIR, "tools", "verify_backups.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _zip_bueno(path):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("level.dat", b"X" * 64)


def test_verify_all_marca_corruptos_y_salta_ya_marcados(tmp_path):
    mod = _load_tool()
    bueno = tmp_path / "auto_backup_ok.zip"
    _zip_bueno(bueno)
    roto = tmp_path / "auto_backup_roto.zip"
    roto.write_bytes(b"esto no es un zip")
    marcado = tmp_path / "auto_backup_viejo_CORRUPTO.zip"
    marcado.write_bytes(b"esto no es un zip")

    ok, corruptos = mod.verify_all(str(tmp_path))

    assert (ok, corruptos) == (1, 1)
    assert bueno.exists()
    assert not roto.exists()
    assert (tmp_path / "auto_backup_roto_CORRUPTO.zip").exists()
    assert marcado.exists(), "un backup ya marcado no debe re-procesarse"


def test_verify_all_detecta_crc_roto(tmp_path):
    mod = _load_tool()
    path = tmp_path / "auto_backup_crc.zip"
    _zip_bueno(path)
    with open(path, "r+b") as f:
        f.seek(-8, 2)
        f.write(b"\x00\x00\x00\x00")

    ok, corruptos = mod.verify_all(str(tmp_path))

    assert (ok, corruptos) == (0, 1)
    assert (tmp_path / "auto_backup_crc_CORRUPTO.zip").exists()


def test_main_directorio_inexistente_exit_0(tmp_path):
    mod = _load_tool()
    assert mod.main([str(tmp_path / "no_existe")]) == 0


def test_main_con_corrupto_exit_1(tmp_path):
    mod = _load_tool()
    (tmp_path / "auto_backup_x.zip").write_bytes(b"no zip")
    assert mod.main([str(tmp_path)]) == 1
