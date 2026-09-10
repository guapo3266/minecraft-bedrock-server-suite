# -*- coding: utf-8 -*-
"""Fallback de recuperacion de `_quarantine_and_restore` (zip_safety).

Cuando Windows no deja renombrar la ruta activa (archivos bloqueados por
antivirus/procesos), el modulo debe copiar RECURSIVAMENTE el resguardo sobre la
ruta activa y limpiar el .bak. Sin cobertura hasta 2026-09-10.
"""
import os

from zip_safety import _quarantine_and_restore


def test_fallback_copia_recursiva_cuando_rename_falla(tmp_path, monkeypatch):
    active = tmp_path / "active_world"
    bak = tmp_path / "active_world.bak_test"
    (active / "sub").mkdir(parents=True)
    (bak / "sub").mkdir(parents=True)
    (active / "level.dat").write_bytes(b"VIEJO")
    (active / "sub" / "x.bin").write_bytes(b"VIEJO-X")
    (bak / "level.dat").write_bytes(b"NUEVO")
    (bak / "sub" / "x.bin").write_bytes(b"NUEVO-X")

    def _rename_falla(*_a, **_k):
        raise OSError("bloqueado por otro proceso")

    monkeypatch.setattr(os, "rename", _rename_falla)
    _quarantine_and_restore(str(active), str(bak), is_dir=True)

    assert (active / "level.dat").read_bytes() == b"NUEVO"
    assert (active / "sub" / "x.bin").read_bytes() == b"NUEVO-X"
    assert not bak.exists()


def test_camino_feliz_rename_deja_el_bak_y_sin_residuos(tmp_path):
    active = tmp_path / "active_world"
    bak = tmp_path / "active_world.bak_test"
    active.mkdir()
    bak.mkdir()
    (active / "level.dat").write_bytes(b"VIEJO")
    (bak / "level.dat").write_bytes(b"NUEVO")

    _quarantine_and_restore(str(active), str(bak), is_dir=True)

    assert (active / "level.dat").read_bytes() == b"NUEVO"
    assert not bak.exists()
    assert not [p for p in os.listdir(tmp_path) if ".failed_" in p]


def test_sin_bak_no_hace_nada(tmp_path):
    active = tmp_path / "active_world"
    active.mkdir()
    (active / "level.dat").write_bytes(b"INTACTO")
    _quarantine_and_restore(str(active), str(tmp_path / "no_existe.bak"), is_dir=True)
    assert (active / "level.dat").read_bytes() == b"INTACTO"
