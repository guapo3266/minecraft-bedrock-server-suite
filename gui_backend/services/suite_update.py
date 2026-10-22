"""Consulta Releases oficiales y prepara el relevo a un instalador externo."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
from urllib.parse import urljoin, urlsplit

import psutil
import requests

from console_lang import L
from gui_backend import config
from gui_backend.services import external_probe, lifecycle
from gui_backend.state import manager
from suite_release import ASSET_NAME, REPOSITORY, extract_package, prepare_update, sha256, write_json
from suite_updater import process_alive, update_mutex
from suite_version import VERSION

API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
MAX_DOWNLOAD = 512 * 1024 * 1024
_cache_lock = threading.Lock()
_cache = {"at": 0.0, "value": None}
_exit_callback = None
_port = None
_handoff_guard = False
_early_progress = None


def configure_runtime(callback, port):
    global _exit_callback, _port
    _exit_callback, _port = callback, port


def enter_handoff_guard():
    global _handoff_guard
    if not os.environ.get("SUITE_UPDATE_BOOT_TOKEN"):
        return
    try:
        journal = json.loads((_job_path() / "journal.json").read_text(encoding="utf-8"))
        if journal["phase"] == "checking":
            if not manager.op_lock.acquire(blocking=False):
                raise ValueError("Operación inesperada durante el relevo")
            manager.suite_update_in_progress = True
            _handoff_guard = True
    except FileNotFoundError:
        pass


def release_handoff_guard():
    """Libera el guard de relevo cuando el diario dice "complete". True si lo libero.

    La llaman /api/suite_update/health y el loop de metricas (cada ~2 s, mismo
    hilo del event loop). Antes solo la llamada de health del auxiliar lo
    liberaba: si esa unica llamada fallaba, la GUI nueva quedaba con op_lock
    tomado y todo POST en 409 hasta reiniciarla (2026-10-20). Un diario
    ilegible en ese instante no rompe el endpoint: se reintenta despues.
    """
    global _handoff_guard
    if not _handoff_guard:
        return False
    try:
        journal = json.loads((_job_path() / "journal.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(journal, dict) or journal.get("phase") != "complete":
        return False
    _handoff_guard = False
    manager.suite_update_in_progress = False
    manager.op_lock.release()
    return True


def _area():
    root = Path(config.BASE_DIR).absolute()
    current = root
    for name in (None, "data", "suite_updates"):
        if name:
            current /= name
        if current.exists() and (current.is_symlink() or getattr(current.lstat(), "st_file_attributes", 0) & 0x400):
            raise ValueError("Área de actualización con un enlace no permitido")
    return current


# Fases que solo avanzan con una actualizacion viva (esta GUI o el auxiliar).
_ACTIVE_PHASES = frozenset({"downloading", "verifying", "stopping", "waiting_gui",
                            "applying", "checking", "rolling_back"})


def _update_alive(job):
    """True si alguien puede seguir escribiendo progress.json: esta GUI o su auxiliar."""
    if manager.suite_update_in_progress:
        return True
    try:
        request = json.loads((job / "request.json").read_text(encoding="utf-8"))
        return process_alive(request.get("helper_pid", 0), request.get("helper_created", 0))
    except Exception:
        return False


def _stale_progress(job, phase):
    """Resultado real de una fase activa que ya nadie avanza, segun el diario.

    El aviso de progreso puede quedar atrasado aunque la operacion terminara:
    el auxiliar de 2.1.0 no reintenta el reemplazo y, si la GUI leia
    progress.json en ese instante, el ultimo aviso no se guardaba con la
    actualizacion ya completada. journal.json es la fuente autoritativa.
    """
    try:
        journal_phase = json.loads((job / "journal.json").read_text(encoding="utf-8")).get("phase")
    except (OSError, ValueError, AttributeError):
        journal_phase = None
    if journal_phase in ("complete", "rolled_back"):
        # Sin "version": no debe disparar la recarga del navegador.
        return {"phase": journal_phase, "interrupted_phase": phase}
    if journal_phase in (None, "prepared"):
        return {"phase": "error", "interrupted_phase": phase,
                "detail": L("La actualización anterior se interrumpió antes de reemplazar el programa. Puedes volver a intentarla.",
                            "The previous update was interrupted before replacing the program. You can try it again.")}
    return {"phase": "rollback_failed", "interrupted_phase": phase,
            "detail": L("La actualización anterior quedó a medias. Cierra la GUI y ejecuta Recuperar_suite.bat (o vuelve a abrir iniciar_gui.bat) para recuperar la versión anterior.",
                        "The previous update was left halfway. Close the GUI and run Recuperar_suite.bat (or reopen iniciar_gui.bat) to restore the previous version.")}


def last_progress():
    if _early_progress is not None:
        return dict(_early_progress)
    try:
        job = _job_path()
        value = json.loads((job / "progress.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"phase": "idle"}
    # Una fase activa sin nadie que la avance es residuo: GUI cerrada a mitad,
    # auxiliar que no llego a arrancar o un ultimo aviso que no se pudo guardar.
    # Devolverla tal cual dejaba la ventana "en curso" para siempre, con
    # Instalar y Comprobar deshabilitados (2026-10-20).
    if isinstance(value, dict) and value.get("phase") in _ACTIVE_PHASES and not _update_alive(job):
        return _stale_progress(job, value["phase"])
    return value


def _job_path():
    job = _area() / "recovery"
    for path in (job, job / "progress.json", job / "journal.json", job / "request.json"):
        if path.exists() and (path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400):
            raise ValueError("No se permite un enlace en la carpeta de recuperación")
    if job.exists() and not job.is_dir():
        raise ValueError("La carpeta de recuperación tiene un tipo inesperado")
    return job


def installation_block():
    if (Path(config.BASE_DIR) / ".git").exists():
        return "git_checkout"
    if _exit_callback is None:
        return "launcher_required"
    return None


def _version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", value):
        raise ValueError("Versión estable inválida")
    return tuple(map(int, value.split(".")))


def _fetch_release():
    with requests.get(API_URL, timeout=(5, 15), allow_redirects=False,
                      headers={"Accept": "application/vnd.github+json", "User-Agent": "BedrockSuite/" + VERSION}) as response:
        if response.status_code == 404:
            return {"state": "no_release", "has_update": False}
        response.raise_for_status()
        payload = response.json()
    version = str(payload.get("tag_name", "")).removeprefix("v")
    _version_tuple(version)
    if payload.get("draft") or payload.get("prerelease"):
        raise ValueError("La entrega no es estable")
    assets = [a for a in payload.get("assets", []) if a.get("name") == ASSET_NAME]
    if len(assets) != 1:
        raise ValueError("Falta el ZIP Windows x64 de la entrega")
    asset = assets[0]
    expected_url = f"https://github.com/{REPOSITORY}/releases/download/v{version}/{ASSET_NAME}"
    if asset.get("browser_download_url") != expected_url:
        raise ValueError("El ZIP no pertenece a la entrega esperada")
    digest = asset.get("digest", "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("GitHub no proporcionó un SHA-256 verificable")
    size = asset.get("size")
    if type(size) is not int or not 0 < size <= MAX_DOWNLOAD:
        raise ValueError("Tamaño de descarga inválido")
    return {"state": "available", "latest_version": version, "has_update": _version_tuple(version) > _version_tuple(VERSION),
            "url": expected_url, "release_url": f"https://github.com/{REPOSITORY}/releases/tag/v{version}",
            "sha256": digest[7:], "size": size}


def check_release(refresh=False):
    with _cache_lock:
        # Incluso los clics manuales comparten una pausa corta para no agotar la API.
        age = time.monotonic() - _cache["at"]
        if _cache["value"] is None or age > (30 if refresh else 3600):
            try:
                _cache["value"] = _fetch_release()
            except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                _cache["value"] = {"state": "unavailable", "has_update": None, "detail": str(exc)}
            _cache["at"] = time.monotonic()
        info = dict(_cache["value"])
    info.update(current_version=VERSION, install_block=installation_block(), progress=last_progress())
    # El checksum y la URL de descarga no son argumentos aceptados por POST.
    return info


def _download(info, destination):
    url = info["url"]
    allowed_hosts = {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
    for _ in range(6):
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname not in allowed_hosts or parsed.port not in (None, 443)
                or parsed.username or parsed.password or parsed.fragment):
            raise ValueError("Redirección de descarga fuera de GitHub")
        with requests.get(url, stream=True, timeout=(5, 30), allow_redirects=False) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                url = urljoin(url, response.headers.get("Location", ""))
                continue
            response.raise_for_status()
            total = 0
            with Path(destination).open("xb") as stream:
                for block in response.iter_content(1024 * 1024):
                    total += len(block)
                    if total > min(info["size"], MAX_DOWNLOAD):
                        raise ValueError("La descarga excede el tamaño autorizado")
                    stream.write(block)
                stream.flush()
                os.fsync(stream.fileno())
            if total != info["size"] or sha256(destination) != info["sha256"]:
                raise ValueError("El ZIP descargado no supera su comprobación SHA-256")
            return
    raise ValueError("Demasiadas redirecciones")


def start_update():
    global _early_progress
    block = installation_block()
    if block:
        raise ValueError(block)
    _job_path()
    if not manager.op_lock.acquire(blocking=False):
        raise ValueError("busy")
    if manager.suite_update_in_progress or manager.backup_in_progress or manager.restart_in_progress or manager.update_in_progress:
        manager.op_lock.release()
        raise ValueError("busy")
    manager.suite_update_in_progress = True
    _early_progress = {"phase": "downloading"}
    try:
        threading.Thread(target=_update_worker, daemon=True).start()
        manager.update_status()
    except Exception:
        manager.suite_update_in_progress = False
        manager.op_lock.release()
        raise


def _archive_job(candidate, history):
    """Mueve el trabajo anterior (recovery/) a history (previous_*).

    Normalmente es un rename. Pero una GUI relanzada por el auxiliar de 2.2.0
    o anterior tiene abierto recovery/gui.log como stdout toda su vida: el
    rename fallaba (WinError 32) y shutil.move dejaba una copia previous_* a
    medias en cada reintento, sin salida (2026-10-21). Se mueve entrada por
    entrada; un archivo abierto se copia y queda en su sitio. Una carpeta que
    no se puede mover sigue siendo un error.
    """
    try:
        os.replace(candidate, history)
        return
    except OSError:
        pass
    history.mkdir()
    for entry in list(candidate.iterdir()):
        try:
            os.replace(entry, history / entry.name)
        except OSError:
            if not entry.is_file():
                raise
            shutil.copy2(entry, history / entry.name)


def _update_worker():
    global _early_progress
    root = Path(config.BASE_DIR)
    mutex = update_mutex(root)
    handed_off = False
    job = None
    was_running = manager.is_running
    try:
        if not mutex.acquire(timeout_ms=0):
            raise ValueError("Otra GUI está preparando una actualización")
        area = _area()
        candidate = _job_path()
        if candidate.exists():
            request_path = candidate / "request.json"
            if request_path.exists():
                previous = json.loads(request_path.read_text(encoding="utf-8"))
                if process_alive(previous.get("helper_pid", 0), previous.get("helper_created", 0)):
                    raise ValueError("El auxiliar de otra actualización sigue activo")
            if (candidate / "journal.json").exists():
                phase = json.loads((candidate / "journal.json").read_text(encoding="utf-8"))["phase"]
                if phase not in {"complete", "rolled_back", "prepared"}:
                    raise ValueError("Primero recupera la actualización pendiente con Recuperar_suite.bat")
            history = area / ("previous_" + os.urandom(8).hex())
            assert candidate.absolute().is_relative_to(area.absolute()) and history.absolute().is_relative_to(area.absolute())
            _archive_job(candidate, history)
        job = candidate
        job.mkdir(parents=True, exist_ok=True)
        write_json(job / "progress.json", {"phase": "downloading"})
        _early_progress = None
        info = _fetch_release()  # POST vuelve a consultar; nunca confía en el navegador.
        if not info.get("has_update"):
            raise ValueError("No hay una nueva entrega estable verificable")
        if shutil.disk_usage(root).free < info["size"] * 4 + 256 * 1024 * 1024:
            raise ValueError("Espacio insuficiente para descarga, runtime auxiliar y rollback")
        archive = job / ASSET_NAME
        _download(info, archive)
        write_json(job / "progress.json", {"phase": "verifying"})
        stage = job / "stage"
        manifest = extract_package(archive, stage, info["latest_version"])
        if manifest.get("dirty") is not False:
            raise ValueError("El paquete no procede de un checkout limpio")
        helper = job / "helper"
        helper.mkdir()
        shutil.copytree(stage / "runtime", helper / "runtime")
        for name in ("suite_updater.py", "suite_release.py", "zip_safety.py", "console_lang.py", "windows_process_guard.py"):
            shutil.copy2(root / name, helper / name)
        prepare_update(stage, root, job)
        external, _ = external_probe.detect_external_bds()
        if external:
            raise ValueError("Hay un servidor externo en esta instalación")
        write_json(job / "progress.json", {"phase": "stopping"})
        if not lifecycle.stop_and_wait("[Actualizador de suite]"):
            raise ValueError("No se pudo detener Minecraft y su wrapper")
        if was_running:
            end = time.monotonic() + 5
            while manager.final_backup_result is None and time.monotonic() < end:
                time.sleep(.1)
            result = manager.final_backup_result
            if not result or result.get("success") is not True or not result.get("zip") or not Path(result["zip"]).is_file():
                raise ValueError("El backup final no pudo verificarse; no se reemplazó código")
        request = {"target": str(root.absolute()), "parent_pid": os.getpid(),
                   "parent_created": psutil.Process().create_time(), "old_python": sys.executable,
                   "restart_bds": bool(was_running), "port": _port, "from_version": VERSION}
        write_json(job / "request.json", request)
        with (job / "helper.log").open("ab") as log:
            process = subprocess.Popen([str(helper / "runtime/python.exe"), "-B", str(helper / "suite_updater.py"), "--job", str(job)],
                                       cwd=helper, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        request.update(helper_pid=process.pid, helper_created=psutil.Process(process.pid).create_time())
        write_json(job / "request.json", request)
        write_json(job / "progress.json", {"phase": "waiting_gui", "version": info["latest_version"]})
        _exit_callback()
        handed_off = True
    except Exception as exc:
        detail = str(exc)
        if was_running and not manager.is_running:
            detail += ". Minecraft quedó detenido; puedes iniciarlo desde la GUI."
        if job and job.exists():
            write_json(job / "progress.json", {"phase": "error", "detail": detail})
        else:
            _early_progress = {"phase": "error", "detail": detail}
    finally:
        mutex.close()
        if not handed_off:
            manager.suite_update_in_progress = False
            manager.op_lock.release()
            manager.update_status()
