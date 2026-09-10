# -*- coding: utf-8 -*-
"""Endpoints de backups (/api/backups*, /api/restore).

El router es destructivo: fija 400/403/404/409/500 y los caminos felices con
`auto_backup.BACKUP_DIR` apuntando a tmp (nunca toca la carpeta real).
"""
import os
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import auto_backup
import server_gui_server as sgs
from gui_backend.state import manager

_CLIENTE_LOCAL = ("127.0.0.1", 50000)


def _client():
    return TestClient(sgs.app, client=_CLIENTE_LOCAL, raise_server_exceptions=False)


def _zip(path, entries=None):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in (entries or {"level.dat": b"X"}).items():
            zf.writestr(name, data)
    return path


@pytest.fixture
def backup_dir(tmp_path, monkeypatch):
    d = tmp_path / "backups"
    d.mkdir()
    monkeypatch.setattr(auto_backup, "BACKUP_DIR", str(d))
    monkeypatch.setattr(manager, "is_running", False)
    monkeypatch.setattr(manager, "backup_in_progress", False)
    return str(d)


def test_listado_ordena_por_mtime_y_excluye_marcados(backup_dir):
    viejo = _zip(os.path.join(backup_dir, "auto_backup_test_viejo.zip"))
    nuevo = _zip(os.path.join(backup_dir, "auto_backup_test_nuevo.zip"))
    _zip(os.path.join(backup_dir, "auto_backup_test_malo_CORRUPTO.zip"))
    _zip(os.path.join(backup_dir, "auto_backup_test_excedido_EXCEDIDO.zip"))
    os.utime(viejo, (1000, 1000))
    os.utime(nuevo, (2000, 2000))

    r = _client().get("/api/backups")

    assert r.status_code == 200
    backups = r.json()["backups"]
    assert [b["filename"] for b in backups] == [
        "auto_backup_test_nuevo.zip", "auto_backup_test_viejo.zip",
    ]
    assert all({"filename", "size_mb", "date"} <= set(b) for b in backups)


def test_listado_sin_directorio_devuelve_vacio(tmp_path, monkeypatch):
    monkeypatch.setattr(auto_backup, "BACKUP_DIR", str(tmp_path / "no_existe"))
    r = _client().get("/api/backups")
    assert r.status_code == 200
    assert r.json()["backups"] == []


def test_delete_inexistente_404(backup_dir):
    r = _client().post("/api/backups/no_existe.zip/delete")
    assert r.status_code == 404


def test_delete_ok_borra_archivo(backup_dir):
    path = _zip(os.path.join(backup_dir, "auto_backup_test_ok.zip"))
    r = _client().post("/api/backups/auto_backup_test_ok.zip/delete")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert not os.path.exists(path)


def test_delete_con_backup_en_curso_409(backup_dir, monkeypatch):
    _zip(os.path.join(backup_dir, "auto_backup_test_ok.zip"))
    monkeypatch.setattr(manager, "backup_in_progress", True)
    r = _client().post("/api/backups/auto_backup_test_ok.zip/delete")
    assert r.status_code == 409
    assert "backup en curso" in r.json()["detail"]


def test_download_ok_entrega_los_bytes(backup_dir):
    path = _zip(os.path.join(backup_dir, "auto_backup_test_dl.zip"),
                {"level.dat": b"CONTENIDO-ZIP"})
    r = _client().get("/api/backups/auto_backup_test_dl.zip/download")
    assert r.status_code == 200
    assert r.content == Path(path).read_bytes()
    assert r.headers["content-type"] == "application/zip"


def test_download_inexistente_404(backup_dir):
    r = _client().get("/api/backups/no_existe.zip/download")
    assert r.status_code == 404


def test_verify_ok_y_corrupto(backup_dir):
    _zip(os.path.join(backup_dir, "auto_backup_test_ok.zip"))
    with open(os.path.join(backup_dir, "auto_backup_test_roto.zip"), "wb") as f:
        f.write(b"esto no es un zip")

    r_ok = _client().post("/api/backups/auto_backup_test_ok.zip/verify")
    assert r_ok.status_code == 200
    assert r_ok.json()["status"] == "ok"

    r_bad = _client().post("/api/backups/auto_backup_test_roto.zip/verify")
    assert r_bad.status_code == 200
    assert r_bad.json()["status"] == "corrupt"


def test_verify_inexistente_404(backup_dir):
    r = _client().post("/api/backups/no_existe.zip/verify")
    assert r.status_code == 404


def test_restore_inexistente_404(backup_dir):
    r = _client().post("/api/restore", json={"filename": "no_existe.zip"})
    assert r.status_code == 404


def test_restore_con_servidor_corriendo_409(backup_dir, monkeypatch):
    monkeypatch.setattr(manager, "is_running", True)
    r = _client().post("/api/restore", json={"filename": "auto_backup_test_ok.zip"})
    assert r.status_code == 409


def test_restore_cuerpo_invalido_400(backup_dir):
    r = _client().post(
        "/api/restore", content=b"no-json",
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 400


def test_restore_filename_con_separadores_400(backup_dir):
    r = _client().post("/api/restore", json={"filename": "..\\evil.zip"})
    assert r.status_code == 400


def test_delete_oserror_500(backup_dir, monkeypatch):
    _zip(os.path.join(backup_dir, "auto_backup_test_ok.zip"))

    def _boom(_path):
        raise OSError("bloqueado por otro proceso")

    monkeypatch.setattr(os, "remove", _boom)
    r = _client().post("/api/backups/auto_backup_test_ok.zip/delete")
    assert r.status_code == 500


def test_verify_error_generico_500(backup_dir, monkeypatch):
    _zip(os.path.join(backup_dir, "auto_backup_test_ok.zip"))
    from gui_backend.services import backups as backups_service

    def _boom(_full):
        raise RuntimeError("exploto el testzip")

    monkeypatch.setattr(backups_service, "verify_zip", _boom)
    r = _client().post("/api/backups/auto_backup_test_ok.zip/verify")
    assert r.status_code == 500


def test_restore_error_generico_500(backup_dir, monkeypatch):
    from gui_backend.services import backups as backups_service

    def _boom(_manager, _filename):
        raise RuntimeError("exploto el restore")

    monkeypatch.setattr(backups_service, "restore_backup_under_lock", _boom)
    r = _client().post("/api/restore", json={"filename": "auto_backup_test_ok.zip"})
    assert r.status_code == 500
