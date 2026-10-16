r"""Prueba el EXE real en una copia temporal, sin BDS ni datos del servidor.

Ejecutar con el entorno de desarrollo (requests y websockets), tras el build:
    .venv\Scripts\python.exe tools/verify_portable.py
Conserva evidencia bajo build/portable/qa; nunca opera sobre portable/SuiteMinecraft.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import time
import zipfile

import requests
from websockets.sync.client import connect


ROOT = Path(__file__).resolve().parents[1]


def wait_until(function, timeout=30):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        result = function()
        if result:
            return result
        time.sleep(0.2)
    raise AssertionError("Se agoto el tiempo de espera del portable")


def main():
    source = ROOT / "portable" / "SuiteMinecraft"
    qa = ROOT / "build" / "portable" / "qa" / str(time.time_ns())
    base = qa / "Suite movida con espacios y acentos á"
    shutil.copytree(source, base)
    assert not list(base.rglob("bedrock_server.exe"))
    checks = []
    exe = base / "SuiteMinecraft.exe"
    host = base / "SuiteMinecraftHost.exe"
    # No Python/Node en PATH, cwd fuera de la instalacion y entorno heredado limpio.
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GUI_", "WRAPPER_", "PYTHON", "LMSTUDIO_"))}
    env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    env["WRAPPER_LANG"] = "es"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env["GUI_PORT"] = str(port)
    url = f"http://127.0.0.1:{port}"
    session = requests.Session()
    session.trust_env = False
    session.headers["Origin"] = url
    log_path = qa / "gui.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen([str(host), "--no-browser"], cwd=qa, env=env,
                                   stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            def ready():
                if process.poll() is not None:
                    raise AssertionError(log_path.read_text(encoding="utf-8"))
                try:
                    response = session.get(url + "/api/setup_status", timeout=1)
                    return response.json() if response.ok else False
                except requests.ConnectionError:
                    return False

            setup = wait_until(ready)
            assert setup == {"required": True, "bds_installed": False}, setup
            checks.append("Host EXE movido, cwd ajeno, sin Python/Node en PATH, wizard sin BDS")
            index = session.get(url, timeout=5)
            index.raise_for_status()
            for asset in re.findall(r'(?:src|href)="(/assets/[^\"]+)"', index.text):
                session.get(url + asset, timeout=5).raise_for_status()
            session.get(url + "/favicon.svg", timeout=5).raise_for_status()
            checks.append("Frontend React, JS, CSS y favicon servidos desde _internal")
            assert session.get(url + "/api/status", timeout=5).ok
            assert session.get(url + "/api/addons", timeout=5).ok
            assert session.get(url + "/api/status", headers={"Host": "evil.example"}, timeout=5).status_code == 403
            assert session.post(url + "/api/command", headers={"Origin": "https://evil.example"}, json={"command": "stop"}, timeout=5).status_code == 403
            checks.append("API de estado y addons; guards Host/Origin devuelven 403")
            with connect(f"ws://127.0.0.1:{port}/ws", origin=url, proxy=None, open_timeout=5) as ws:
                assert json.loads(ws.recv(timeout=5))["type"] == "init"
                ws.send(json.dumps({"type": "ping"}))
                for _ in range(10):
                    if json.loads(ws.recv(timeout=5))["type"] == "pong":
                        break
                else:
                    raise AssertionError("WebSocket sin pong")
            checks.append("WebSocket real: init y ping/pong")

            # Mundo sintetico: se comprueba el contenido exacto del ZIP y del restore.
            world = base / "worlds" / "MundoPrueba"
            world.mkdir(parents=True)
            original = b"SOLO QA PORTABLE - NO ES UN MUNDO REAL\x00\xff"
            (world / "level.dat").write_bytes(original)
            (base / "server.properties").write_text("level-name=MundoPrueba\nbackup-inicio=false\n", encoding="utf-8")
            snapshot = qa / "snapshot.json"
            snapshot.write_text(json.dumps([["level.dat", len(original)]]), encoding="utf-8")
            result_path = qa / "result.json"
            worker = subprocess.run([str(host), "--internal-backup-worker", str(snapshot),
                                     str(qa / "cancel.mark"), str(result_path)],
                                    cwd=qa, env=env, capture_output=True, timeout=30,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            (qa / "worker.log").write_bytes(worker.stdout + worker.stderr)
            assert worker.returncode == 0, worker.stdout + worker.stderr
            result = json.loads(result_path.read_text(encoding="utf-8"))
            assert result["error"] is None and result["zip"], result
            backup = Path(result["zip"])
            assert backup.parent == base / "backups", backup
            with zipfile.ZipFile(backup) as zf:
                assert zf.testzip() is None
                entry = next(name for name in zf.namelist() if name.endswith("level.dat"))
                assert zf.read(entry) == original
            checks.append("Worker EXE separado: snapshot JSON, ZIP valido en backups/ y bytes exactos")
            assert any(b["filename"] == backup.name for b in session.get(url + "/api/backups", timeout=5).json()["backups"])
            verify = session.post(url + f"/api/backups/{backup.name}/verify", timeout=10)
            assert verify.ok and verify.json()["status"] == "ok", verify.text
            (world / "level.dat").write_bytes(b"MODIFICADO PARA PROBAR RESTORE")
            restore = session.post(url + "/api/restore", json={"filename": backup.name}, timeout=20)
            assert restore.ok and restore.json()["status"] == "ok", restore.text
            assert (world / "level.dat").read_bytes() == original
            checks.append("GUI empaquetada: lista y verifica ZIP; restore recupera bytes originales")

            # Sin BDS, el wrapper debe fallar limpiamente y liberar su sesion.
            start = session.post(url + "/api/action/start", timeout=5)
            assert start.ok and start.json()["status"] == "starting", start.text
            event_dir = base / "data" / "wrapper_events"
            wait_until(lambda: list(event_dir.glob("*.ndjson")))
            events = wait_until(lambda: [p for p in event_dir.glob("*.ndjson") if "wrapper_started" in p.read_text(encoding="utf-8")])
            assert events
            wait_until(lambda: not session.get(url + "/api/status", timeout=5).json()["running"])
            assert process.poll() is None
            checks.append("GUI lanza wrapper EXE; evento NDJSON; salida sin BDS libera sesion")
            # JSON ilegible debe devolver fallo retryable y no relanzar la GUI.
            bad_result = qa / "bad-result.json"
            bad = subprocess.run([str(host), "--internal-backup-worker", str(qa / "missing.json"),
                                  str(qa / "cancel.mark"), str(bad_result)],
                                 cwd=qa, env=env, capture_output=True, timeout=20,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
            assert bad.returncode == 1
            assert json.loads(bad_result.read_text(encoding="utf-8"))["error"].startswith("Snapshot:")
            checks.append("Worker con snapshot ausente: exit 1 y contrato Snapshot: conservado")
        finally:
            process.terminate()
            process.wait(timeout=10)
            session.close()
    report = {"ejecutable_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
              "host_sha256": hashlib.sha256(host.read_bytes()).hexdigest(),
              "carpeta_qa": str(base), "bds_ejecutado": False, "comprobaciones": checks}
    report_path = ROOT / "portable" / "VERIFICACION.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
