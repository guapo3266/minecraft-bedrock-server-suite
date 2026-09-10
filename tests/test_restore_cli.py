# -*- coding: utf-8 -*-
"""CLI interactivo de restauracion (`restore_backup.list_and_restore`).

Cubre las canciones/guardas de la via sin GUI: cancelar, confirmacion
negativa, eleccion invalida, servidor corriendo, backup corrupto y el camino
feliz completo. Todo con directorios temporales: NUNCA toca el mundo real.
"""
import os
import zipfile

import pytest

import restore_backup as rb


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    base = tmp_path
    world = base / "worlds" / "Mundo"
    backups = base / "backups"
    world.mkdir(parents=True)
    backups.mkdir()
    (world / "level.dat").write_bytes(b"VIEJO")
    monkeypatch.setattr(rb, "BASE_DIR", str(base))
    monkeypatch.setattr(rb, "WORLD_DIR", str(world))
    monkeypatch.setattr(rb, "BACKUP_DIR", str(backups))
    monkeypatch.setattr(rb, "_server_is_running", lambda: False)
    monkeypatch.setattr(rb.os, "system", lambda *_a, **_k: 0)
    return base, world, backups


def _zip_backup(backups, data=b"NUEVO", name="auto_backup_test_ok.zip"):
    path = backups / name
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("level.dat", data)
    return path


def _responder(monkeypatch, respuestas):
    it = iter(respuestas)
    monkeypatch.setattr("builtins.input", lambda _p="": next(it))


def _restos(world):
    return [
        p.name for p in world.parent.iterdir()
        if ".bak_" in p.name or ".restore_staging_" in p.name
    ]


def _assert_intacto(world):
    assert (world / "level.dat").read_bytes() == b"VIEJO"


def test_cli_cancelar_con_cero_no_toca_el_mundo(cli_env, monkeypatch):
    _base, world, backups = cli_env
    _zip_backup(backups)
    _responder(monkeypatch, ["0"])

    rb.list_and_restore()

    _assert_intacto(world)
    assert _restos(world) == []


def test_cli_confirmacion_negativa_no_toca_el_mundo(cli_env, monkeypatch):
    _base, world, backups = cli_env
    _zip_backup(backups)
    _responder(monkeypatch, ["1", "NO", ""])

    rb.list_and_restore()

    _assert_intacto(world)
    assert _restos(world) == []


def test_cli_eleccion_invalida_no_toca_el_mundo(cli_env, monkeypatch):
    _base, world, backups = cli_env
    _zip_backup(backups)
    _responder(monkeypatch, ["abc", ""])

    rb.list_and_restore()

    _assert_intacto(world)


def test_cli_servidor_corriendo_aborta(cli_env, monkeypatch):
    _base, world, backups = cli_env
    _zip_backup(backups)
    monkeypatch.setattr(rb, "_server_is_running", lambda: True)
    _responder(monkeypatch, [""])

    rb.list_and_restore()

    _assert_intacto(world)


def test_cli_sin_carpeta_de_backups_aborta(cli_env, monkeypatch):
    _base, world, backups = cli_env
    monkeypatch.setattr(rb, "BACKUP_DIR", str(backups / "no_existe"))
    _responder(monkeypatch, [""])

    rb.list_and_restore()

    _assert_intacto(world)


def test_cli_backup_corrupto_no_toca_el_mundo(cli_env, monkeypatch):
    _base, world, backups = cli_env
    corrupto = backups / "auto_backup_test_roto.zip"
    corrupto.write_bytes(b"esto no es un zip")
    _responder(monkeypatch, ["1", "SI", ""])

    rb.list_and_restore()

    _assert_intacto(world)
    assert _restos(world) == []


def test_cli_restaura_backup_valido_y_limpia_residuos(cli_env, monkeypatch):
    _base, world, backups = cli_env
    _zip_backup(backups)
    _responder(monkeypatch, ["1", "SI", ""])

    rb.list_and_restore()

    assert (world / "level.dat").read_bytes() == b"NUEVO"
    assert _restos(world) == [], "quedaron .bak o staging sin limpiar"


def test_cli_fallo_de_extraccion_no_toca_el_mundo(cli_env, monkeypatch):
    import zipfile

    _base, world, backups = cli_env
    _zip_backup(backups)

    def _extract_falla(*_a, **_k):
        raise OSError("disco lleno simulado")

    monkeypatch.setattr(zipfile.ZipFile, "extract", _extract_falla)
    _responder(monkeypatch, ["1", "SI", ""])

    rb.list_and_restore()

    _assert_intacto(world)
    assert _restos(world) == []


def test_cli_rechaza_zip_que_excede_la_expansion(cli_env, monkeypatch):
    _base, world, backups = cli_env
    _zip_backup(backups)
    monkeypatch.setattr(rb, "_exceeds_expansion_limit", lambda *_a, **_k: True)
    _responder(monkeypatch, ["1", "SI", ""])

    rb.list_and_restore()

    _assert_intacto(world)
    assert _restos(world) == []


def test_cli_swap_fallido_hace_rollback_del_mundo(cli_env, monkeypatch):
    _base, world, backups = cli_env
    _zip_backup(backups)
    real_rename = os.rename

    def _rename_falla_al_activar(src, dst):
        # Deja pasar el resguardo (active -> .bak) y falla al activar el staging.
        if ".restore_staging_" in str(src):
            raise OSError("fallo simulado al activar el mundo")
        return real_rename(src, dst)

    monkeypatch.setattr(rb.os, "rename", _rename_falla_al_activar)
    _responder(monkeypatch, ["1", "SI", ""])

    rb.list_and_restore()

    _assert_intacto(world)
    assert _restos(world) == [], "el rollback dejo resguardos colgados"
