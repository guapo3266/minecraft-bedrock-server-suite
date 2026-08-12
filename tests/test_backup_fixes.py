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
import time
import shutil
import tempfile
import datetime
import asyncio
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import pytest
import auto_backup
import server_wrapper as sw
import server_gui_server as sgs
import gui_backend.supervisor as supervisor
import gui_backend.services.backups as backups_service
import gui_backend.services.bds_update as bds_update
import gui_backend.routers.backups as backups_router
import gui_backend.routers.actions as actions_router


def _setup_env():
    tmp = tempfile.mkdtemp(prefix="fixes_")
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

            listed = {os.path.basename(p) for p in backups_service._list_backup_files(tmp)}
        assert "auto_backup_ok.zip" in listed
        assert "otro.zip" in listed  # contrato historico: *.zip sin prefijo
        assert not any("_CORRUPTO" in n or "_EXCEDIDO" in n for n in listed), listed


# ── 6) clasificacion de fallos de snapshot ────────────────────────────────────
def test_is_snapshot_failure():
    """El wrapper reintenta los fallos anotados como snapshot, pero no los
    operativos (cancelacion, exceso de tamano) ni los ajenos al backup."""
    retry = [
        # Mensajes del worker con prefijo "Snapshot:" (solo SnapshotDesyncError:
        # desincronizacion del snapshot, que un nuevo save query puede arreglar)
        "Snapshot: Empty or invalid Bedrock snapshot; aborting hot backup.",
        "Snapshot: Snapshot missing level.dat; incomplete or invalid snapshot.",
        "Snapshot: Incomplete snapshot: 1 < 4 real files in db/.",
        "Snapshot: Snapshot truncated at 'db/000030.ldb': 5 < 1917505 bytes.",
        "Snapshot: Snapshot desync at 'x': file larger than snapshot.",
        "Snapshot: Snapshot file not found on disk: db/000030.ldb",
        "Snapshot: Snapshot file disappeared during copy: db/000030.ldb",
    ]
    for err in retry:
        assert sw._is_snapshot_failure(err) is True, err

    no_retry = [
        None,
        "",
        # Errores de almacenamiento/operativos: viajan SIN el prefijo "Snapshot:"
        # (backup_worker solo lo pone para SnapshotDesyncError) y un reintento
        # no los resuelve
        "[Errno 28] No space left on device",
        "[Errno 13] Permission denied: 'C:\\\\Backups\\\\auto_backup_x.zip'",
        "Backup exceeds the 10 GB limit (accumulated: 12.00 GB). Aborting.",
        "Backup cancelled before publishing ZIP.",
        # Defensa en profundidad: aunque llegaran prefijados, no reintentan
        "Snapshot: Backup cancelled before publishing ZIP.",
        "Snapshot: Backup exceeds the 10 GB limit (accumulated: 12.00 GB). Aborting.",
        # Ajenos al modo snapshot (fallo fuera del worker o resultado perdido)
        "The process exited without returning a result",
        "Could not write the result: boom",
    ]
    for err in no_retry:
        assert sw._is_snapshot_failure(err) is False, repr(err)


def test_almacenamiento_no_reintentable(monkeypatch):
    """Disco lleno al escribir el ZIP NO es desincronizacion del snapshot:
    create_backup devuelve False (sin excepcion) y el wrapper no reintenta."""
    import zipfile as _zipfile
    tmp, fake_bkp, fake_world, old = _setup_env()
    try:
        snap = _small_world(fake_world, n_db_files=1)

        def _disk_full(self, *args, **kwargs):
            raise OSError("[Errno 28] No space left on device")

        # El modo snapshot escribe en streaming via ZipFile.open (fix F3),
        # no via writestr: se inyecta el fallo en el mecanismo real.
        monkeypatch.setattr(_zipfile.ZipFile, "open", _disk_full)

        result = auto_backup.create_backup("test", file_snapshot=snap)
        assert result is False, (
            "el fallo de almacenamiento debe devolver False (no relanzar como "
            "SnapshotDesyncError)"
        )
        # Y el resultado que llegaria al wrapper (sin prefijo) no reintenta
        assert sw._is_snapshot_failure("[Errno 28] No space left on device") is False
    finally:
        _teardown(tmp, old)


