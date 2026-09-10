# -*- coding: utf-8 -*-
"""Guard de symlinks/junctions de `auto_backup._resolve_snapshot_path`.

Un enlace dentro del mundo que apunta FUERA debe rechazarse (segundo chequeo
con realpath); uno que apunta dentro es valido. En Windows sin privilegios de
symlink se usa una junction de directorio (`mklink /J`), que no los requiere.
"""
import os
import subprocess

import pytest

import auto_backup as ab


def _crear_enlace(link, target):
    try:
        os.symlink(str(target), str(link), target_is_directory=os.path.isdir(target))
        return
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt" and os.path.isdir(target):
        r = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            return
    pytest.skip("el sistema no permite crear enlaces")


@pytest.fixture
def mundo_parcheado(tmp_path, monkeypatch):
    def _preparar(mundo):
        monkeypatch.setattr(ab, "WORLD_DIR", str(mundo))
        monkeypatch.setattr(ab, "WORLD_PARENT_DIR", str(tmp_path / "worlds"))
        return mundo
    return _preparar


def test_enlace_que_escapa_del_mundo_es_rechazado(tmp_path, mundo_parcheado):
    mundo = tmp_path / "worlds" / "Bedrock level"
    mundo.mkdir(parents=True)
    (mundo / "level.dat").write_bytes(b"X")
    fuera = tmp_path / "fuera"
    fuera.mkdir()
    (fuera / "secreto.txt").write_text("dato", encoding="utf-8")
    _crear_enlace(mundo / "link", fuera)
    mundo_parcheado(mundo)

    with pytest.raises(ValueError):
        ab._resolve_snapshot_path("link/secreto.txt")


def test_enlace_dentro_del_mundo_es_aceptado(tmp_path, mundo_parcheado):
    mundo = tmp_path / "worlds" / "Bedrock level"
    real = mundo / "db"
    real.mkdir(parents=True)
    (real / "000001.ldb").write_bytes(b"dato")
    _crear_enlace(mundo / "db_link", real)
    mundo_parcheado(mundo)

    _clean, full = ab._resolve_snapshot_path("db_link/000001.ldb")
    assert os.path.exists(full)
