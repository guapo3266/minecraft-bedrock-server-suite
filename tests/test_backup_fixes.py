# -*- coding: utf-8 -*-
"""Regresiones de los fixes de revision (altos y medios).

Cubre:
1. Snapshot pequeno pero valido (con level.dat) ya NO se rechaza (fix <4 magico).
2. Snapshot sin level.dat se rechaza.
3. rotate_backups con `now` inyectable (determinista).
4. mark_corrupt_zip idempotente (sin _CORRUPTO_CORRUPTO.zip).
5. /api/backups excluye backups marcados _CORRUPTO/_EXCEDIDO.
6. Clasificacion de fallos de snapshot para reintento inmediato.
7. Parser acepta prefijos con nivel LOG.
"""
import os
import sys
import shutil
import tempfile
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import auto_backup
import server_wrapper as sw
import server_gui_server as sgs


def _setup_env():
    tmp = tempfile.mkdtemp(prefix="fixes_")
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


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def _small_world(fake_world, n_db_files=1):
    """Mundo falso con 1..n archivos db: snapshot total < 4 entradas."""
    _write(os.path.join(fake_world, "level.dat"), b"L" * 100)
    for i in range(n_db_files):
        _write(os.path.join(fake_world, "db", "file_%02d.log" % i), b"D" * 64)
    _write(os.path.join(fake_world, "db", "CURRENT"), b"MANIFEST-000001")
    snap = [("level.dat", 100)]
    for i in range(n_db_files):
        snap.append(("db/file_%02d.log" % i, 64))
    snap.append(("db/CURRENT", 15))
    return snap


# ── 1) Snapshot pequeno pero valido ya NO se rechaza ──────────────────────────
def test_snapshot_pequeno_valido_aceptado():
    """Un mundo con 3 archivos en el snapshot (level.dat + db) hace backup OK."""
    tmp, fake_bkp, fake_world, old = _setup_env()
    try:
        snap = _small_world(fake_world, n_db_files=1)  # 3 entradas (< 4)
        assert len(snap) < 4
        result = auto_backup.create_backup("test", file_snapshot=snap)
        assert result, "el snapshot pequeno valido fue rechazado"
        assert str(result).endswith(".zip") and os.path.exists(result)
    finally:
        _teardown(tmp, old)


# ── 2) Snapshot sin level.dat se rechaza ──────────────────────────────────────
def test_snapshot_sin_level_dat_rechazado(capsys):
    tmp, fake_bkp, fake_world, old = _setup_env()
    try:
        _small_world(fake_world, n_db_files=1)
        snap = [("db/file_00.log", 64), ("db/CURRENT", 15)]
        import pytest
        with pytest.raises(RuntimeError):
            auto_backup.create_backup("test", file_snapshot=snap)
        out = capsys.readouterr().out
        assert "level.dat" in out, out
    finally:
        _teardown(tmp, old)


# ── 3) rotate_backups con now inyectable ──────────────────────────────────────
def _make_backup_files(backup_dir, file_dates):
    os.makedirs(backup_dir, exist_ok=True)
    created = []
    for name, dt in file_dates:
        path = os.path.join(backup_dir, f"auto_backup_{name}.zip")
        with open(path, "w") as f:
            f.write("fake")
        ts = dt.timestamp()
        os.utime(path, (ts, ts))
        created.append(path)
    return created


def test_rotate_backups_now_inyectado_determinista():
    """Con `now` fijo, la capa diaria rescata 1 archivo de un dia distinto
    aunque no este entre los MAX_RECENT mas recientes."""
    tmp, fake_bkp, fake_world, old = _setup_env()
    try:
        now = datetime.datetime(2026, 8, 2, 12, 0, 0)
        dates = []
        # 15 backups de HOY (dentro de la ventana): ocupan la capa reciente
        for i in range(15):
            dates.append((f"hoy_{i:02d}", now - datetime.timedelta(minutes=30 * i)))
        # 5 backups de AYER: solo el mas reciente debe sobrevivir (1 por dia)
        for i in range(5):
            dates.append((f"ayer_{i:02d}", now - datetime.timedelta(days=1, minutes=30 * i)))

        _make_backup_files(fake_bkp, dates)
        auto_backup.rotate_backups(now=now)

        surviving = os.listdir(fake_bkp)
        assert len(surviving) == auto_backup.MAX_RECENT_BACKUPS + 1, (
            f"esperado {auto_backup.MAX_RECENT_BACKUPS} recientes + 1 diario, "
            f"hay {len(surviving)}"
        )
        assert "auto_backup_ayer_00.zip" in surviving, surviving
        assert not any(n.startswith("auto_backup_ayer_") for n in surviving if n != "auto_backup_ayer_00.zip"), (
            f"mas de un backup por dia conservado: {surviving}"
        )
    finally:
        _teardown(tmp, old)


