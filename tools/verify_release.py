"""QA opt-in: GUI/Python reales, GitHub y wrapper simulados; nunca ejecuta BDS."""

import argparse
import json
import os
import platform
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from suite_release import ASSET_NAME, MANIFEST, extract_package, sha256, write_json  # noqa: E402

OLD_URL = "https://www.python.org/ftp/python/3.13.15/python-3.13.15-embed-amd64.zip"
OLD_HASH = "d1f04d990aee1253d8569e8e5104e30fa9f5fa830899f14843448872d936a2cf"

WRAPPER = r'''import json, os, sys, zipfile
from pathlib import Path
from wrapper_console import _RE_PLAYER_CONNECT, _RE_PLAYER_DISCONNECT, _RE_VERSION, _strip_log_prefix
from wrapper_schedule import _crossed_daily_time
root = Path(__file__).resolve().parent
def emit(event, **data):
    Path(os.environ['WRAPPER_EVENTS_FILE']).parent.mkdir(parents=True, exist_ok=True)
    with open(os.environ['WRAPPER_EVENTS_FILE'], 'a', encoding='utf-8') as f:
        f.write(json.dumps({'event': event, **data}) + '\n')
if __name__ == '__main__':
    emit('wrapper_started')
    emit('version_captured', version='1.99.0.0')
    for line in sys.stdin:
        if line.strip() == 'stop':
            emit('server_stopped')
            path = root / 'data/qa-final.zip'
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr('level.dat', b'QA, no Minecraft')
            emit('final_backup_finished', success=True, zip=str(path))
            break
'''

BOOTSTRAP = r'''import json, runpy, sys
from pathlib import Path
root, archive, version = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
sys.path.insert(0, str(root))
from gui_backend.services import suite_update as service
from suite_release import REPOSITORY, ASSET_NAME, sha256
original = service.requests.get
class Response:
    status_code = 200
    headers = {}
    def __init__(self, payload=None): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def raise_for_status(self): pass
    def json(self): return self.payload
    def iter_content(self, size):
        with archive.open('rb') as f:
            yield from iter(lambda: f.read(size), b'')
url = f'https://github.com/{REPOSITORY}/releases/download/v{version}/{ASSET_NAME}'
payload = {'tag_name': 'v' + version, 'draft': False, 'prerelease': False, 'assets': [
    {'name': ASSET_NAME, 'browser_download_url': url, 'digest': 'sha256:' + sha256(archive), 'size': archive.stat().st_size}]}
def get(address, **kwargs):
    if address == service.API_URL: return Response(payload)
    if address == url: return Response()
    return original(address, **kwargs)
service.requests.get = get
runpy.run_path(str(root / 'server_gui_server.py'), run_name='__main__')
'''


