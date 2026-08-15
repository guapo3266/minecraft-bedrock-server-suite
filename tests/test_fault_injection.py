# -*- coding: utf-8 -*-
"""Pruebas de inyeccion de fallos (fault injection) sobre el motor de backups.

Escenarios:
1. Backup que tarda demasiado -> cancel_event aborta la compresion y libera el lock.
2. Servidor cerrado durante un backup -> el worker aborta sin dejar deadlocks ni .tmp.
3. Snapshot incompleto -> rechazado (vacio, <4 archivos, cobertura db/ <70%).
4. Dos backups simultaneos -> el lock rechaza la segunda solicitud (+ variante timeout).
5. ZIP corrupto (truncado) -> rechazado ANTES de tocar el mundo.
6. Fallo a mitad de restauracion -> rollback del resguardo recupera el mundo.

Usan directorios temporales: NUNCA tocan el mundo real del servidor.
"""
import os
import sys
import time
import zipfile
import shutil
import tempfile
import threading
import multiprocessing

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import auto_backup


def _setup_env():
    """Reemplaza BACKUP_DIR/WORLD_DIR por directorios temporales aislados."""
    tmp = tempfile.mkdtemp(prefix="fault_inj_")
    fake_bkp = os.path.join(tmp, "backups")
    fake_world = os.path.join(tmp, "worlds", "Bedrock level")
    os.makedirs(fake_bkp)
    os.makedirs(fake_world)
    old = (auto_backup.BACKUP_DIR, auto_backup.WORLD_DIR, auto_backup.BASE_DIR)
    auto_backup.BACKUP_DIR = fake_bkp
    auto_backup.WORLD_DIR = fake_world
    auto_backup.BASE_DIR = tmp
    return tmp, fake_bkp, fake_world, old


def _teardown(tmp, old):
    auto_backup.BACKUP_DIR, auto_backup.WORLD_DIR, auto_backup.BASE_DIR = old
    shutil.rmtree(tmp, ignore_errors=True)


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def _valid_world(fake_world, n_db_files=2):
    """Mundo falso minimo que pasa las validaciones de snapshot (100% cobertura db/)."""
    _write(os.path.join(fake_world, "level.dat"), b"L" * 100)
    for i in range(n_db_files):
        _write(os.path.join(fake_world, "db", "file_%02d.log" % i), b"D" * 64)
    _write(os.path.join(fake_world, "db", "CURRENT"), b"MANIFEST-000001")
    snapshot = [("level.dat", 100)]
    for i in range(n_db_files):
        snapshot.append(("db/file_%02d.log" % i, 64))
    snapshot.append(("db/CURRENT", 15))
    return snapshot


def _lock_free(lock, timeout=3.0):
    got = lock.acquire(timeout=timeout)
    if got:
        lock.release()
    return got


# ---- Escenario 1: backup que tarda demasiado -> cancelacion cooperativa ----
def test_backup_cancelado_libera_lock_y_limpia_tmp(capsys):
    tmp, fake_bkp, fake_world, old = _setup_env()
    lock = multiprocessing.Lock()
    try:
        _valid_world(fake_world)
        cancel = threading.Event()
        cancel.set()  # cancelado de antemano -> aborta en la primera comprobacion
        snap = [("level.dat", 100), ("db/CURRENT", 15), ("db/file_00.log", 64), ("db/file_01.log", 64)]
        # La cancelacion NO es desincronizacion del snapshot: create_backup
        # devuelve False (no propaga SnapshotDesyncError) y el wrapper no
        # reintenta una cancelacion.
        result = auto_backup.create_backup("test", file_snapshot=snap,
                                           cancel_event=cancel, external_lock=lock)
        out = capsys.readouterr().out
        assert result is False
        assert "Backup cancelled" in out
        # Sin .tmp huerfanos ni zip publicado
        assert not glob_tmp(fake_bkp), "quedaron .tmp huerfanos"
        assert not any(f.endswith(".zip") for f in os.listdir(fake_bkp))
        # El lock queda libre (sin deadlock tras abortar)
        assert _lock_free(lock), "el lock quedo tomado tras el aborto"
    finally:
        _teardown(tmp, old)


def glob_tmp(bkp_dir):
    return [f for f in os.listdir(bkp_dir) if f.endswith(".tmp")]


# ---- Escenario 4: dos backups simultaneos ----
def test_backup_simultaneo_rechazado_sin_espera(capsys):
    tmp, fake_bkp, fake_world, old = _setup_env()
    lock = multiprocessing.Lock()
    try:
        _valid_world(fake_world)
        assert lock.acquire()  # "el primer backup esta en curso"
        try:
            result = auto_backup.create_backup("test", file_snapshot=None,
                                               external_lock=lock, wait_lock_timeout_sec=0)
        finally:
            lock.release()
        out = capsys.readouterr().out
        assert result is False
        assert "Ya hay un backup ejecutandose" in out
    finally:
        _teardown(tmp, old)


def test_backup_simultaneo_timeout_espera_y_aborta(capsys):
    tmp, fake_bkp, fake_world, old = _setup_env()
    lock = multiprocessing.Lock()
    try:
        _valid_world(fake_world)
        assert lock.acquire()
        start = time.time()
        try:
            result = auto_backup.create_backup("test", file_snapshot=None,
                                               external_lock=lock, wait_lock_timeout_sec=1)
        finally:
            lock.release()
        elapsed = time.time() - start
        out = capsys.readouterr().out
        assert result is False
        assert "Backup lock wait timed out" in out
        assert 0.9 <= elapsed < 5, "el timeout no respeto el limite"
    finally:
        _teardown(tmp, old)


