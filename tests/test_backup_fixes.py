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
import json
import shutil
import tempfile
import datetime
import asyncio
import types
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import pytest
import auto_backup
import backup_worker
import server_wrapper as sw
import wrapper_state as wstate
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

    with wstate.state_lock:
        assert wstate.snapshot_retry_count == 1, (
            "el fallo de lectura del snapshot no incremento el contador de reintentos"
        )
        assert wstate.snapshot_retry_at > time.time(), (
            "el fallo de lectura del snapshot no programo un reintento con backoff"
        )
        assert wstate.last_backup_completed_time != 0, (
            "el ultimo ciclo no quedo registrado"
        )
        assert not wstate.backup_in_progress and not wstate.backup_dispatched, (
            "estado colgado tras el ciclo del worker"
        )


# ── 10) backoff exponencial y limite de reintentos ─────────────────────────────
def test_snapshot_retry_delay_backoff():
    """El backoff es exponencial con tope: 5, 10, 20, 40, 60, 60, ..."""
    expected = [5, 10, 20, 40, 60, 60, 60, 60]
    for attempt, want in enumerate(expected, start=1):
        got = sw._snapshot_retry_delay(attempt)
        assert got == want, f"intento {attempt}: esperado {want}s, got {got}s"
        assert got <= wstate.RETRY_BACKOFF_MAX_SEC


