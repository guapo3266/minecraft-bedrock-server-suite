# -*- coding: utf-8 -*-
"""Unitarios de backup_worker._main: contrato snapshot -> result.json.

El worker corre en subproceso en produccion; aqui se ejercita su logica con
`create_backup` parcheado (exito, snapshot desincronizado y error generico)
para fijar el prefijo "Snapshot:" del que depende el reintento del wrapper.
"""
import json
import sys

import backup_worker as bw


def _correr_main(monkeypatch, tmp_path, fake_create):
    snap = tmp_path / "snap.json"
    snap.write_text("[]", encoding="utf-8")
    marker = tmp_path / "cancel.mark"
    result = tmp_path / "result.json"
    monkeypatch.setattr(sys, "argv",
                        ["backup_worker.py", str(snap), str(marker), str(result)])
    import auto_backup
    monkeypatch.setattr(auto_backup, "create_backup", fake_create)
    bw._main()
    return json.loads(result.read_text(encoding="utf-8"))


def test_main_exito_escribe_zip(tmp_path, monkeypatch):
    data = _correr_main(monkeypatch, tmp_path,
                        lambda *a, **k: r"C:\backups\auto_backup_test.zip")
    assert data == {"zip": r"C:\backups\auto_backup_test.zip", "error": None}


def test_main_snapshot_desync_lleva_prefijo_retry(tmp_path, monkeypatch):
    import auto_backup

    def _boom(*_a, **_k):
        raise auto_backup.SnapshotDesyncError("snapshot incompleto")

    data = _correr_main(monkeypatch, tmp_path, _boom)
    assert data["zip"] is None
    assert data["error"].startswith("Snapshot:"), data["error"]


def test_main_error_generico_sin_prefijo(tmp_path, monkeypatch):
    def _boom(*_a, **_k):
        raise OSError("disco lleno")

    data = _correr_main(monkeypatch, tmp_path, _boom)
    assert data["zip"] is None
    assert "Snapshot:" not in data["error"]
    assert "disco lleno" in data["error"]


def test_write_result_no_deja_parcial_ni_temporales(tmp_path, monkeypatch):
    """Si la serializacion falla, no debe quedar un result.json a medias ni
    .tmp_*: el wrapper leeria un JSON truncado como fallo opaco."""
    import json

    import backup_worker as bw

    destino = tmp_path / "result.json"

    def _dump_falla(*_a, **_k):
        raise TypeError("no serializable")

    monkeypatch.setattr(json, "dump", _dump_falla)
    try:
        bw.write_result(str(destino), {"x": object()})
        raise AssertionError("write_result debia propagar el fallo de dump")
    except TypeError:
        pass

    assert not destino.exists()
    assert list(tmp_path.glob("*.tmp_*")) == []


def test_main_snapshot_ilegible_escribe_error_retryable(tmp_path, monkeypatch):
    """Si el snapshot no se puede leer (archivo borrado entre padre e hijo),
    el worker debe devolver un error con prefijo Snapshot: en vez de morir con
    traceback: el wrapper reintenta y el usuario ve el motivo."""
    marker = tmp_path / "m.mark"
    result = tmp_path / "r.json"
    monkeypatch.setattr(sys, "argv", [
        "backup_worker.py", str(tmp_path / "no_existe.json"), str(marker), str(result),
    ])

    try:
        bw._main()
        raise AssertionError("el worker debia terminar con SystemExit")
    except SystemExit:
        pass

    data = json.loads(result.read_text(encoding="utf-8"))
    assert data["zip"] is None
    assert data["error"].startswith("Snapshot:")
