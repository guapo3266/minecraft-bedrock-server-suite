"""Coherencia del producto, los manifiestos y los contratos HTTP/WS."""

import json
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient

from gui_backend import __version__, state
import server_gui_server as gui
from suite_version import VERSION
from tools.set_version import check_version, set_version


ROOT = Path(__file__).resolve().parents[1]


def test_version_comun_en_manifiestos_y_changelog():
    assert check_version() == []
    assert __version__ == VERSION
    assert gui.app.openapi()["info"]["version"] == VERSION


def test_status_http_y_ws_separan_suite_y_bds(monkeypatch):
    monkeypatch.setattr(state, "get_hardware_metrics", lambda: {})
    for installed in (None, "1.26.43.1"):
        monkeypatch.setattr(gui.manager, "installed_version", installed)
        # Los tres consumidores (HTTP, init WS y broadcast WS) comparten este builder.
        payload = state.build_public_status(gui.manager)
        assert payload["suite_version"] == VERSION
        assert payload["installed_version"] == installed
        with TestClient(gui.app, client=("127.0.0.1", 50000)) as client:
            response = client.get("/api/status")
        assert response.status_code == 200
        assert response.json()["suite_version"] == VERSION
        assert response.json()["installed_version"] == installed


def test_version_no_depende_del_directorio_de_trabajo(tmp_path):
    code = f"import sys; sys.path.insert(0, {str(ROOT)!r}); from suite_version import VERSION; print(VERSION)"
    result = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True, check=True)
    assert result.stdout.strip() == VERSION


def test_actualizar_version_conserva_dependencias_y_detecta_changelog_pendiente(tmp_path):
    for name in ("version.json", "gui_frontend/package.json", "gui_frontend/package-lock.json", "CHANGELOG.md"):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    lock_path = tmp_path / "gui_frontend/package-lock.json"
    previous = json.loads(lock_path.read_text(encoding="utf-8"))
    set_version("987.654.321", tmp_path)
    updated = json.loads(lock_path.read_text(encoding="utf-8"))
    assert updated["version"] == updated["packages"][""]["version"] == "987.654.321"
    assert {k: v for k, v in updated["packages"].items() if k} == {
        k: v for k, v in previous["packages"].items() if k
    }
    assert check_version(tmp_path) == ["Falta la entrada ## [987.654.321] - AAAA-MM-DD en CHANGELOG.md."]
    with (tmp_path / "CHANGELOG.md").open("a", encoding="utf-8") as stream:
        stream.write("\n## [987.654.321] - 2026-10-15\n")
    assert check_version(tmp_path) == []