def test_snapshot_retry_limite_abandona_hasta_intervalo_normal():
    """Tras MAX reintentos consecutivos el patron se reinicia y no se programa
    mas reintento: se espera el proximo intervalo normal de 30 min."""
    ev = sw._FileCancelEvent(os.path.join(
        tempfile.gettempdir(), "e2e_%s.mark" % os.urandom(4).hex()))
    with wstate.state_lock:
        wstate.snapshot_retry_count = wstate.MAX_CONSECUTIVE_SNAPSHOT_RETRIES - 1
        wstate.snapshot_retry_at = 0.0
    try:
        sw.execute_backup_worker(file_snapshot=[], cancel_event=ev)
    finally:
        try:
            os.remove(ev.path)
        except OSError:
            pass

    with wstate.state_lock:
        assert wstate.snapshot_retry_count == 0, (
            "el contador no se reinicio al abandonar el reintento"
        )
        assert wstate.snapshot_retry_at == 0.0, (
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


# ── 15) Snapshot: archivos no-WAL que crecen post-snapshot se truncan a N bytes ──
def test_snapshot_archivo_ldb_crece_post_snapshot_exitoso():
    """Un archivo .ldb que creció en disco tras el snapshot se trunca a los N bytes
    reportados por save query; el backup tiene éxito sin lanzar desync."""
    tmp, fake_bkp, fake_world, old = _setup_env()
    try:
        _write(os.path.join(fake_world, "level.dat"), b"LEVEL_DAT_HEADER_12345" * 5)
        # Archivo .ldb con 200 bytes en disco, snapshot indica 100 bytes
        ldb_path = os.path.join(fake_world, "db", "000005.ldb")
        _write(ldb_path, b"A" * 100 + b"B" * 100)
        _write(os.path.join(fake_world, "db", "CURRENT"), b"MANIFEST-000001")

        snap = [
            ("level.dat", 110),
            ("db/000005.ldb", 100),
            ("db/CURRENT", 15),
        ]
        result = auto_backup.create_backup("periodico", file_snapshot=snap)
        assert result and os.path.exists(result), "el backup debio completarse truncando a 100 bytes"

        # Verificar que en el ZIP el archivo tiene exactamente 100 bytes
        with zipfile.ZipFile(result, "r") as zf:
            content = zf.read("db/000005.ldb")
            assert len(content) == 100
            assert content == b"A" * 100
    finally:
        _teardown(tmp, old)


def test_snapshot_level_dat_crece_post_snapshot_exitoso():
    """level.dat que creció en disco tras save query se trunca a la longitud del snapshot."""
    tmp, fake_bkp, fake_world, old = _setup_env()
    try:
        _write(os.path.join(fake_world, "level.dat"), b"INIT_DATA" * 10 + b"EXTRA_ACTIVE_PLAYERS" * 5)
        _write(os.path.join(fake_world, "db", "000001.ldb"), b"LDB_DATA_1234567890")
        _write(os.path.join(fake_world, "db", "CURRENT"), b"MANIFEST-000001")

        snap = [
            ("level.dat", 90),
            ("db/000001.ldb", 19),
            ("db/CURRENT", 15),
        ]
        result = auto_backup.create_backup("periodico", file_snapshot=snap)
        assert result and os.path.exists(result), "level.dat que crecio debio truncarse a 90 bytes"

        with zipfile.ZipFile(result, "r") as zf:
            content = zf.read("level.dat")
            assert len(content) == 90
            assert content == b"INIT_DATA" * 10
    finally:
        _teardown(tmp, old)


def test_snapshot_archivo_truncado_en_disco_lanza_desync():
    """Si un archivo en disco tiene MENOS bytes que los reportados por save query,
    debe lanzar SnapshotDesyncError para reintento."""
    tmp, fake_bkp, fake_world, old = _setup_env()
    try:
        _write(os.path.join(fake_world, "level.dat"), b"LEVEL_DATA" * 10)
        _write(os.path.join(fake_world, "db", "000001.ldb"), b"LDB_DATA")  # 8 bytes
        _write(os.path.join(fake_world, "db", "CURRENT"), b"MANIFEST-000001")

        snap = [
            ("level.dat", 100),
            ("db/000001.ldb", 500),  # snapshot espera 500 bytes pero solo hay 8
            ("db/CURRENT", 15),
        ]
        with pytest.raises(auto_backup.SnapshotDesyncError):
            auto_backup.create_backup("periodico", file_snapshot=snap)
    finally:
        _teardown(tmp, old)


def test_snapshot_rutas_duplicadas_conflictivas_rechazado():
    """Rutas duplicadas en el snapshot con tamaños distintos se rechazan."""
    tmp, fake_bkp, fake_world, old = _setup_env()
    try:
        _write(os.path.join(fake_world, "level.dat"), b"LEVEL_DATA" * 10)
        _write(os.path.join(fake_world, "db", "000001.ldb"), b"LDB_DATA_1234567890" * 10)
        _write(os.path.join(fake_world, "db", "CURRENT"), b"MANIFEST-000001")

        snap = [
            ("level.dat", 100),
            ("db/000001.ldb", 50),
            ("db/000001.ldb", 100),  # duplicado conflictivo
            ("db/CURRENT", 15),
        ]
        with pytest.raises(auto_backup.SnapshotDesyncError):
            auto_backup.create_backup("periodico", file_snapshot=snap)
    finally:
        _teardown(tmp, old)


# ── 16) Restauración transaccional con staging ────────────────────────────────
def test_restore_fallo_extraccion_a_mitad_preserva_mundo_original():
    """Si la extracción del backup falla a mitad, el mundo original permanece 100% intacto."""
    tmp, fake_bkp, fake_world, old = _setup_env()
    try:
        _write(os.path.join(fake_world, "level.dat"), b"ORIGINAL_LEVEL_DAT_CONTENT")
        _write(os.path.join(fake_world, "db", "000001.ldb"), b"ORIGINAL_LDB_CONTENT")

        zip_path = os.path.join(fake_bkp, "auto_backup_test_invalido.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("level.dat", b"NEW_LEVEL_DAT")
            zf.writestr("db/000001.ldb", b"NEW_LDB")

        orig_extract = zipfile.ZipFile.extract

        def fail_extract(self, member, path=None, pwd=None):
            member_name = member.filename if hasattr(member, "filename") else member
            if "000001.ldb" in member_name:
                raise IOError("Fallo de disco simulado durante extraccion")
            return orig_extract(self, member, path=path, pwd=pwd)

        zipfile.ZipFile.extract = fail_extract
        try:
            with pytest.raises(Exception):
                auto_backup.restore_backup("auto_backup_test_invalido.zip")
        finally:
            zipfile.ZipFile.extract = orig_extract

        # El mundo original debe seguir intacto
        assert os.path.exists(os.path.join(fake_world, "level.dat"))
        with open(os.path.join(fake_world, "level.dat"), "rb") as f:
            assert f.read() == b"ORIGINAL_LEVEL_DAT_CONTENT"
        with open(os.path.join(fake_world, "db", "000001.ldb"), "rb") as f:
            assert f.read() == b"ORIGINAL_LDB_CONTENT"
    finally:
        _teardown(tmp, old)


def test_restore_exitoso_reemplaza_mundo_y_limpia_staging():
    """Restauración exitosa intercambia staging con el mundo y limpia residuos."""
    tmp, fake_bkp, fake_world, old = _setup_env()
    try:
        _write(os.path.join(fake_world, "level.dat"), b"OLD_WORLD")
        zip_path = os.path.join(fake_bkp, "auto_backup_test_good.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("level.dat", b"RESTORED_WORLD_LEVEL_DAT")
            zf.writestr("db/CURRENT", b"MANIFEST-000001")

        restored = auto_backup.restore_backup("auto_backup_test_good.zip")
        assert restored == zip_path
        with open(os.path.join(fake_world, "level.dat"), "rb") as f:
            assert f.read() == b"RESTORED_WORLD_LEVEL_DAT"

        # Verificar que no quedan carpetas .bak ni .restore_staging
        parent = os.path.dirname(fake_world)
        remaining = os.listdir(parent)
        assert len(remaining) == 1 and remaining[0] == "Bedrock level"
    finally:
        _teardown(tmp, old)


# ── 17) Bloqueo de update si falla backup preventivo ──────────────────────────
def test_update_bds_aborta_si_backup_preventivo_falla(monkeypatch):
    """Si el backup preventivo previo al update falla o retorna False, se aborta sin tocar binarios."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    installed_called = {"called": False}

    def fake_create_backup(*args, **kwargs):
        return False

    def fake_download_and_install():
        installed_called["called"] = True
        return True, "1.21.0.0"

    monkeypatch.setattr(actions_router.auto_backup, "create_backup", fake_create_backup)
    monkeypatch.setattr(actions_router.bds_update_service, "_download_and_install_bds", fake_download_and_install)

    sgs.manager.is_running = False
    sgs.manager.update_in_progress = False

    with TestClient(sgs.app, client=("127.0.0.1", 50000)) as client:
        resp = client.post("/api/action/update_bds")
        assert resp.json()["status"] == "update_dispatched"

    time.sleep(0.5)
    assert installed_called["called"] is False, "no debió llamar al instalador si el backup falló"
    assert sgs.manager.update_in_progress is False


# ── 18) Rotación excluye backups marcados como _CRASH ─────────────────────────
def test_rotate_backups_excluye_crash_backups_de_capa_reciente():
    """Los backups marcados _CRASH no desplazan backups saludables de la capa 15 recientes."""
    tmp, fake_bkp, fake_world, old = _setup_env()
    try:
        now = datetime.datetime(2026, 8, 15, 12, 0, 0)
        # Crear 15 backups saludables
        for i in range(15):
            p = os.path.join(fake_bkp, f"auto_backup_test_ok_{i}.zip")
            _write(p, b"OK")
            # poner mtime en el pasado
            mtime = (now - datetime.timedelta(minutes=i + 1)).timestamp()
            os.utime(p, (mtime, mtime))

        # Crear 1 backup de CRASH con mtime más reciente que todos
        crash_p = os.path.join(fake_bkp, "auto_backup_test_cierre_crash_2026-08-15_12-00-00_abcdef.zip")
        _write(crash_p, b"CRASH")
        os.utime(crash_p, (now.timestamp(), now.timestamp()))

        auto_backup.rotate_backups(now=now)

        # Los 15 backups saludables deben seguir existiendo + el crash backup (dentro de los 7 días)
        remaining = os.listdir(fake_bkp)
        assert len(remaining) == 16
        assert os.path.basename(crash_p) in remaining
    finally:
        _teardown(tmp, old)


# ── 19) Escritura atómica de server.properties ────────────────────────────────
def test_write_props_values_atomico(tmp_path, monkeypatch):
    """Verifica que _write_props_values escribe limpiamente sin dejar temporales."""
    from gui_backend.services import properties as props_service
    fake_props = str(tmp_path / "server.properties")
    monkeypatch.setattr(props_service.config, "PROPS_PATH", fake_props)

    # Escritura inicial
    written = props_service._write_props_values({"server-name": "Test Server", "gamemode": "survival"})
    assert "server-name" in written
    assert os.path.exists(fake_props)

    # No deben quedar archivos .tmp
    tmps = list(tmp_path.glob("*.tmp_*"))
    assert len(tmps) == 0

    # Lectura roundtrip
    vals = props_service._read_props_values()
    assert vals["server-name"] == "Test Server"
    assert vals["gamemode"] == "survival"


# ── 20) Bloqueo Sec-Fetch-Site: cross-site en descarga ────────────────────────
def test_download_backup_rechaza_sec_fetch_site_cross_site(tmp_path, monkeypatch):
    """Peticiones de descarga iniciadas con Sec-Fetch-Site: cross-site son rechazadas con 403."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    fake_bkp = str(tmp_path / "backups")
    os.makedirs(fake_bkp, exist_ok=True)
    zip_path = os.path.join(fake_bkp, "auto_backup_test_ok.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("level.dat", b"TEST")

    monkeypatch.setattr(auto_backup, "BACKUP_DIR", fake_bkp)

    with TestClient(sgs.app, client=("127.0.0.1", 50000)) as client:
        # Cross-site -> 403
        resp = client.get("/api/backups/auto_backup_test_ok.zip/download", headers={"sec-fetch-site": "cross-site"})
        assert resp.status_code == 403
        assert "cross-site" in resp.json()["detail"]

        # Same-origin -> 200
        resp_ok = client.get("/api/backups/auto_backup_test_ok.zip/download", headers={"sec-fetch-site": "same-origin"})
        assert resp_ok.status_code == 200
        assert resp_ok.content == open(zip_path, "rb").read()


# ── 21) Resolución dinámica de mundo sin reimportar módulo ────────────────────
def test_dynamic_world_name_resolution_without_reimport(tmp_path):
    """El cambio de level-name en server.properties se refleja en tiempo de ejecución."""
    import restore_backup as rb
    props = tmp_path / "server.properties"
    props.write_text("level-name=MundoAlfa\n", encoding="utf-8")

    assert auto_backup.get_world_name(str(tmp_path)) == "MundoAlfa"
    assert auto_backup.get_world_dir(str(tmp_path)).endswith("MundoAlfa")
    assert rb._world_name(str(tmp_path)) == "MundoAlfa"
    assert rb.get_world_dir(str(tmp_path)).endswith("MundoAlfa")

    # Cambiar configuración en caliente
    props.write_text("level-name=MundoBeta\n", encoding="utf-8")
    assert auto_backup.get_world_name(str(tmp_path)) == "MundoBeta"
    assert auto_backup.get_world_dir(str(tmp_path)).endswith("MundoBeta")
    assert rb._world_name(str(tmp_path)) == "MundoBeta"
    assert rb.get_world_dir(str(tmp_path)).endswith("MundoBeta")


# ── 22) Rollback con cuarentena recupera .bak ante archivos bloqueados ─────────
def test_restore_rollback_quarantines_and_recovers_bak_when_active_world_has_locked_files(tmp_path):
    """_quarantine_and_restore aísla el mundo activo y recupera .bak incluso con archivos abiertos."""
    active_world = str(tmp_path / "active_world")
    bak_world = str(tmp_path / "active_world.bak_test")
    os.makedirs(active_world, exist_ok=True)
    os.makedirs(bak_world, exist_ok=True)

    # Archivo original en bak
    with open(os.path.join(bak_world, "level.dat"), "wb") as f:
        f.write(b"ORIGINAL_LEVEL_DAT")

    # Archivo en active_world simulando estar bloqueado o abierto
    locked_file_path = os.path.join(active_world, "db_locked.log")
    with open(locked_file_path, "wb") as f_active:
        f_active.write(b"PARTIAL_STAGING_CONTENT")
        # Mantener el handle abierto simulando bloqueo de proceso Windows
        with open(locked_file_path, "rb") as _holder:
            auto_backup._quarantine_and_restore(active_world, bak_world, is_dir=True)

    # active_world debe haber sido recuperado desde bak_world
    assert os.path.exists(active_world)
    assert not os.path.exists(bak_world)
    with open(os.path.join(active_world, "level.dat"), "rb") as f:
        assert f.read() == b"ORIGINAL_LEVEL_DAT"


# ── 23) Worker de compresión usa JSON con soporte Unicode ────────────────────
def test_backup_worker_json_roundtrip_unicode_y_errores(tmp_path):
    """Roundtrip de snapshot y result por el código REAL del worker (JSON UTF-8)."""
    snap_file = str(tmp_path / "snap.json")
    result_file = str(tmp_path / "result.json")

    # Snapshot con nombres unicode: write/load a través de backup_worker
    snapshot_data = [["level.dat", 100], ["db/archivo_áéíóú_ñ.ldb", 2048]]
    with open(snap_file, "w", encoding="utf-8") as f:
        json.dump(snapshot_data, f, ensure_ascii=False)
    assert backup_worker.load_snapshot(snap_file) == snapshot_data

    # Resultado con error unicode: write/load a través de backup_worker
    result_data = {"zip": None, "error": "Error de compresión: verificación fallida 💥"}
    backup_worker.write_result(result_file, result_data)
    with open(result_file, "r", encoding="utf-8") as f:
        loaded_result = json.load(f)
    assert loaded_result == result_data
    assert loaded_result["error"] == "Error de compresión: verificación fallida 💥"

    # Roundtrip completo: lo que escribe write_result lo lee load (el wrapper
    # usa json.load sobre _result; mismo formato, sin escape ascii).
    roundtrip = {"zip": "auto_backup_x.zip", "error": None}
    backup_worker.write_result(result_file, roundtrip)
    with open(result_file, "r", encoding="utf-8") as f:
        assert json.load(f) == roundtrip


# ── 24) Blindaje contra spoofing de eventos desde chat ───────────────────────
def test_chat_spoofing_defense_no_altera_estado():
    """Verifica que mensajes de chat de jugadores no manipulen jugadores online ni save query."""
    import server_wrapper as sw
    from gui_backend import supervisor

    with wstate.state_lock:
        prev_players = set(wstate.players_online)
    try:
        # 1. Spoofing de desconexión
        with wstate.state_lock:
            wstate.players_online.clear()
            wstate.players_online.add("Steve")

        chat_disconnect = "[2026-08-15 12:00:00:001 INFO] <Griefer> Player disconnected: Steve, xuid: 12345"
        clean_line = sw._strip_log_prefix(chat_disconnect).strip()
        assert clean_line.startswith("<")
        # Al ser chat, _RE_PLAYER_DISCONNECT no debe ser evaluado ni coincidir sobre clean_line
        assert not sw._RE_PLAYER_DISCONNECT.search(clean_line)
        assert supervisor.classify_log_line(chat_disconnect) == "info"

        # 2. Spoofing de save query
        chat_save_query = "[2026-08-15 12:00:00:001 INFO] <Griefer> db/CURRENT:0, level.dat:0"
        assert sw.parse_save_query_files(chat_save_query) == []
        assert sw.parse_save_query_files("<Griefer> db/CURRENT:0, level.dat:0") == []

        # 3. Spoofing de marcadores de backup de la GUI: el chat debe
        # clasificarse como 'info' y no disparar la máquina de estados
        # (run_wrapper_thread solo la evalúa cuando log_type == 'backup').
        chat_compress = "[2026-08-15 12:00:00:002 INFO] <Griefer> Iniciando compresion de archivos en proceso separado"
        chat_finished = "[2026-08-15 12:00:00:003 INFO] <Griefer> Backup finalizado"
        assert supervisor.classify_log_line(chat_compress) == "info"
        assert supervisor.classify_log_line(chat_finished) == "info"
    finally:
        with wstate.state_lock:
            wstate.players_online.clear()
            wstate.players_online.update(prev_players)


# ── 25) Validación estructural LevelDB con condición OR para descriptores ───
def test_snapshot_leveldb_validation_con_or_y_vacio():
    """Verifica que el snapshot valide descriptores LevelDB (CURRENT o MANIFEST) cuando hay db/ en disco."""
    tmp, fake_bkp, fake_world, old = _setup_env()
    try:
        _write(os.path.join(fake_world, "level.dat"), b"LEVEL_DAT_BYTES")
        _write(os.path.join(fake_world, "db", "000001.ldb"), b"LDB_BYTES")
        _write(os.path.join(fake_world, "db", "CURRENT"), b"MANIFEST-000001")
        _write(os.path.join(fake_world, "db", "MANIFEST-000001"), b"MANIFEST_DATA")

        # Caso 1: Snapshot sin CURRENT ni MANIFEST debe lanzar SnapshotDesyncError
        snap_sin_desc = [("level.dat", 15), ("db/000001.ldb", 9)]
        with pytest.raises(auto_backup.SnapshotDesyncError):
            auto_backup.create_backup("periodico", file_snapshot=snap_sin_desc)

        # Caso 2: Snapshot con CURRENT + archivo db es válido
        snap_con_current = [("level.dat", 15), ("db/CURRENT", 15), ("db/000001.ldb", 9)]
        res1 = auto_backup.create_backup("periodico", file_snapshot=snap_con_current)
        assert res1 and os.path.exists(res1)

        # Caso 3: Snapshot con MANIFEST (sin CURRENT) + archivo db es válido (condición OR)
        snap_con_manifest = [("level.dat", 15), ("db/MANIFEST-000001", 13), ("db/000001.ldb", 9)]
        res2 = auto_backup.create_backup("periodico", file_snapshot=snap_con_manifest)
        assert res2 and os.path.exists(res2)

        # Caso 5: snapshot autoritativo con solo el descriptor CURRENT (sin
        # tablas .ldb) se acepta aunque el disco tenga tablas: el chequeo de
        # cobertura daba falsos positivos en mundos pequeños (regresión
        # test_cobertura_70_mundo_pequeno_sin_falso_positivo).
        snap_descriptor_solo = [("level.dat", 15), ("db/CURRENT", 15)]
        res4 = auto_backup.create_backup("periodico", file_snapshot=snap_descriptor_solo)
        assert res4 and os.path.exists(res4)

        # Caso 4: Mundo sin db/ en disco permite snapshot de solo level.dat
        shutil.rmtree(os.path.join(fake_world, "db"))
        res3 = auto_backup.create_backup("periodico", file_snapshot=[("level.dat", 15)])
        assert res3 and os.path.exists(res3)
    finally:
        _teardown(tmp, old)


# ── 26) Recuperación de restauraciones interrumpidas (rollback y huérfanos) ─
def test_recover_interrupted_restores_rollback_y_huerfanos(tmp_path):
    """Verifica limpieza de staging, rollback de .bak si destino falta y cuarentena si destino existe."""
    worlds_dir = tmp_path / "worlds"
    worlds_dir.mkdir(parents=True, exist_ok=True)

    # 1. Residuo de staging debe eliminarse
    staging_dir = worlds_dir / "Bedrock level.restore_staging_deadbeef"
    staging_dir.mkdir()
    (staging_dir / "temp.dat").write_text("junk", encoding="utf-8")

    # 2. .bak sin mundo activo original debe recuperarse (rollback)
    missing_world_bak = worlds_dir / "MundoPerdido.bak_1234abcd"
    missing_world_bak.mkdir()
    (missing_world_bak / "level.dat").write_text("LOST_LEVEL_DAT", encoding="utf-8")

    # 3. .bak con mundo activo existente debe aislarse como .bak_huerfano_*
    active_world = worlds_dir / "MundoActivo"
    active_world.mkdir()
    (active_world / "level.dat").write_text("ACTIVE_LEVEL_DAT", encoding="utf-8")
    orphan_bak = worlds_dir / "MundoActivo.bak_5678ef01"
    orphan_bak.mkdir()
    (orphan_bak / "level.dat").write_text("OLD_BAK_LEVEL_DAT", encoding="utf-8")

    # 4. Residuos de packs: staging y .bak en resource_packs (no server_*)
    packs_dir = tmp_path / "resource_packs"
    packs_dir.mkdir(parents=True, exist_ok=True)
    pack_staging = packs_dir / "MiPack.restore_staging_abcd1234"
    pack_staging.mkdir()
    (pack_staging / "manifest.json").write_text("junk", encoding="utf-8")
    pack_bak = packs_dir / "MiPack.bak_99ff00aa"
    pack_bak.mkdir()
    (pack_bak / "manifest.json").write_text("PACK_BAK_MANIFEST", encoding="utf-8")

    actions = auto_backup.recover_interrupted_restores(str(tmp_path))

    # Staging fue eliminado
    assert not staging_dir.exists()

    # MundoPerdido fue restaurado a su nombre original
    recovered_world = worlds_dir / "MundoPerdido"
    assert recovered_world.exists()
    assert (recovered_world / "level.dat").read_text(encoding="utf-8") == "LOST_LEVEL_DAT"
    assert not missing_world_bak.exists()

    # MundoActivo sigue intacto y su bak fue renombrado a .bak_huerfano_*
    assert active_world.exists()
    assert (active_world / "level.dat").read_text(encoding="utf-8") == "ACTIVE_LEVEL_DAT"
    assert not orphan_bak.exists()
    orphans = list(worlds_dir.glob("MundoActivo.bak_huerfano_*"))
    assert len(orphans) == 1
    assert (orphans[0] / "level.dat").read_text(encoding="utf-8") == "OLD_BAK_LEVEL_DAT"

    # Packs: staging eliminado y .bak recuperado como pack activo
    assert not pack_staging.exists()
    assert (packs_dir / "MiPack").exists()
    assert (packs_dir / "MiPack" / "manifest.json").read_text(encoding="utf-8") == "PACK_BAK_MANIFEST"
    assert not pack_bak.exists()

    # Todas las acciones registradas devuelven una lista con los eventos esperados
    assert any("rollback" in a for a in actions)
    assert any("staging_removed" in a for a in actions)


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--tb=short"])
