"""Auxiliar externo: espera la GUI, aplica, comprueba y recupera una entrega."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import re

import psutil
from console_lang import L

from suite_release import apply_update, rollback_update, write_json, read_manifest
from windows_process_guard import NamedMutex
import hashlib


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def process_alive(pid, created):
    if type(pid) is not int or pid <= 0:
        return False
    try:
        process = psutil.Process(pid)
        return abs(process.create_time() - created) < .01 and process.is_running()
    except psutil.NoSuchProcess:
        return False


def update_mutex(root):
    key = hashlib.sha256(os.path.normcase(str(Path(root).absolute())).encode()).hexdigest()[:24]
    return NamedMutex("BedrockSuiteUpdate_" + key)


def progress(job, phase, **extra):
    value = {"phase": phase, "updated_at": time.time(), **extra}
    write_json(Path(job) / "progress.json", value)


def validate_job(job, target):
    job, target = Path(job).absolute(), Path(target).absolute()
    if job != target / "data/suite_updates/recovery" or (target / ".git").exists():
        raise ValueError("Destino de actualización rechazado")
    current = target
    for part in (None, "data", "suite_updates", "recovery"):
        if part:
            current /= part
        if current.exists() and (current.is_symlink() or getattr(current.lstat(), "st_file_attributes", 0) & 0x400):
            raise ValueError("No se permiten junctions en el área de actualización")
    journal = read_json(job / "journal.json")
    if Path(journal["target"]).absolute() != target or Path(journal["stage"]).absolute() != job / "stage":
        raise ValueError("El diario no corresponde a esta instalación")
    return journal


def other_installation_processes(root):
    root = os.path.normcase(str(Path(root).absolute())) + os.sep
    result = []
    for process in psutil.process_iter(["pid", "name", "exe", "cmdline"]):
        if process.pid == os.getpid():
            continue
        try:
            info = process.info
            name = (info["name"] or "").lower()
            if "python" not in name and name != "bedrock_server.exe":
                continue
            executable = os.path.normcase(info["exe"] or "")
            args = [os.path.normcase(str(a)) for a in (info["cmdline"] or [])]
            if executable.startswith(root) or any(a.startswith(root) for a in args):
                result.append(process.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return result


def launch_gui(root, request, token):
    root = Path(root)
    interpreter = root / "runtime/python.exe"
    if not interpreter.exists():
        interpreter = Path(request["old_python"])
    env = os.environ.copy()
    env.update(GUI_PORT=str(request["port"]), GUI_OPEN_BROWSER="0", SUITE_UPDATE_BOOT_TOKEN=token)
    with (root / "data/suite_updates/recovery/gui.log").open("ab") as log:
        return subprocess.Popen([str(interpreter), "-B", str(root / "server_gui_server.py")], cwd=root, env=env,
                                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def get_json(port, route, body=None):
    request = urllib.request.Request(f"http://127.0.0.1:{port}{route}",
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.loads(response.read(65536))


def wait_healthy(process, port, version, token, timeout=60, legacy=False, root=None):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if process.poll() is not None:
            return False
        try:
            if legacy:
                healthy = get_json(port, "/api/status").get("suite_version") == version
            else:
                status = get_json(port, "/api/suite_update/health")
                healthy = status.get("version") == version and status.get("boot_token") == token
            if healthy:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as response:
                    html = response.read(1024 * 1024).decode("utf-8")
                assets = set(re.findall(r'(?:src|href)="(/assets/[^"?#]+)"', html))
                if assets:
                    inventory = read_manifest(root)["files"] if root and (Path(root) / "suite_release_manifest.json").exists() else None
                    for asset in assets:
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}{asset}", timeout=3) as response:
                            content = response.read(4 * 1024 * 1024 + 1)
                        if not content or len(content) > 4 * 1024 * 1024:
                            raise ValueError("Asset de GUI vacío o excesivo")
                        if inventory:
                            expected = inventory.get("gui_frontend/dist" + asset)
                            if not expected or hashlib.sha256(content).hexdigest() != expected["sha256"]:
                                raise ValueError("La GUI servida no coincide con la entrega")
                    return True
        except (OSError, ValueError):
            pass
        time.sleep(.25)
    return False


def terminate_owned(process):
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def resume_minecraft(request):
    if not request["restart_bds"]:
        return True
    result = get_json(request["port"], "/api/action/start", {})
    if result.get("status") not in {"starting", "already_running"}:
        return False
    end = time.monotonic() + 75
    while time.monotonic() < end:
        status = get_json(request["port"], "/api/status")
        if status.get("running") and status.get("installed_version"):
            return True
        time.sleep(.5)
    return False


def run_job(job):
    job = Path(job).absolute()
    request = read_json(job / "request.json")
    root = Path(request["target"])
    journal = validate_job(job, root)
    end = time.monotonic() + 90
    while process_alive(request["parent_pid"], request["parent_created"]):
        if time.monotonic() >= end:
            progress(job, "error", detail="La GUI anterior no terminó; no se reemplazó código.")
            return 1
        time.sleep(.2)
    mutex = update_mutex(root)
    if not mutex.acquire(timeout_ms=5000):
        mutex.close()
        progress(job, "error", detail="Otra actualización conserva el bloqueo.")
        return 1
    process = None
    try:
        if other_installation_processes(root):
            progress(job, "error", detail="Quedan procesos de esta instalación; no se reemplazó código.")
            return 1
        progress(job, "applying", version=journal["version"])
        apply_update(job, journal)
        progress(job, "checking", version=journal["version"])
        token = os.urandom(24).hex()
        process = launch_gui(root, request, token)
        if not wait_healthy(process, request["port"], journal["version"], token, root=root):
            raise ValueError("La nueva GUI/API no superó la comprobación de arranque.")
        journal["phase"] = "complete"
        write_json(job / "journal.json", journal)
    except Exception as exc:
        terminate_owned(process)
        progress(job, "rolling_back", detail=str(exc))
        try:
            rollback_update(job, journal)
            process = launch_gui(root, request, os.urandom(24).hex())
            if not wait_healthy(process, request["port"], request["from_version"], "", legacy=True, root=root):
                raise ValueError("Código recuperado, pero la GUI anterior no arrancó; revisa gui.log.")
            try:
                restarted = resume_minecraft(request)
            except Exception:
                restarted = False
            progress(job, "rolled_back", detail=str(exc), restart_ok=restarted)
            return 1
        except Exception as recovery_error:
            progress(job, "rollback_failed", detail=str(recovery_error))
            return 2
    finally:
        mutex.close()
    try:
        get_json(request["port"], "/api/suite_update/health")  # libera el guard tras confirmar el arranque.
        restarted = resume_minecraft(request)
    except Exception:
        restarted = False
    progress(job, "complete" if restarted else "restart_failed", version=journal["version"], restart_ok=restarted)
    return 0 if restarted else 3


def recover(root):
    root = Path(root).absolute()
    job = root / "data/suite_updates/recovery"
    if not (job / "journal.json").exists():
        return 0
    journal = validate_job(job, root)
    if journal["phase"] in {"complete", "rolled_back"}:
        return 0
    request = read_json(job / "request.json") if (job / "request.json").exists() else {}
    if process_alive(request.get("helper_pid", 0), request.get("helper_created", 0)):
        raise ValueError("Una actualización sigue activa; espera antes de abrir otra GUI.")
    if journal["phase"] == "prepared":
        return 0
    if other_installation_processes(root):
        raise ValueError("Cierra los procesos de esta instalación antes de recuperar.")
    mutex = update_mutex(root)
    try:
        if not mutex.acquire(timeout_ms=0):
            raise ValueError("La actualización está ocupada")
        rollback_update(job, journal)
        progress(job, "rolled_back", detail="Recuperación de actualización interrumpida. Inicia Minecraft cuando revises la GUI.", restart_ok=False)
    finally:
        mutex.close()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    options = parser.add_mutually_exclusive_group(required=True)
    options.add_argument("--job", type=Path)
    options.add_argument("--recover", type=Path)
    args = parser.parse_args()
    try:
        raise SystemExit(run_job(args.job) if args.job else recover(args.recover))
    except Exception as exc:
        print(L(f"Error de recuperación: {exc}", f"Recovery error: {exc}"), file=sys.stderr)
        raise SystemExit(2)
