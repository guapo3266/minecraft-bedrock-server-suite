# -*- coding: utf-8 -*-
"""Unitarios deterministas de zip_safety: clasificacion de packs y guards."""

import pytest

from zip_safety import (
    _exceeds_expansion_limit,
    _extract_pack_entry,
    _is_safe_zip_entry,
    _pack_dest,
)


@pytest.mark.parametrize("entrada,esperado", [
    ("server_resource_packs/Pack/manifest.json",
     ("resource_packs", "Pack", "manifest.json")),
    ("server_behavior_packs/Mod/a/b.txt",
     ("behavior_packs", "Mod", "a/b.txt")),
    ("server_resource_packs/suelto.txt",
     ("resource_packs", "", "suelto.txt")),
    ("server_resource_packs/Pack/", None),   # entrada de directorio
    ("server_resource_packs/", None),
    ("server_behavior_packs/", None),
    ("level.dat", None),
    ("worlds/Mundo/db/CURRENT", None),
])
def test_pack_dest_clasifica(entrada, esperado):
    assert _pack_dest(entrada) == esperado


def test_extract_pack_entry_rechaza_traversal_sin_tocar_el_zip(tmp_path):
    class _Entry:
        filename = "server_resource_packs/P/../../evil"

    with pytest.raises(ValueError):
        _extract_pack_entry(None, _Entry(), str(tmp_path), "../evil")


@pytest.mark.parametrize("nombre,esperado", [
    ("a/b.txt", True),
    ("C:/Windows/x.dll", False),
    ("/abs/x", False),
    ("a/../b", False),
    ("a\\..\\b", False),
    ("a\x00b", False),
    ("\\.\\NUL", False),
])
def test_is_safe_zip_entry_casos_fijos(nombre, esperado):
    assert _is_safe_zip_entry(nombre) is esperado


def test_is_safe_zip_entry_no_str_es_insegura():
    assert _is_safe_zip_entry(None) is False
    assert _is_safe_zip_entry(123) is False


class _Info:
    def __init__(self, size):
        self.file_size = size


def test_expansion_limit_suma_y_corta():
    assert _exceeds_expansion_limit([_Info(10), _Info(20)], max_bytes=100) is False
    assert _exceeds_expansion_limit([_Info(10), _Info(200)], max_bytes=100) is True
    assert _exceeds_expansion_limit([], max_bytes=100) is False
    # entradas con tamaño no numerico se ignoran, no rompen
    assert _exceeds_expansion_limit([_Info(None), _Info(50)], max_bytes=100) is False
    assert _exceeds_expansion_limit([_Info("x"), _Info(50)], max_bytes=100) is False
