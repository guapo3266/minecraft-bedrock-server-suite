"""Contratos del portable: raiz de datos, recursos y despacho de subprocesos."""

import os
import sys

import pytest

import runtime_paths as paths
import suite_minecraft


@pytest.fixture(autouse=True)
def entorno_del_lanzador_aislado(monkeypatch):
    # main fija defaults globales; no deben cambiar el idioma de otros tests.
    for key, default in (("WRAPPER_LANG", "en"), ("LMSTUDIO_MODEL", "qa")):
        monkeypatch.setenv(key, os.environ.get(key, default))


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    base = tmp_path / "Suite Minecraft con espacios"
    resources = base / "_internal"
    resources.mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(resources), raising=False)
    monkeypatch.setattr(sys, "executable", str(base / "SuiteMinecraft.exe"))
    return base, resources


def test_fuente_conserva_rutas_y_comandos_historicos(monkeypatch, tmp_path):
    monkeypatch.delattr(sys, "frozen", raising=False)
    base = str(tmp_path / "Instalacion")
    assert paths.installation_dir() == os.path.dirname(os.path.dirname(__file__))
    assert paths.resource_path("web", base_dir=base) == os.path.join(base, "web")
    assert paths.backup_dir(base) == os.path.abspath(os.path.join(base, "..", "..", "Backups_Minecraft", "auto_backups", "Instalacion"))
    assert paths.process_command("wrapper", base) == [sys.executable, "-u", os.path.join(base, "server_wrapper.py")]


def test_portable_separa_datos_de_recursos_e_ignora_cwd(frozen, monkeypatch, tmp_path):
    base, resources = frozen
    monkeypatch.chdir(tmp_path)
    assert paths.installation_dir() == str(base)
    assert paths.resource_path("web") == str(resources / "web")
    assert paths.backup_dir(str(base)) == str(base / "backups")
    host = str(base / "SuiteMinecraftHost.exe")
    assert paths.process_command("wrapper", str(base)) == [host, "--internal-wrapper"]
    assert paths.process_command("backup-worker", str(base), "s.json", "c", "r.json") == [host, "--internal-backup-worker", "s.json", "c", "r.json"]


@pytest.mark.parametrize("mode,module,args", [
    ("--internal-wrapper", "server_wrapper", []),
    ("--internal-backup-worker", "backup_worker", ["s.json", "c", "r.json"]),
])
def test_despacho_interno_no_abre_gui(monkeypatch, mode, module, args):
    calls = []
    monkeypatch.setattr(sys, "argv", [])
    monkeypatch.setattr(suite_minecraft.runpy, "run_module", lambda name, **kw: calls.append((name, kw, sys.argv.copy())))
    assert suite_minecraft.main([mode, *args]) == 0
    assert calls == [(module, {"run_name": "__main__"}, [module + ".py", *args])]


def test_gui_sin_navegador_usa_carpeta_del_exe(frozen, monkeypatch):
    base, _ = frozen
    calls = []
    monkeypatch.setattr(sys, "argv", [])
    monkeypatch.setenv("GUI_OPEN_BROWSER", "1")
    monkeypatch.setattr(suite_minecraft.runpy, "run_module", lambda name, **kw: calls.append((name, os.getcwd())))
    old_cwd = os.getcwd()
    try:
        assert suite_minecraft.main(["--no-browser"]) == 0
        assert calls == [("server_gui_server", str(base))]
        assert os.environ["GUI_OPEN_BROWSER"] == "0"
    finally:
        os.chdir(old_cwd)


def test_spawn_wrapper_portable_conserva_canal_y_pipes(frozen, monkeypatch):
    from gui_backend import supervisor, config
    from gui_backend.state import manager
    base, _ = frozen
    calls = []
    monkeypatch.setattr(config, "BASE_DIR", str(base))
    monkeypatch.setattr(supervisor.subprocess, "Popen", lambda command, **kw: calls.append((command, kw)))
    for name in ("events_file", "events_alive", "stop_requested"):
        monkeypatch.setattr(manager, name, getattr(manager, name))
    supervisor._spawn_wrapper_process()
    command, kwargs = calls[0]
    assert command == [str(base / "SuiteMinecraftHost.exe"), "--internal-wrapper"]
    assert kwargs["cwd"] == str(base)
    assert kwargs["stdin"] == supervisor.subprocess.PIPE
    assert kwargs["stdout"] == supervisor.subprocess.PIPE
    assert kwargs["env"]["WRAPPER_EVENTS_FILE"].startswith(str(base / "data" / "wrapper_events"))