# ── 7) parser con prefijo LOG ─────────────────────────────────────────────────
def test_parse_prefixed_LOG():
    assert sw.parse_save_query_files("[LOG] level.dat:6304") == [("level.dat", 6304)]
    assert sw.parse_save_query_files(
        "[2026-07-30 12:00:00:001 LOG] db/000030.ldb:5"
    ) == [("db/000030.ldb", 5)]
    assert sw.parse_save_query_files("[WARN] [LOG] a:1") == [("a", 1)]


def _api_resp(url="https://www.minecraft.net/bedrockdedicatedserver/bin-win/bedrock-server-1.26.40.8.zip"):
    class Resp:
        status_code = 200
        text = "<html>sin zip de bedrock aqui</html>"

        def json(self):
            return {"result": {"links": [
                {"downloadType": "serverBedrockWindows", "downloadUrl": url},
                {"downloadType": "serverJar", "downloadUrl": "https://x/server.jar"},
            ]}}

    return Resp()


def test_check_update_no_miente_si_version_instalada_es_desconocida(monkeypatch):
    """Sin version local conocida, el endpoint no debe afirmar que todo esta actualizado."""
    class Req:
        client = types.SimpleNamespace(host="127.0.0.1")

    old_version = sgs.manager.installed_version
    monkeypatch.setattr(sgs.manager, "installed_version", None)
    monkeypatch.setattr(bds_update.requests, "get", lambda *args, **kwargs: _api_resp())
    try:
        result = asyncio.run(actions_router.check_update(Req()))
        assert result["latest_version"] == "1.26.40.8"
        assert result["has_update"] is None
        assert result["unavailable"] is False
    finally:
        sgs.manager.installed_version = old_version


def test_check_update_detecta_version_nueva_por_api(monkeypatch):
    """La API oficial de Mojang (/api/v1.0/download/links) detecta versiones nuevas."""
    class Req:
        client = types.SimpleNamespace(host="127.0.0.1")

    old_version = sgs.manager.installed_version
    monkeypatch.setattr(sgs.manager, "installed_version", "1.26.33.2")
    monkeypatch.setattr(bds_update.requests, "get", lambda *args, **kwargs: _api_resp())
    try:
        result = asyncio.run(actions_router.check_update(Req()))
        assert result["latest_version"] == "1.26.40.8"
        assert result["download_url"].endswith("bedrock-server-1.26.40.8.zip")
        assert result["has_update"] is True
        assert result["unavailable"] is False
    finally:
        sgs.manager.installed_version = old_version


def test_check_update_sin_link_de_windows_marca_no_disponible(monkeypatch):
    """Si la API no trae el link de Windows, se reporta unavailable (no se miente)."""
    class Req:
        client = types.SimpleNamespace(host="127.0.0.1")

    old_version = sgs.manager.installed_version
    monkeypatch.setattr(sgs.manager, "installed_version", "1.26.33.2")
    monkeypatch.setattr(bds_update.requests, "get", lambda *args, **kwargs: _api_resp(url=""))
    try:
        result = asyncio.run(actions_router.check_update(Req()))
        assert result["unavailable"] is True
        assert result["latest_version"] is None
        assert result["has_update"] is None
    finally:
        sgs.manager.installed_version = old_version