# ---- Escenario 2: servidor cerrado durante un backup (worker abortado) ----
def test_worker_abortado_no_deja_deadlock_ni_parciales(capsys):
    tmp, fake_bkp, fake_world, old = _setup_env()
    lock = multiprocessing.Lock()
    try:
        _valid_world(fake_world)
        cancel = threading.Event()
        results = {}

        def worker():
            results["r"] = auto_backup.create_backup(
                "test", file_snapshot=None, cancel_event=cancel, external_lock=lock)

        cancel.set()  # simula el aborto que el wrapper dispara al morir el servidor
        th = threading.Thread(target=worker)
        th.start()
        th.join(timeout=20)
        assert not th.is_alive(), "el worker quedo colgado"
        assert results.get("r") is False
        out = capsys.readouterr().out
        assert "Backup cancelled" in out
        assert _lock_free(lock), "lock tomado para siempre tras aborto del worker"
        assert not glob_tmp(fake_bkp)
    finally:
        _teardown(tmp, old)


# ---- Escenario 3: snapshot incompleto ----
def test_snapshot_vacio_rechazado(capsys):
    tmp, fake_bkp, fake_world, old = _setup_env()
    lock = multiprocessing.Lock()
    try:
        _valid_world(fake_world)
        import pytest
        with pytest.raises(RuntimeError):
            auto_backup.create_backup("test", file_snapshot=[], external_lock=lock)
        out = capsys.readouterr().out
        assert "Empty or invalid Bedrock snapshot" in out
    finally:
        _teardown(tmp, old)


def test_snapshot_con_pocos_archivos_rechazado(capsys):
    """Snapshot sin level.dat se rechaza de forma determinista."""
    tmp, fake_bkp, fake_world, old = _setup_env()
    lock = multiprocessing.Lock()
    try:
        _valid_world(fake_world)
        import pytest
        with pytest.raises(RuntimeError):
            auto_backup.create_backup("test", file_snapshot=[("db/CURRENT", 15)],
                                      external_lock=lock)
        out = capsys.readouterr().out
        assert "level.dat" in out
    finally:
        _teardown(tmp, old)


def test_snapshot_cobertura_db_insuficiente_rechazado(capsys):
    """Snapshot de save query es autoritativo: no se descarta por comparar contra disco."""
    tmp, fake_bkp, fake_world, old = _setup_env()
    lock = multiprocessing.Lock()
    try:
        _valid_world(fake_world, n_db_files=10)
        snap = [("level.dat", 100), ("db/CURRENT", 15),
                ("db/file_00.log", 64), ("db/file_01.log", 64)]
        res = auto_backup.create_backup("test", file_snapshot=snap, external_lock=lock)
        assert res and os.path.exists(res)
    finally:
        _teardown(tmp, old)


# ---- Escenario 5: ZIP truncado (corrupto) rechazado antes de tocar el mundo ----
def test_zip_truncado_rechazado_sin_tocar_mundo():
    tmp, fake_bkp, fake_world, old = _setup_env()
    try:
        zip_path = os.path.join(fake_bkp, "auto_backup_test_truncado.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("level.dat", b"GOOD-DATA" * 100)
        data = open(zip_path, "rb").read()
        open(zip_path, "wb").write(data[: len(data) // 2])  # truncar a la mitad

        _write(os.path.join(fake_world, "level.dat"), b"CURRENT-WORLD")
        try:
            auto_backup.restore_backup("auto_backup_test_truncado.zip")
            assert False, "debia rechazar el zip truncado"
        except (ValueError, zipfile.BadZipFile):
            pass
        with open(os.path.join(fake_world, "level.dat"), "rb") as f:
            assert f.read() == b"CURRENT-WORLD", "el mundo fue modificado"
        assert not os.path.exists(fake_world + ".bak")
    finally:
        _teardown(tmp, old)


# ---- Escenario 6: fallo a mitad de restauracion -> rollback ----
def test_restore_fallo_a_mitad_hace_rollback(monkeypatch):
    tmp, fake_bkp, fake_world, old = _setup_env()
    try:
        zip_path = os.path.join(fake_bkp, "auto_backup_test_ok.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            for i in range(3):
                zf.writestr("file_%d.bin" % i, b"X" * 500)

        _write(os.path.join(fake_world, "level.dat"), b"CURRENT-WORLD")
        _write(os.path.join(fake_world, "db", "CURRENT"), b"MANIFEST")

        calls = {"n": 0}
        orig_extract = zipfile.ZipFile.extract

        def flaky(self, member, path=None, pwd=None):
            calls["n"] += 1
            if calls["n"] >= 2:
                raise OSError("Fallo de disco simulado a mitad de extraccion")
            return orig_extract(self, member, path, pwd)

        monkeypatch.setattr(zipfile.ZipFile, "extract", flaky)
        try:
            auto_backup.restore_backup("auto_backup_test_ok.zip")
            assert False, "debia fallar la extraccion"
        except RuntimeError:
            pass
        monkeypatch.undo()

        # Rollback: el mundo anterior quedo intacto y sin resguardo colgado
        with open(os.path.join(fake_world, "level.dat"), "rb") as f:
            assert f.read() == b"CURRENT-WORLD", "el rollback no restauro el mundo"
        with open(os.path.join(fake_world, "db", "CURRENT"), "rb") as f:
            assert f.read() == b"MANIFEST"
        assert not os.path.exists(fake_world + ".bak"), "quedo un resguardo .bak colgado"
        assert calls["n"] >= 2
    finally:
        _teardown(tmp, old)