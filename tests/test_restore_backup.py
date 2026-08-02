"""Tests de la restauracion de backups (auto_backup.restore_backup).

Usan directorios temporales: NUNCA tocan el mundo real del servidor.
"""
import os
import sys
import zipfile
import shutil
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import auto_backup


def _setup_env():
    """Reemplaza BACKUP_DIR/WORLD_DIR por directorios temporales aislados."""
    tmp = tempfile.mkdtemp()
    fake_bkp = os.path.join(tmp, "backups")
    fake_world = os.path.join(tmp, "worlds", "Bedrock level")
    os.makedirs(fake_bkp)
    os.makedirs(fake_world)
    old = (auto_backup.BACKUP_DIR, auto_backup.WORLD_DIR)
    auto_backup.BACKUP_DIR = fake_bkp
    auto_backup.WORLD_DIR = fake_world
    return tmp, fake_bkp, fake_world, old


def _teardown(tmp, old):
    auto_backup.BACKUP_DIR, auto_backup.WORLD_DIR = old
    shutil.rmtree(tmp, ignore_errors=True)


def _make_zip(path, entries):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)


def test_restore_reemplaza_mundo_y_limpia_resguardo():
    tmp, fake_bkp, fake_world, old = _setup_env()
    try:
        _make_zip(os.path.join(fake_bkp, "auto_backup_test_ok.zip"),
                  {"level.dat": b"WORLD-DATA-OK", "world_icon.png": b"PNG"})
        with open(os.path.join(fake_world, "level.dat"), "wb") as f:
            f.write(b"CURRENT-WORLD")

        result = auto_backup.restore_backup("auto_backup_test_ok.zip")
        assert result.endswith("auto_backup_test_ok.zip")
        with open(os.path.join(fake_world, "level.dat"), "rb") as f:
            assert f.read() == b"WORLD-DATA-OK"
        assert not os.path.exists(fake_world + ".bak")
    finally:
        _teardown(tmp, old)


def test_restore_rechaza_traversal_en_filename():
    tmp, fake_bkp, fake_world, old = _setup_env()
    try:
        try:
            auto_backup.restore_backup("..\\..\\secret.zip")
            assert False, "debia rechazar traversal"
        except ValueError:
            pass
        # El mundo no fue tocado
        assert os.path.isdir(fake_world)
    finally:
        _teardown(tmp, old)


def test_restore_rechaza_zip_slip():
    tmp, fake_bkp, fake_world, old = _setup_env()
    try:
        _make_zip(os.path.join(fake_bkp, "auto_backup_test_evil.zip"),
                  {"../evil.txt": b"BAD"})
        try:
            auto_backup.restore_backup("auto_backup_test_evil.zip")
            assert False, "debia rechazar zip-slip"
        except ValueError:
            pass
    finally:
        _teardown(tmp, old)


def test_restore_fallback_rollback_en_zip_corrupto():
    tmp, fake_bkp, fake_world, old = _setup_env()
    try:
        zip_path = os.path.join(fake_bkp, "auto_backup_test_bad.zip")
        _make_zip(zip_path, {"level.dat": b"GOOD"})
        # Corromper el CRC del zip
        with open(zip_path, "r+b") as f:
            f.seek(-8, 2)
            f.write(b"\x00\x00\x00\x00")
        with open(os.path.join(fake_world, "level.dat"), "wb") as f:
            f.write(b"CURRENT-WORLD")

        try:
            auto_backup.restore_backup("auto_backup_test_bad.zip")
            assert False, "debia fallar con zip corrupto"
        except ValueError:
            pass
        # Rollback: el mundo sigue intacto y no quedan restos
        with open(os.path.join(fake_world, "level.dat"), "rb") as f:
            assert f.read() == b"CURRENT-WORLD"
        assert not os.path.exists(fake_world + ".bak")
    finally:
        _teardown(tmp, old)


def test_restore_inexistente_lanza_filenotfound():
    tmp, fake_bkp, fake_world, old = _setup_env()
    try:
        try:
            auto_backup.restore_backup("no_existe.zip")
            assert False, "debia lanzar FileNotFoundError"
        except FileNotFoundError:
            pass
    finally:
        _teardown(tmp, old)