def api(port, route, body=None):
    request = urllib.request.Request(f"http://127.0.0.1:{port}{route}",
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.loads(response.read())


def wait_for(callback, seconds=90):
    end = time.monotonic() + seconds
    last = None
    while time.monotonic() < end:
        try:
            value = callback()
            if value:
                return value
        except (OSError, ValueError) as exc:
            last = exc
        time.sleep(.2)
    raise AssertionError(f"Timeout: {last}")


def manifest_for(root, version):
    manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    manifest.update(version=version, dirty=False)
    (root / "version.json").write_text(json.dumps({"version": version}), encoding="utf-8")
    inventory = {}
    for name in set(manifest["files"]) | {"web/qa-unchanged.js"}:
        path = root / name
        if path.exists():
            inventory[name] = {"size": path.stat().st_size, "sha256": sha256(path)}
    manifest["files"] = inventory
    write_json(root / MANIFEST, manifest)


def pack(root, archive):
    manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
        for name in sorted(set(manifest["files"]) | {MANIFEST}):
            output.write(root / name, name)


def run(archive, output):
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.glob("escenario_*")):
        raise ValueError("Usa una carpeta QA nueva para conservar las evidencias anteriores.")
    old_runtime = output / "python31315.zip"
    with urllib.request.urlopen(OLD_URL, timeout=60) as response, old_runtime.open("wb") as stream:
        shutil.copyfileobj(response, stream, 1024 * 1024)
    assert sha256(old_runtime) == OLD_HASH
    seed = output / "base"
    with zipfile.ZipFile(archive) as original:
        version = json.loads(original.read("version.json"))["version"]
    extract_package(archive, seed, version)
    (seed / "server_wrapper.py").write_text(WRAPPER, encoding="utf-8")
    (seed / "web/qa-unchanged.js").write_bytes(b"conservar mtime")
    bootstrap = output / "bootstrap_qa.py"
    bootstrap.write_text(BOOTSTRAP, encoding="utf-8")
    results = []
    for mode in ("update", "migration", "rollback"):
        failed, migration = mode == "rollback", mode == "migration"
        scenario = output / ("escenario_" + mode)
        target, incoming = scenario / "Instalación con espacios y á", scenario / "entrega"
        shutil.copytree(seed, target)
        shutil.copytree(seed, incoming)
        new_version = "2.1.1" if failed else version
        if failed:
            (incoming / "server_gui_server.py").write_text("raise RuntimeError('Fallo de arranque inyectado por QA')\n", encoding="utf-8")
        manifest_for(incoming, new_version)
        package = scenario / ASSET_NAME
        pack(incoming, package)
        # El escenario exitoso sustituye realmente CPython 3.13.15 por 3.13.16.
        with zipfile.ZipFile(old_runtime) as runtime:
            for info in runtime.infolist():
                if not info.is_dir() and not info.filename.endswith("._pth"):
                    (target / "runtime" / info.filename).write_bytes(runtime.read(info))
        old_version = version if failed else "2.0.0"
        manifest_for(target, old_version)
        initial_files = set(json.loads((target / MANIFEST).read_text(encoding="utf-8"))["files"]) | {MANIFEST}
        if migration:
            runtime_path = target / "runtime"
            assert runtime_path.resolve().is_relative_to(target.resolve())
            shutil.rmtree(runtime_path)
            (target / MANIFEST).unlink()
        sentinels = {"server.properties": b"level-name=MundoQA\nbackup-inicio=false\n",
                     "permissions.json": b"[]", "allowlist.json": b"[]", "worlds/MundoQA/level.dat": b"NO ES UN MUNDO REAL",
                     "resource_packs/personal/manifest.json": b"personal", "data/config.json": b"config local"}
        for name, value in sentinels.items():
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value)
        before = {name: sha256(target / name) for name in initial_files if (target / name).is_file()}
        unchanged_time = (target / "web/qa-unchanged.js").stat().st_mtime_ns
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = os.environ.copy()
        env.update(GUI_PORT=str(port), GUI_OPEN_BROWSER="0", WRAPPER_LANG="es",
                   PATH=os.environ.get("SystemRoot", r"C:\Windows") + r"\System32")
        proc = None
        try:
            with (scenario / "bootstrap.log").open("wb") as log:
                interpreter = sys.executable if migration else str(target / "runtime/python.exe")
                proc = subprocess.Popen([interpreter, "-B", str(bootstrap), str(target), str(package), new_version],
                                        cwd=output, env=env, stdout=log, stderr=subprocess.STDOUT,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            def ready():
                if proc.poll() is not None:
                    raise AssertionError((scenario / "bootstrap.log").read_text(encoding="utf-8", errors="replace")[-3000:])
                return api(port, "/api/suite_update/health")
            initial = wait_for(ready)
            assert initial["python_version"] == (platform.python_version() if migration else "3.13.15"), initial
            started = api(port, "/api/action/start", {})
            assert started.get("status") == "starting", started
            wait_for(lambda: api(port, "/api/status").get("installed_version") == "1.99.0.0", seconds=20)
            info = api(port, "/api/suite_update")
            assert info["has_update"] and info["install_block"] is None, info
            assert api(port, "/api/suite_update", {"confirmed": True})["status"] == "preparing"
            progress_path = target / "data/suite_updates/recovery/progress.json"
            def completed():
                if progress_path.exists():
                    value = json.loads(progress_path.read_text(encoding="utf-8"))
                    if value["phase"] in {"complete", "rolled_back", "restart_failed", "rollback_failed", "error"}:
                        return value
                return False
            outcome = wait_for(completed, seconds=180)
            assert outcome["phase"] == ("rolled_back" if failed else "complete"), outcome
            current = wait_for(lambda: api(port, "/api/suite_update/health"))
            assert current["version"] == (old_version if failed else new_version), current
            assert current["python_version"] == ("3.13.15" if failed else "3.13.16"), current
            assert outcome.get("restart_ok") is True, outcome
            for name, value in sentinels.items():
                assert (target / name).read_bytes() == value, name
            assert (target / "web/qa-unchanged.js").stat().st_mtime_ns == unchanged_time
            if failed:
                assert all(sha256(target / name) == digest for name, digest in before.items())
            assert not (target / "bedrock_server.exe").exists()
            result = {"scenario": mode, "outcome": outcome, "health": current,
                      "protected_files": len(sentinels), "unchanged_mtime": True, "bds_executed": False,
                      "github": "metadata y bytes simulados; validadores reales", "runtime": "Python real y DLLs reemplazadas"}
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
        finally:
            try:
                api(port, "/api/action/stop", {})
                wait_for(lambda: not api(port, "/api/status")["running"], seconds=15)
            except (OSError, AssertionError):
                pass
            for process in psutil.process_iter(["exe", "cmdline"]):
                try:
                    prefix = str(target).casefold()
                    args = [str(a).casefold() for a in (process.info["cmdline"] or [])]
                    if ((process.info["exe"] or "").casefold().startswith(prefix + os.sep)
                            or (proc and process.pid == proc.pid)
                            or any(a == prefix or a.startswith(prefix + os.sep) for a in args)):
                        process.terminate()
                        try:
                            process.wait(timeout=10)
                        except psutil.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=10)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            if proc:
                proc.wait(timeout=10)
    write_json(output / "VERIFICACION.json", {"results": results, "scope": "GUI/Python reales; wrapper y GitHub simulados; sin BDS"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    run(args.archive, args.output)
