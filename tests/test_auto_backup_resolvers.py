# -*- coding: utf-8 -*-
"""Resolucion dinamica de mundo/backups en auto_backup (heuristica H3).

Distingue tres casos: base_dir explicita, global parcheado por tests
(monkeypatch) y global "stale" de una instalacion longeva cuyo
server.properties cambio despues del import. Sin tocar la instalacion real.
"""
import os

import auto_backup as ab


def _arbol(tmp_path, level_name="Nuevo"):
    (tmp_path / "worlds" / level_name).mkdir(parents=True)
    (tmp_path / "server.properties").write_text(
        f"level-name={level_name}\n", encoding="utf-8"
    )
    return tmp_path


def test_get_world_dir_con_base_dir_explicita(tmp_path):
    _arbol(tmp_path, "MundoAlfa")
    assert ab.get_world_dir(str(tmp_path)) == os.path.join(str(tmp_path), "worlds", "MundoAlfa")


def test_get_world_dir_respeta_el_global_parcheado(monkeypatch, tmp_path):
    _arbol(tmp_path)
    parcheado = os.path.join(str(tmp_path), "worlds", "Parcheado")
    monkeypatch.setattr(ab, "WORLD_DIR", parcheado)

    assert ab.get_world_dir() == parcheado


def test_get_world_dir_relee_properties_si_el_global_no_es_un_parche(
    monkeypatch, tmp_path
):
    """Global == valor de import (instalacion longeva): si server.properties
    cambio de level-name, se debe releer y no devolver el mundo viejo."""
    _arbol(tmp_path, "Nuevo")
    viejo = "C:/viejaSede/worlds/Bedrock level"
    monkeypatch.setattr(ab, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(ab, "WORLD_DIR", viejo)
    monkeypatch.setattr(ab, "_IMPORT_TIME_WORLD_DIR", viejo)

    assert ab.get_world_dir() == os.path.join(str(tmp_path), "worlds", "Nuevo")


def test_get_backup_dir_respeta_el_global_parcheado(monkeypatch):
    parcheado = "C:/backups/parcheado"
    monkeypatch.setattr(ab, "BACKUP_DIR", parcheado)

    assert ab.get_backup_dir() == parcheado


def test_resolve_backup_dir_por_instalacion():
    resultado = ab._resolve_backup_dir("C:/Servidores/TestA")
    partes = resultado.replace("\\", "/").split("/")
    assert partes[-3:] == ["Backups_Minecraft", "auto_backups", "TestA"], resultado
    assert os.path.isabs(resultado)


def test_rotate_backups_sin_carpeta_no_lanza(monkeypatch, tmp_path):
    monkeypatch.setattr(ab, "BACKUP_DIR", str(tmp_path / "no_existe"))
    ab.rotate_backups()  # no debe lanzar