def test_spawn_wrapper_limpia_evento_de_salida_antes_de_publicar_proceso(monkeypatch):
    """Un proceso nuevo nunca debe heredar el evento set del proceso anterior."""
    class FakeProcess:
        pass

    monkeypatch.setattr(supervisor.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    was_set = sgs.manager.wrapper_exit_event.is_set()
    sgs.manager.wrapper_exit_event.set()
    try:
        process = supervisor._spawn_wrapper_process()
        assert isinstance(process, FakeProcess)
        assert not sgs.manager.wrapper_exit_event.is_set()
    finally:
        if was_set:
            sgs.manager.wrapper_exit_event.set()
        else:
            sgs.manager.wrapper_exit_event.clear()


def test_run_wrapper_actualiza_version_aunque_hubiera_version_anterior(monkeypatch):
    """Cada arranque debe reemplazar la version capturada por la del nuevo log."""
    class FakeStdout:
        def __init__(self):
            self.lines = iter(["Version: 1.26.33.2\n", ""])

        def readline(self):
            return next(self.lines)

    class FakeProcess:
        stdout = FakeStdout()

        def wait(self):
            return None

    old_version = sgs.manager.installed_version
    old_process = sgs.manager.wrapper_process
    old_running = sgs.manager.is_running
    monkeypatch.setattr(sgs.manager, "update_status", lambda: None)
    monkeypatch.setattr(sgs.manager, "add_log", lambda *args, **kwargs: None)
    sgs.manager.installed_version = "1.26.32.2"
    try:
        supervisor.run_wrapper_thread(FakeProcess())
        assert sgs.manager.installed_version == "1.26.33.2"
    finally:
        sgs.manager.installed_version = old_version
        sgs.manager.wrapper_process = old_process
        sgs.manager.is_running = old_running


# ── 8) guard TOCTOU de /api/restore: 409 dentro del threadpool ────────────────
def test_restore_guard_dentro_threadpool_devuelve_409(monkeypatch):
    """Si el servidor se enciende entre el chequeo del endpoint y la ejecucion
    real, el guard interno responde 409 (no 500)."""
    import pytest
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    orig_run_in_threadpool = backups_router.run_in_threadpool

    async def _hijack(fn, *args, **kwargs):
        sgs.manager.is_running = True  # TOCTOU: se encendio mientras esperaba
        return await orig_run_in_threadpool(fn, *args, **kwargs)

    monkeypatch.setattr(backups_router, "run_in_threadpool", _hijack)
    sgs.manager.is_running = False
    try:
        # client=("127.0.0.1", ...) para pasar _ensure_local del endpoint
        with TestClient(sgs.app, client=("127.0.0.1", 50000)) as client:
            resp = client.post("/api/restore", json={"filename": "auto_backup_x.zip"})
            assert resp.status_code == 409, resp.text
            assert "encendió" in resp.json()["detail"]
    finally:
        sgs.manager.is_running = False


# ── 9) E2E worker real: fallo de lectura de snapshot -> reintento ─────────────
def _real_world_snapshot_with_missing_file():
    """Snapshot del mundo real (80% de db/) + un archivo inexistente:
    pasa las validaciones de cobertura pero falla al leer (FileNotFoundError),
    exactamente el caso reportado: BDS borra un archivo entre save query y copia."""
    world = auto_backup.WORLD_DIR
    files = []
    for root, _dirs, names in os.walk(os.path.join(world, "db")):
        for n in names:
            full = os.path.join(root, n)
            files.append((os.path.relpath(full, world).replace("\\", "/"),
                          os.path.getsize(full)))
    take = max(1, int(len(files) * 0.8))
    snapshot = [("db/zz_missing_%s.ldb" % os.urandom(4).hex(), 1)]
    snapshot += files[:take]
    snapshot.append(("level.dat", os.path.getsize(os.path.join(world, "level.dat"))))
    return snapshot


@pytest.mark.skipif(
    not os.path.exists(os.path.join(auto_backup.WORLD_DIR, "db")),
    reason="requiere mundo real con db/ (solo la instalacion TESTTEST)",
)
def test_worker_lectura_snapshot_fallida_programa_reintento():
    """Regresion del caso reportado: un fallo de lectura NO RuntimeError en el
    snapshot (archivo desaparecido) debe programar el reintento con backoff
    (snapshot_retry_at en el futuro), no esperar los 30 minutos."""
    ev = sw._FileCancelEvent(os.path.join(
        tempfile.gettempdir(), "e2e_%s.mark" % os.urandom(4).hex()))
    try:
        sw.execute_backup_worker(
            file_snapshot=_real_world_snapshot_with_missing_file(),
            cancel_event=ev,
        )
    finally:
        try:
            os.remove(ev.path)
        except OSError:
            pass

    with sw.state_lock:
        assert sw.snapshot_retry_count == 1, (
            "el fallo de lectura del snapshot no incremento el contador de reintentos"
        )
        assert sw.snapshot_retry_at > time.time(), (
            "el fallo de lectura del snapshot no programo un reintento con backoff"
        )
        assert sw.last_backup_completed_time != 0, (
            "el ultimo ciclo no quedo registrado"
        )
        assert not sw.backup_in_progress and not sw.backup_dispatched, (
            "estado colgado tras el ciclo del worker"
        )


# ── 10) backoff exponencial y limite de reintentos ─────────────────────────────
def test_snapshot_retry_delay_backoff():
    """El backoff es exponencial con tope: 5, 10, 20, 40, 60, 60, ..."""
    expected = [5, 10, 20, 40, 60, 60, 60, 60]
    for attempt, want in enumerate(expected, start=1):
        got = sw._snapshot_retry_delay(attempt)
        assert got == want, f"intento {attempt}: esperado {want}s, got {got}s"
        assert got <= sw.RETRY_BACKOFF_MAX_SEC


def test_snapshot_retry_limite_abandona_hasta_intervalo_normal():
    """Tras MAX reintentos consecutivos el patron se reinicia y no se programa
    mas reintento: se espera el proximo intervalo normal de 30 min."""
    ev = sw._FileCancelEvent(os.path.join(
        tempfile.gettempdir(), "e2e_%s.mark" % os.urandom(4).hex()))
    with sw.state_lock:
        sw.snapshot_retry_count = sw.MAX_CONSECUTIVE_SNAPSHOT_RETRIES - 1
        sw.snapshot_retry_at = 0.0
    try:
        sw.execute_backup_worker(file_snapshot=[], cancel_event=ev)
    finally:
        try:
            os.remove(ev.path)
        except OSError:
            pass

    with sw.state_lock:
        assert sw.snapshot_retry_count == 0, (
            "el contador no se reinicio al abandonar el reintento"
        )
        assert sw.snapshot_retry_at == 0.0, (
            "se programo un reintento tras el limite; debe esperar 30 min"
        )


# ── 11) update con staging/rollback y locks de operacion ──────────────────────
def test_apply_staged_update_exito_con_preservados():
    """El staging reemplaza los binarios pero respeta los archivos/dirs
    preservados (server.properties, worlds/)."""
    with tempfile.TemporaryDirectory() as tmp:
        base = os.path.join(tmp, "base")
        staging = os.path.join(tmp, "staging")
        os.makedirs(os.path.join(base, "worlds"))
        os.makedirs(os.path.join(staging, "behavior_packs"))
        for p, content in [
            (os.path.join(base, "a.dll"), "old-a"),
            (os.path.join(base, "server.properties"), "keep-me"),
            (os.path.join(base, "worlds", "level.dat"), "world"),
        ]:
            with open(p, "w") as f:
                f.write(content)
        for p, content in [
            (os.path.join(staging, "a.dll"), "new-a"),
            (os.path.join(staging, "behavior_packs", "pack.json"), "new-pack"),
        ]:
            with open(p, "w") as f:
                f.write(content)

        bds_update._apply_staged_update(
            staging, base,
            {"server.properties"}, {"worlds"},
        )

        assert open(os.path.join(base, "a.dll")).read() == "new-a"
        assert open(os.path.join(base, "behavior_packs", "pack.json")).read() == "new-pack"
        assert open(os.path.join(base, "server.properties")).read() == "keep-me"
        assert open(os.path.join(base, "worlds", "level.dat")).read() == "world"
        assert not os.path.exists(staging)
        assert not [d for d in os.listdir(base) if d.startswith("bds_update_prev_")]


def test_apply_staged_update_rollback_restaura_instalacion(monkeypatch):
    """Un fallo a mitad de la aplicacion restaura los binarios anteriores:
    la instalacion nunca queda con versiones mezcladas."""
    with tempfile.TemporaryDirectory() as tmp:
        base = os.path.join(tmp, "base")
        staging = os.path.join(tmp, "staging")
        os.makedirs(base)
        os.makedirs(staging)
        for p, content in [
            (os.path.join(base, "a.dll"), "old-a"),
            (os.path.join(base, "b.dll"), "old-b"),
        ]:
            with open(p, "w") as f:
                f.write(content)
        for p, content in [
            (os.path.join(staging, "a.dll"), "new-a"),
            (os.path.join(staging, "b.dll"), "new-b"),
        ]:
            with open(p, "w") as f:
                f.write(content)

        real_replace = os.replace

        def flaky(src, dst):
            if "b.dll" in str(dst):
                raise OSError("fallo simulado a mitad de la aplicacion")
            return real_replace(src, dst)

        monkeypatch.setattr(os, "replace", flaky)

        with pytest.raises(OSError):
            bds_update._apply_staged_update(staging, base, set(), set())

        # Rollback: TODO vuelve al estado anterior, sin mezcla de versiones
        assert open(os.path.join(base, "a.dll")).read() == "old-a"
        assert open(os.path.join(base, "b.dll")).read() == "old-b"
        assert not [d for d in os.listdir(base) if d.startswith("bds_update_prev_")]


def test_recover_interrupted_update_restores_old_and_removes_new():
    """Un proceso terminado entre fases deja una instalacion recuperable."""
    with tempfile.TemporaryDirectory() as tmp:
        base = os.path.join(tmp, "base")
        prev = os.path.join(base, "bds_update_prev_crash")
        os.makedirs(prev)
        _write(os.path.join(base, "a.dll"), b"new-a")
        _write(os.path.join(base, "new.dll"), b"new-file")
        _write(os.path.join(prev, "a.dll"), b"old-a")
        _write(
                os.path.join(prev, bds_update._UPDATE_MANIFEST_NAME),
            b'[{"path":"a.dll","had_previous":true},'
            b'{"path":"new.dll","had_previous":false}]',
        )

        bds_update.recover_interrupted_updates(base)

        assert open(os.path.join(base, "a.dll"), "rb").read() == b"old-a"
        assert not os.path.exists(os.path.join(base, "new.dll"))
        assert not os.path.exists(prev)


def test_cli_restore_excluye_backups_marcados():
    import restore_backup

    with tempfile.TemporaryDirectory() as tmp:
        for name in (
            "auto_backup_bueno.zip",
            "auto_backup_malo_CORRUPTO.zip",
            "auto_backup_grande_EXCEDIDO.zip",
        ):
            open(os.path.join(tmp, name), "wb").close()

        listed = restore_backup._list_backup_files(tmp)

        assert [os.path.basename(path) for path in listed] == ["auto_backup_bueno.zip"]


def test_start_rechaza_busy_con_operacion_en_curso():
    """Si una restauracion/actualizacion tiene op_lock, el start se rechaza
    con 'busy' (no espera ni lanza un segundo wrapper)."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    sgs.manager.is_running = False
    try:
        sgs.manager.op_lock.acquire()  # simula restore/update en curso
        try:
            with TestClient(sgs.app, client=("127.0.0.1", 50000)) as client:
                resp = client.post("/api/action/start")
                assert resp.status_code == 200
                assert resp.json()["status"] == "busy"
        finally:
            sgs.manager.op_lock.release()
    finally:
        sgs.manager.is_running = False


def test_doble_start_solo_lanza_un_wrapper(monkeypatch):
    """Dos solicitudes de start seguidas no lanzan dos wrappers: la segunda
    ve el estado marcado atomicamente y responde already_running."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    calls = {"n": 0}

    def fake_run_wrapper(*args, **kwargs):
        calls["n"] += 1

    monkeypatch.setattr(supervisor, "run_wrapper_thread", fake_run_wrapper)

    class _DummyProc:
        stdin = type("S", (), {"write": lambda *a: None, "flush": lambda *a: None})()
        stdout = type("O", (), {"readline": lambda *a: ""})()

        def wait(self):
            return 0

        def poll(self):
            return None

    # FIX G1: el handler crea el subproceso bajo op_lock via _spawn_wrapper_process
    monkeypatch.setattr(supervisor, "_spawn_wrapper_process", lambda: _DummyProc())
    sgs.manager.is_running = False
    try:
        with TestClient(sgs.app, client=("127.0.0.1", 50000)) as client:
            r1 = client.post("/api/action/start")
            r2 = client.post("/api/action/start")
        assert r1.json()["status"] == "starting", r1.text
        assert r2.json()["status"] == "already_running", r2.text
        assert calls["n"] == 1, f"se lanzo el wrapper {calls['n']} veces"
    finally:
        sgs.manager.is_running = False


# ── 12) restore_backup.py: rutas relativas a la propia instalacion ────────────
def test_restore_backup_rutas_relativas():
    """restore_backup.py resuelve el mundo desde su propia ubicacion: no puede
    sobrescribir la instalacion vecina (bug de las rutas hardcodeadas)."""
    import restore_backup as rb
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    expected_world = os.path.join(project_root, "worlds", rb._world_name())
    assert rb.WORLD_DIR == expected_world, (
        f"WORLD_DIR={rb.WORLD_DIR} no apunta a esta instalacion"
    )
    assert os.path.isabs(rb.WORLD_DIR)
    # H3: los backups son por instalacion (subcarpeta con el nombre del
    # servidor). NO comparar contra un nombre fijo ("Servidor de Guapo"): esa
    # assertion fallaba en la instalacion que se llama exactamente igual.
    assert rb.BACKUP_DIR.endswith(
        os.path.join("Backups_Minecraft", "auto_backups", rb.SERVER_NAME)
    ), f"BACKUP_DIR={rb.BACKUP_DIR} no es la subcarpeta por servidor"


# ── 13) op_lock cubre TODO el ciclo de operaciones que tocan el servidor ─────
def test_update_toma_op_lock_durante_todo_el_ciclo(monkeypatch):
    """El backup preventivo y la descarga corren CON op_lock adquirido: un
    start/restart durante cualquier fase de la actualizacion recibe busy."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    lock_state = {}

    def fake_create_backup(*args, **kwargs):
        lock_state["locked"] = sgs.manager.op_lock.locked()
        return os.path.join(tempfile.gettempdir(), "fake_pre_update.zip")

    class FakeResp:
        status_code = 200
        text = "<html>sin zip de bedrock aqui</html>"
        headers = {}

        def json(self):
            return {"result": {"links": [
                {"downloadType": "serverBedrockWindows",
                 "downloadUrl": "https://www.minecraft.net/bedrockdedicatedserver/bin-win/bedrock-server-1.26.40.8.zip"},
            ]}}

        def iter_content(self, chunk_size):
            return iter([])

    monkeypatch.setattr(sgs.auto_backup, "create_backup", fake_create_backup)
    monkeypatch.setattr(bds_update.requests, "get", lambda *a, **k: FakeResp())

    sgs.manager.is_running = False
    sgs.manager.update_in_progress = False
    try:
        with TestClient(sgs.app, client=("127.0.0.1", 50000)) as client:
            resp = client.post("/api/action/update_bds")
            assert resp.json()["status"] == "update_dispatched", resp.text
            deadline = time.time() + 10
            while sgs.manager.update_in_progress and time.time() < deadline:
                time.sleep(0.05)
        assert not sgs.manager.update_in_progress, "el hilo de update no termino"
        assert lock_state.get("locked") is True, (
            "el backup preventivo corrio sin op_lock: un start podria arrancar "
            "BDS durante la actualizacion"
        )
    finally:
        sgs.manager.is_running = False
        sgs.manager.update_in_progress = False


def test_restart_respeta_op_lock(monkeypatch):
    """Con una operacion en curso (op_lock retenido), el restart no lanza un
    nuevo wrapper."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    calls = {"n": 0}

    def fake_run_wrapper():
        calls["n"] += 1

    monkeypatch.setattr(supervisor, "run_wrapper_thread", fake_run_wrapper)
    sgs.manager.is_running = False
    try:
        sgs.manager.op_lock.acquire()  # actualizacion/restauracion en curso
        try:
            with TestClient(sgs.app, client=("127.0.0.1", 50000)) as client:
                resp = client.post("/api/action/restart")
                assert resp.json()["status"] == "restarting", resp.text
                time.sleep(0.5)  # deja terminar al hilo do_restart
            assert calls["n"] == 0, (
                "el restart lanzo un wrapper con una operacion en curso"
            )
        finally:
            sgs.manager.op_lock.release()
    finally:
        sgs.manager.is_running = False


def test_backup_frio_toma_op_lock(monkeypatch):
    """El backup en frio corre CON op_lock: un start inmediato no puede
    modificar el mundo mientras se comprime (backup inconsistente)."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    lock_state = {}

    def fake_create_backup(*args, **kwargs):
        lock_state["locked"] = sgs.manager.op_lock.locked()
        return os.path.join(tempfile.gettempdir(), "fake_gui_manual.zip")

    monkeypatch.setattr(sgs.auto_backup, "create_backup", fake_create_backup)
    sgs.manager.is_running = False
    sgs.manager.backup_in_progress = False
    try:
        with TestClient(sgs.app, client=("127.0.0.1", 50000)) as client:
            resp = client.post("/api/action/backup")
            assert resp.json()["status"] == "backup_dispatched", resp.text
            deadline = time.time() + 10
            while sgs.manager.backup_in_progress and time.time() < deadline:
                time.sleep(0.05)
        assert not sgs.manager.backup_in_progress, "el hilo de backup no termino"
        assert lock_state.get("locked") is True, (
            "el backup en frio corrio sin op_lock: un start podria modificar "
            "el mundo durante la copia"
        )
    finally:
        sgs.manager.is_running = False
        sgs.manager.backup_in_progress = False


# ── 14) carrera: start gana al backup en frio -> se cancela bajo el lock ─────
def test_backup_frio_cancela_si_servidor_inicio(monkeypatch):
    """Si `start` gana la carrera entre el chequeo del handler y la
    adquisicion del lock, el backup en frio se cancela dentro del lock: nunca
    copia el mundo con BDS activo."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    calls = {"n": 0}

    def fake_create_backup(*args, **kwargs):
        calls["n"] += 1
        return os.path.join(tempfile.gettempdir(), "fake_gui_manual.zip")

    monkeypatch.setattr(sgs.auto_backup, "create_backup", fake_create_backup)
    sgs.manager.is_running = False
    sgs.manager.backup_in_progress = False
    try:
        # El handler decide la rama 'off' (is_running=False). Antes de que el
        # hilo del backup adquiera el lock, el start gana la carrera y marca
        # is_running=True (bajo op_lock). Al soltar, el hilo debe cancelar.
        sgs.manager.op_lock.acquire()
        try:
            with TestClient(sgs.app, client=("127.0.0.1", 50000)) as client:
                resp = client.post("/api/action/backup")
                assert resp.json()["status"] == "backup_dispatched", resp.text
                # mientras el hilo espera el lock, el start marca el estado
                sgs.manager.is_running = True
        finally:
            sgs.manager.op_lock.release()  # el hilo del backup entra ahora

        time.sleep(0.5)  # deja terminar al hilo
        assert calls["n"] == 0, (
            "el backup en frio copio el mundo con el servidor iniciado"
        )
        assert not sgs.manager.backup_in_progress
    finally:
        sgs.manager.is_running = False
        sgs.manager.backup_in_progress = False


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--tb=short"])
