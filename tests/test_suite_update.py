"""Instalador de código: preservación, fallo inyectado, rollback y guards HTTP."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import threading
import subprocess
import zipfile

import pytest
from hypothesis import given, settings, strategies as st, HealthCheck
from fastapi.testclient import TestClient

import suite_release as release
import suite_updater
import server_gui_server as gui
from gui_backend import state, supervisor
from gui_backend.services import suite_update as service


def make_tree(root, version, extra=None):
    root.mkdir(parents=True, exist_ok=True)
    files = {"version.json": json.dumps({"version": version}).encode(),
             "server_gui_server.py": b"# GUI", "suite_updater.py": b"# helper", "runtime/python.exe": b"runtime",
             "console_lang.py": b"# unchanged", **(extra or {})}
    inventory = {}
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        inventory[name] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    manifest = {"schema": 1, "repository": release.REPOSITORY, "platform": "windows-x64", "version": version,
                "dirty": False, "files": inventory}
    release.write_json(root / release.MANIFEST, manifest)
    return manifest


def make_zip(root, archive, extras=None):
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
        for path in root.rglob("*"):
            if path.is_file():
                output.write(path, path.relative_to(root).as_posix())
        for name, data in (extras or {}).items():
            output.writestr(name, data)


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@given(st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=70))
def test_rutas_de_datos_y_config_no_entran_en_ningun_prefijo(suffix):
    for protected in ("server.properties", "permissions.json", "allowlist.json", "worlds", "backups", "data", "config", "resource_packs", "behavior_packs", "bedrock_server.exe"):
        assert not release.managed_path(protected + "/" + suffix)
        assert not release.managed_path("runtime/" + protected + "/" + suffix)
        assert not release.managed_path(protected)


@pytest.mark.parametrize("name", ["../server_gui_server.py", "/runtime/python.exe", "runtime/a:stream", "runtime/NUL.txt",
                                  "runtime/a. ", "runtime/../server.properties", "gui_backend\\state.py", "runtime/.git/config",
                                  "runtime/x\x00.dll", "tools/build_release.py", "AGENTS.md"])
def test_rutas_peligrosas_rechazadas(name):
    assert not release.managed_path(name)


def test_zip_y_hashes_son_autoritativos_antes_de_instalar(tmp_path):
    source = tmp_path / "source"
    make_tree(source, "2.1.0")
    archive = tmp_path / "release.zip"
    make_zip(source, archive)
    release.extract_package(archive, tmp_path / "stage", "2.1.0")
    assert release.verify_tree(tmp_path / "stage")["version"] == "2.1.0"
    make_zip(source, archive, {"server.properties": b"malicioso"})
    with pytest.raises(ValueError):
        release.extract_package(archive, tmp_path / "rejected", "2.1.0")
    assert not (tmp_path / "rejected").exists()
    (source / "server_gui_server.py").write_bytes(b"xxxxx")
    make_zip(source, archive)
    with pytest.raises(ValueError, match="Integridad"):
        release.extract_package(archive, tmp_path / "corrupt", "2.1.0")


def test_zip_rechaza_symlink_y_duplicado_de_windows(tmp_path):
    source = tmp_path / "source"
    make_tree(source, "2.1.0")
    archive = tmp_path / "release.zip"
    make_zip(source, archive)
    with zipfile.ZipFile(archive, "a") as output:
        info = zipfile.ZipInfo("runtime/link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        output.writestr(info, "../../server.properties")
    with pytest.raises(ValueError):
        release.extract_package(archive, tmp_path / "stage", "2.1.0")
    make_zip(source, archive, {"runtime/PYTHON.exe": b"duplicate"})
    with pytest.raises(ValueError):
        release.extract_package(archive, tmp_path / "stage2", "2.1.0")


@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.binary(max_size=400))
def test_instala_solo_cambios_y_rollback_preserva_datos(tmp_path, content):
    # Cada ejemplo tiene una raíz nueva; tmp_path no comparte estado entre ejemplos.
    root = tmp_path / str(len(list(tmp_path.iterdir())))
    target, stage, job = root / "target", root / "stage", root / "job"
    make_tree(target, "2.0.0", {"web/old.js": b"obsoleto"})
    make_tree(stage, "2.1.0", {"server_gui_server.py": b"# GUI nueva", "web/new.js": b"nuevo"})
    for name in ("server.properties", "permissions.json", "worlds/Mundo/level.dat", "resource_packs/pack/manifest.json", "data/config.json"):
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    before = snapshot(target)
    unchanged = target / "console_lang.py"
    timestamp = unchanged.stat().st_mtime_ns
    journal = release.prepare_update(stage, target, job)
    assert "console_lang.py" not in {op["path"] for op in journal["operations"]}
    release.apply_update(job, journal)
    assert not (target / "web/old.js").exists()
    assert unchanged.stat().st_mtime_ns == timestamp
    for name in ("server.properties", "permissions.json", "worlds/Mundo/level.dat", "resource_packs/pack/manifest.json", "data/config.json"):
        assert (target / name).read_bytes() == content
    release.rollback_update(job, journal)
    assert snapshot(target) == before
    # Es idempotente y conserva el resguardo incluso después de la recuperación.
    release.rollback_update(job, journal)
    assert snapshot(target) == before
    assert (job / "previous/version.json").is_file()


def test_fallo_tras_reemplazo_recupera_desde_diario_persistido(tmp_path, monkeypatch):
    target, stage, job = tmp_path / "target", tmp_path / "stage", tmp_path / "job"
    make_tree(target, "2.0.0")
    make_tree(stage, "2.1.0", {"server_gui_server.py": b"nueva"})
    before = snapshot(target)
    journal = release.prepare_update(stage, target, job)
    original = release._atomic_copy
    fired = False

    def crash(source, dest):
        nonlocal fired
        original(source, dest)
        if dest == target / "server_gui_server.py" and not fired:
            fired = True
            raise OSError("apagón después del replace")

    monkeypatch.setattr(release, "_atomic_copy", crash)
    with pytest.raises(OSError):
        release.apply_update(job, journal)
    persisted = json.loads((job / "journal.json").read_text(encoding="utf-8"))
    release.rollback_update(job, persisted)
    assert snapshot(target) == before


def test_rollback_incompleto_conserva_evidencia(tmp_path):
    target, stage, job = tmp_path / "target", tmp_path / "stage", tmp_path / "job"
    make_tree(target, "2.0.0")
    make_tree(stage, "2.1.0")
    journal = release.prepare_update(stage, target, job)
    release.apply_update(job, journal)
    (job / "previous/version.json").unlink()
    with pytest.raises(ValueError, match="Resguardo"):
        release.rollback_update(job, journal)
    assert (job / "previous" / release.MANIFEST).exists()
    assert json.loads((job / "journal.json").read_text(encoding="utf-8"))["phase"] == "rollback_failed"


def test_no_reemplaza_checkout_git(tmp_path):
    target, stage = tmp_path / "target", tmp_path / "stage"
    make_tree(target, "2.0.0")
    make_tree(stage, "2.1.0")
    (target / ".git").mkdir()
    with pytest.raises(ValueError, match="Git"):
        release.prepare_update(stage, target, tmp_path / "job")


def test_redireccion_externa_no_se_contacta(tmp_path, monkeypatch):
    calls = []

    class Response:
        status_code = 302
        headers = {"Location": "https://evil.example/payload.zip"}
        def __enter__(self): return self
        def __exit__(self, *_): pass

    def get(url, **_kwargs):
        calls.append(url)
        return Response()

    monkeypatch.setattr(service.requests, "get", get)
    with pytest.raises(ValueError, match="fuera"):
        service._download({"url": "https://github.com/"}, tmp_path / "zip")
    assert calls == ["https://github.com/"]


def test_api_confirmacion_git_y_guard_durante_relevo(monkeypatch, tmp_path):
    monkeypatch.setattr(service.config, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(service, "_exit_callback", None)
    with TestClient(gui.app, client=("127.0.0.1", 50000)) as client:
        assert client.post("/api/suite_update", json={"confirmed": False}).status_code == 400
        assert client.post("/api/suite_update", json={"confirmed": True}).status_code == 409
        assert client.post("/api/suite_update", json={"confirmed": True, "url": "https://evil.example"}).status_code == 422
        monkeypatch.setattr(state.manager, "suite_update_in_progress", True)
        assert client.post("/api/command", json={"command": "list"}).status_code == 409
        assert client.post("/api/action/start").status_code == 409


def test_evento_final_no_confunde_fin_de_ciclo_con_backup_valido(monkeypatch):
    monkeypatch.setattr(state.manager, "final_backup_result", None)
    supervisor._apply_event({"event": "backup_finished", "outcome": "success"})
    assert state.manager.final_backup_result is None
    supervisor._apply_event({"event": "final_backup_finished", "success": False, "zip": None})
    assert state.manager.final_backup_result == {"success": False, "zip": None}


def test_canal_viejo_no_acredita_backup_final_de_sesion_nueva(tmp_path, monkeypatch):
    old = tmp_path / "old.ndjson"
    old.write_text(json.dumps({"event": "final_backup_finished", "success": True, "zip": "old.zip"}) + "\n", encoding="utf-8")
    monkeypatch.setattr(state.manager, "events_file", str(tmp_path / "new.ndjson"))
    monkeypatch.setattr(state.manager, "final_backup_result", None)
    supervisor._tail_events(str(old))
    assert state.manager.final_backup_result is None


def test_recuperacion_preparada_sin_relevo_no_bloquea_arranque(tmp_path):
    target = tmp_path / "target"
    job = target / "data/suite_updates/recovery"
    stage = job / "stage"
    make_tree(target, "2.0.0")
    make_tree(stage, "2.1.0")
    release.prepare_update(stage, target, job)
    assert suite_updater.recover(target) == 0
    assert not (job / "request.json").exists()


def test_backup_final_fallido_aborta_sin_tocar_programa(tmp_path, monkeypatch):
    root, incoming = tmp_path / "target", tmp_path / "incoming"
    make_tree(root, "2.0.0")
    make_tree(incoming, "99.0.0")
    for name in ("suite_updater.py", "suite_release.py", "zip_safety.py", "console_lang.py", "windows_process_guard.py"):
        shutil.copy2(Path(__file__).resolve().parents[1] / name, root / name)
    original = snapshot(root)
    archive = tmp_path / "new.zip"
    make_zip(incoming, archive)
    monkeypatch.setattr(service.config, "BASE_DIR", str(root))
    monkeypatch.setattr(state.manager, "op_lock", threading.Lock())
    state.manager.op_lock.acquire()
    monkeypatch.setattr(state.manager, "suite_update_in_progress", True)
    monkeypatch.setattr(state.manager, "is_running", True)
    monkeypatch.setattr(state.manager, "final_backup_result", {"success": False})
    monkeypatch.setattr(service, "_fetch_release", lambda: {"has_update": True, "size": archive.stat().st_size, "latest_version": "99.0.0"})
    monkeypatch.setattr(service, "_download", lambda _info, dest: shutil.copy2(archive, dest))
    monkeypatch.setattr(service.external_probe, "detect_external_bds", lambda: (False, None))
    monkeypatch.setattr(service.lifecycle, "stop_and_wait", lambda _tag: True)
    service._update_worker()
    assert service.last_progress()["phase"] == "error"
    for name, value in original.items():
        assert (root / name).read_bytes() == value
    assert not state.manager.op_lock.locked()


def test_fallo_antes_de_crear_job_tambien_tiene_resultado_terminal(monkeypatch, tmp_path):
    monkeypatch.setattr(service.config, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(service, "_early_progress", None)
    monkeypatch.setattr(service, "_area", lambda: (_ for _ in ()).throw(ValueError("Área no segura")))
    monkeypatch.setattr(state.manager, "op_lock", threading.Lock())
    state.manager.op_lock.acquire()
    monkeypatch.setattr(state.manager, "suite_update_in_progress", True)
    service._update_worker()
    assert service.last_progress()["phase"] == "error"
    assert not state.manager.op_lock.locked()


def test_progreso_inicial_no_reutiliza_exito_de_operacion_anterior(tmp_path, monkeypatch):
    monkeypatch.setattr(service.config, "BASE_DIR", str(tmp_path))
    release.write_json(tmp_path / "data/suite_updates/recovery/progress.json", {"phase": "complete"})
    monkeypatch.setattr(service, "_early_progress", {"phase": "downloading"})
    assert service.last_progress()["phase"] == "downloading"


@pytest.mark.skipif(os.name != "nt", reason="junction de Windows")
def test_area_de_recuperacion_junction_no_se_lee_ni_reemplaza(tmp_path, monkeypatch):
    target, outside = tmp_path / "target", tmp_path / "outside"
    area = target / "data/suite_updates"
    area.mkdir(parents=True)
    outside.mkdir()
    release.write_json(outside / "progress.json", {"phase": "complete", "detail": "NO LEER"})
    job = area / "recovery"
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(job), str(outside)], capture_output=True)
    assert result.returncode == 0, result.stderr
    monkeypatch.setattr(service.config, "BASE_DIR", str(target))
    monkeypatch.setattr(service, "_early_progress", None)
    try:
        with pytest.raises(ValueError, match="enlace"):
            service._job_path()
        assert service.last_progress() == {"phase": "idle"}
        assert json.loads((outside / "progress.json").read_text(encoding="utf-8"))["detail"] == "NO LEER"
    finally:
        job.rmdir()  # retira solo la junction creada por esta prueba.


def test_auxiliar_fallo_de_arranque_ejecuta_rollback(tmp_path, monkeypatch):
    root = tmp_path / "target"
    job = root / "data/suite_updates/recovery"
    stage = job / "stage"
    make_tree(root, "2.0.0")
    make_tree(stage, "2.1.0")
    before = {k: v for k, v in snapshot(root).items() if not k.startswith("data/")}
    release.prepare_update(stage, root, job)
    release.write_json(job / "request.json", {"target": str(root), "parent_pid": 0, "parent_created": 0,
                                               "from_version": "2.0.0", "port": 8000, "restart_bds": False})
    monkeypatch.setattr(suite_updater, "other_installation_processes", lambda _root: [])
    monkeypatch.setattr(suite_updater, "launch_gui", lambda *_args: None)
    monkeypatch.setattr(suite_updater, "terminate_owned", lambda _process: None)
    monkeypatch.setattr(suite_updater, "wait_healthy", lambda *_args, **kwargs: bool(kwargs.get("legacy")))
    assert suite_updater.run_job(job) == 1
    after = {k: v for k, v in snapshot(root).items() if not k.startswith("data/")}
    assert after == before
    assert json.loads((job / "progress.json").read_text(encoding="utf-8"))["phase"] == "rolled_back"