# ── 4) mark_corrupt_zip idempotente ───────────────────────────────────────────
def test_mark_corrupt_zip_idempotente():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "auto_backup_x.zip")
        with open(path, "w") as f:
            f.write("zip")

        sw.mark_corrupt_zip(path, "CORRUPTO")
        marked = os.path.join(tmp, "auto_backup_x_CORRUPTO.zip")
        assert os.path.exists(marked), "no se marco el zip"

        sw.mark_corrupt_zip(marked, "CORRUPTO")  # segunda llamada
        assert os.path.exists(marked), "el zip marcado desaparecio"
        assert not os.path.exists(os.path.join(tmp, "auto_backup_x_CORRUPTO_CORRUPTO.zip")), (
            "doble marcado: _CORRUPTO_CORRUPTO.zip"
        )


# ── 5) /api/backups excluye marcados ──────────────────────────────────────────
def test_list_backup_files_excluye_corruptos():
    with tempfile.TemporaryDirectory() as tmp:
        for name in (
            "auto_backup_ok.zip",
            "auto_backup_corrupto_2026-01-01_00-00-00_CORRUPTO.zip",
            "auto_backup_excedido_2026-01-01_00-00-00_EXCEDIDO.zip",
            "otro.zip",
        ):
            with open(os.path.join(tmp, name), "w") as f:
                f.write("x")

        listed = {os.path.basename(p) for p in sgs._list_backup_files(tmp)}
        assert "auto_backup_ok.zip" in listed
        assert "otro.zip" in listed  # contrato historico: *.zip sin prefijo
        assert not any("_CORRUPTO" in n or "_EXCEDIDO" in n for n in listed), listed


# ── 6) clasificacion de fallos de snapshot ────────────────────────────────────
def test_is_snapshot_failure():
    real_errors = [
        "Snapshot Bedrock vacio o invalido; se aborta backup caliente.",
        "Snapshot sin level.dat; snapshot incompleto o invalido.",
        "Snapshot incompleto: 1 < 4 archivos reales en db/.",
        "Snapshot truncado en 'db/000030.ldb': 5 < 1917505 bytes.",
        "Desincronizacion de snapshot en 'x': archivo mas grande que snapshot.",
    ]
    for err in real_errors:
        assert sw._is_snapshot_failure(err) is True, err

    no_retry = [
        None,
        "",
        "Backup excede el limite de 10 GB (acumulado: 12.00 GB). Abortando.",
        "[Errno 28] No space left on device",
        "No se pudo escribir el resultado: boom",
    ]
    for err in no_retry:
        assert sw._is_snapshot_failure(err) is False, repr(err)


# ── 7) parser con prefijo LOG ─────────────────────────────────────────────────
def test_parse_prefixed_LOG():
    assert sw.parse_save_query_files("[LOG] level.dat:6304") == [("level.dat", 6304)]
    assert sw.parse_save_query_files(
        "[2026-07-30 12:00:00:001 LOG] db/000030.ldb:5"
    ) == [("db/000030.ldb", 5)]
    assert sw.parse_save_query_files("[WARN] [LOG] a:1") == [("a", 1)]


# ── 8) guard TOCTOU de /api/restore: 409 dentro del threadpool ────────────────
def test_restore_guard_dentro_threadpool_devuelve_409(monkeypatch):
    """Si el servidor se enciende entre el chequeo del endpoint y la ejecucion
    real, el guard interno responde 409 (no 500)."""
    import pytest
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    orig_run_in_threadpool = sgs.run_in_threadpool

    async def _hijack(fn, *args, **kwargs):
        sgs.manager.is_running = True  # TOCTOU: se encendio mientras esperaba
        return await orig_run_in_threadpool(fn, *args, **kwargs)

    monkeypatch.setattr(sgs, "run_in_threadpool", _hijack)
    sgs.manager.is_running = False
    try:
        # client=("127.0.0.1", ...) para pasar _ensure_local del endpoint
        with TestClient(sgs.app, client=("127.0.0.1", 50000)) as client:
            resp = client.post("/api/restore", json={"filename": "auto_backup_x.zip"})
            assert resp.status_code == 409, resp.text
            assert "encendió" in resp.json()["detail"]
    finally:
        sgs.manager.is_running = False


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--tb=short"])
