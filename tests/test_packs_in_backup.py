# -*- coding: utf-8 -*-
"""Los backups incluyen los packs de nivel servidor (mods/addons) y la
restauracion los devuelve a resource_packs/behavior_packs.

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
    tmp = tempfile.mkdtemp(prefix="packs_")
    fake_bkp = os.path.join(tmp, "backups")
    fake_world = os.path.join(tmp, "worlds", "Bedrock level")
    fake_base = os.path.join(tmp, "base")
    os.makedirs(fake_bkp)
    os.makedirs(fake_world)
    os.makedirs(fake_base)
    old = (auto_backup.BACKUP_DIR, auto_backup.WORLD_DIR, auto_backup.BASE_DIR)
    auto_backup.BACKUP_DIR = fake_bkp
    auto_backup.WORLD_DIR = fake_world
    auto_backup.BASE_DIR = fake_base
    return tmp, fake_bkp, fake_world, fake_base, old


def _teardown(tmp, old):
    auto_backup.BACKUP_DIR, auto_backup.WORLD_DIR, auto_backup.BASE_DIR = old
    shutil.rmtree(tmp, ignore_errors=True)


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def _make_packs(fake_base):
    rp = os.path.join(fake_base, "resource_packs", "Revolution Vibrant Visuals - Realistic")
    bp = os.path.join(fake_base, "behavior_packs", "MiMod")
    _write(os.path.join(rp, "manifest.json"),
           b'{"header":{"uuid":"917aab9c-5273-1000-ba5e-087a4328aa6b"}}')
    _write(os.path.join(rp, "textures", "rock.png"), b"PNGDATA")
    _write(os.path.join(bp, "manifest.json"), b'{"header":{"uuid":"bbbb-cccc"}}')
    return rp, bp


def test_backup_full_incluye_packs_de_servidor():
    """El backup tradicional (mundo + mods) guarda los packs con prefijo propio."""
    tmp, fake_bkp, fake_world, fake_base, old = _setup_env()
    try:
        _write(os.path.join(fake_world, "level.dat"), b"WORLD")
        rp, bp = _make_packs(fake_base)
        result = auto_backup.create_backup("test")
        assert result, "backup completo fallo"
        with zipfile.ZipFile(result) as zf:
            names = zf.namelist()
            assert "level.dat" in names
            assert "server_resource_packs/Revolution Vibrant Visuals - Realistic/manifest.json" in names
            assert "server_resource_packs/Revolution Vibrant Visuals - Realistic/textures/rock.png" in names
            assert "server_behavior_packs/MiMod/manifest.json" in names
            # los packs NO se cuelan como carpetas embebidas del mundo
            assert not any(n.startswith("resource_packs/") for n in names)
    finally:
        _teardown(tmp, old)


def test_backup_snapshot_incluye_packs_de_servidor():
    """El backup en caliente (snapshot Bedrock) tambien guarda los packs."""
    tmp, fake_bkp, fake_world, fake_base, old = _setup_env()
    try:
        _write(os.path.join(fake_world, "level.dat"), b"W" * 100)
        rp, bp = _make_packs(fake_base)
        result = auto_backup.create_backup("test", file_snapshot=[("level.dat", 100)])
        assert result, "backup snapshot fallo"
        with zipfile.ZipFile(result) as zf:
            names = zf.namelist()
            assert "level.dat" in names
            assert "server_resource_packs/Revolution Vibrant Visuals - Realistic/textures/rock.png" in names
            assert "server_behavior_packs/MiMod/manifest.json" in names
    finally:
        _teardown(tmp, old)


def test_restore_devuelve_packs_a_carpetas_de_servidor():
    """La restauracion reemplaza los packs del servidor con los del backup."""
    tmp, fake_bkp, fake_world, fake_base, old = _setup_env()
    try:
        rp, bp = _make_packs(fake_base)  # packs "viejos" instalados
        _write(os.path.join(rp, "textures", "rock.png"), b"OLD")
        _write(os.path.join(fake_world, "level.dat"), b"CURRENT-WORLD")

        zip_path = os.path.join(fake_bkp, "auto_backup_test_packs.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("level.dat", b"WORLD-BACKUP")
            zf.writestr("server_resource_packs/Revolution Vibrant Visuals - Realistic/manifest.json", b'{"v":2}')
            zf.writestr("server_resource_packs/Revolution Vibrant Visuals - Realistic/textures/rock.png", b"NEW")
            zf.writestr("server_behavior_packs/MiMod/manifest.json", b'{"v":9}')

        result = auto_backup.restore_backup("auto_backup_test_packs.zip")
        assert result.endswith("auto_backup_test_packs.zip")
        # mundo restaurado
        assert open(os.path.join(fake_world, "level.dat"), "rb").read() == b"WORLD-BACKUP"
        # packs restaurados en BASE_DIR/resource_packs y behavior_packs
        assert open(os.path.join(rp, "manifest.json"), "rb").read() == b'{"v":2}'
        assert open(os.path.join(rp, "textures", "rock.png"), "rb").read() == b"NEW"
        assert open(os.path.join(bp, "manifest.json"), "rb").read() == b'{"v":9}'
        # sin resguardos sobrantes
        assert not os.path.exists(fake_world + ".bak")
        assert not os.path.exists(rp + ".bak")
        assert not os.path.exists(bp + ".bak")
    finally:
        _teardown(tmp, old)


def test_restore_rollback_recupera_packs_y_mundo():
    """Si la extraccion falla, mundo y packs vuelven al estado anterior."""
    tmp, fake_bkp, fake_world, fake_base, old = _setup_env()
    try:
        rp, bp = _make_packs(fake_base)
        _write(os.path.join(rp, "textures", "rock.png"), b"OLD")
        _write(os.path.join(fake_world, "level.dat"), b"CURRENT-WORLD")

        zip_path = os.path.join(fake_bkp, "auto_backup_test_fail.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("level.dat", b"WORLD-BACKUP")
            zf.writestr("server_resource_packs/Revolution Vibrant Visuals - Realistic/manifest.json", b'{"v":2}')

        orig = auto_backup._extract_pack_entry

        def raiser(zf, entry, base_dir, rel_path):
            raise OSError("fallo simulado de disco")

        auto_backup._extract_pack_entry = raiser
        try:
            try:
                auto_backup.restore_backup("auto_backup_test_fail.zip")
                assert False, "debia fallar la restauracion"
            except RuntimeError:
                pass
        finally:
            auto_backup._extract_pack_entry = orig

        # mundo y pack recuperados desde los resguardos
        assert open(os.path.join(fake_world, "level.dat"), "rb").read() == b"CURRENT-WORLD"
        assert open(os.path.join(rp, "textures", "rock.png"), "rb").read() == b"OLD"
        assert not os.path.exists(fake_world + ".bak")
        assert not os.path.exists(rp + ".bak")
    finally:
        _teardown(tmp, old)


# ═══════════════════════════════════════════════════════════════════════
# H3: clasificacion de archivos sueltos en la raiz del pack dir
# ═══════════════════════════════════════════════════════════════════════
def test_pack_dest_clasifica_archivo_suelto_como_pack():
    """H3: un archivo en la raiz del pack dir (sin subcarpeta) se clasifica
    como pack con folder raiz, no como mundo."""
    assert auto_backup._pack_dest("server_resource_packs/notas.txt") == ("resource_packs", "", "notas.txt")
    assert auto_backup._pack_dest("server_behavior_packs/manifest.json") == ("behavior_packs", "", "manifest.json")
    # casos que no cambian
    assert auto_backup._pack_dest("server_resource_packs/MiPack/manifest.json") == ("resource_packs", "MiPack", "manifest.json")
    assert auto_backup._pack_dest("level.dat") is None
    assert auto_backup._pack_dest("server_resource_packs/") is None
    assert auto_backup._pack_dest("worlds/Bedrock level/db/foo") is None


def test_restore_devuelve_archivo_suelto_de_pack_a_carpeta_de_servidor():
    """H3: server_resource_packs/foo.txt se restaura a
    BASE_DIR/resource_packs/foo.txt, no adentro del mundo."""
    tmp, fake_bkp, fake_world, fake_base, old = _setup_env()
    try:
        _write(os.path.join(fake_world, "level.dat"), b"CURRENT-WORLD")
        zip_path = os.path.join(fake_bkp, "auto_backup_test_root_file.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("level.dat", b"WORLD-BACKUP")
            zf.writestr("server_resource_packs/notas.txt", b"LEEME")

        auto_backup.restore_backup("auto_backup_test_root_file.zip")
        assert open(os.path.join(fake_base, "resource_packs", "notas.txt"), "rb").read() == b"LEEME"
        assert not os.path.exists(os.path.join(fake_world, "server_resource_packs"))
        assert open(os.path.join(fake_world, "level.dat"), "rb").read() == b"WORLD-BACKUP"
    finally:
        _teardown(tmp, old)


def test_resolve_backup_dir_incluye_nombre_del_servidor():
    """H3: BACKUP_DIR se resuelve por instalacion:
    Backups_Minecraft/auto_backups/<carpeta del servidor>."""
    fake_base = os.path.join("C:", os.sep, "Servidores_Minecraft", "Servidor de Guapo")
    resolved = auto_backup._resolve_backup_dir(fake_base)
    expected = os.path.abspath(os.path.join(
        fake_base, "..", "..", "Backups_Minecraft", "auto_backups", "Servidor de Guapo"
    ))
    assert resolved == expected
    # dos servidores distintos => carpetas de backups distintas
    other = auto_backup._resolve_backup_dir(os.path.join("C:", os.sep, "Servidores_Minecraft", "TESTTEST"))
    assert other != resolved
