# -*- coding: utf-8 -*-
"""Ramas de recuperacion de restauraciones interrumpidas (auto_backup).

Cubre staging como ARCHIVO, cuarentena de huerfanos, rollback con rename
fallido y listdir inaccesible: ramas que quedaron sin cobertura hasta
2026-09-10. Son las que garantizan que un corte a mitad de restauracion no
pierda datos.
"""
import os

import auto_backup as ab


def _mundo(tmp_path, nombre="Mundo"):
    d = tmp_path / "worlds" / nombre
    d.mkdir(parents=True)
    (d / "level.dat").write_bytes(b"X")
    return d


def test_staging_archivo_se_elimina_y_se_registra(tmp_path):
    _mundo(tmp_path)
    staging = tmp_path / "worlds" / "Mundo.restore_staging_abc"
    staging.write_text("resto", encoding="utf-8")

    acciones = ab.recover_interrupted_restores(str(tmp_path))

    assert not staging.exists()
    assert any(a.startswith("staging_removed:") for a in acciones)


def test_rollback_cuando_falta_el_original(tmp_path):
    (tmp_path / "worlds").mkdir()
    bak = tmp_path / "worlds" / "Mundo.bak_abc"
    bak.write_bytes(b"RESGUARDO")

    acciones = ab.recover_interrupted_restores(str(tmp_path))

    assert (tmp_path / "worlds" / "Mundo").read_bytes() == b"RESGUARDO"
    assert not bak.exists()
    assert any(a.startswith("rollback:") for a in acciones)


def test_original_y_bak_existen_se_cuarentena_como_huerfano(tmp_path):
    original = _mundo(tmp_path)
    bak = tmp_path / "worlds" / "Mundo.bak_abc"
    bak.write_bytes(b"RESGUARDO")

    acciones = ab.recover_interrupted_restores(str(tmp_path))

    huerfanos = [p for p in os.listdir(tmp_path / "worlds") if ".bak_huerfano_" in p]
    assert len(huerfanos) == 1
    assert (original / "level.dat").read_bytes() == b"X"  # original intacto
    assert any(a.startswith("quarantined_orphan:") for a in acciones)


def test_huerfano_previo_no_se_reprocesa(tmp_path):
    (tmp_path / "worlds").mkdir()
    huerfano = tmp_path / "worlds" / "Mundo.bak_huerfano_20260101_000000_abcd"
    huerfano.write_bytes(b"X")

    acciones = ab.recover_interrupted_restores(str(tmp_path))

    assert huerfano.exists()
    assert not any("bak_huerfano" in a for a in acciones)


def test_rollback_con_rename_fallido_no_pierde_el_bak(tmp_path, monkeypatch):
    (tmp_path / "worlds").mkdir()
    bak = tmp_path / "worlds" / "Mundo.bak_abc"
    bak.write_bytes(b"RESGUARDO")

    def _rename_falla(*_a, **_k):
        raise OSError("bloqueado por antivirus")

    monkeypatch.setattr(ab.os, "rename", _rename_falla)
    acciones = ab.recover_interrupted_restores(str(tmp_path))

    assert bak.exists(), "el resguardo se perdio al fallar el rename"
    assert not any(a.startswith("rollback:") for a in acciones)


def test_huerfano_con_rename_fallido_no_lanza(tmp_path, monkeypatch):
    _mundo(tmp_path)
    bak = tmp_path / "worlds" / "Mundo.bak_abc"
    bak.write_bytes(b"RESGUARDO")

    def _rename_falla(*_a, **_k):
        raise OSError("bloqueado")

    monkeypatch.setattr(ab.os, "rename", _rename_falla)
    acciones = ab.recover_interrupted_restores(str(tmp_path))

    assert bak.exists()
    assert not any(a.startswith("quarantined_orphan:") for a in acciones)


def test_listdir_inaccesible_no_lanza(tmp_path, monkeypatch):
    (tmp_path / "worlds").mkdir()
    real_listdir = os.listdir

    def _listdir_falla(path):
        if os.path.basename(str(path)) == "worlds":
            raise OSError("sin permisos")
        return real_listdir(path)

    monkeypatch.setattr(ab.os, "listdir", _listdir_falla)
    assert ab.recover_interrupted_restores(str(tmp_path)) == []
