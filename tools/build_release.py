"""Construye un ZIP público con CPython incluido, sin datos ni binarios BDS."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from suite_release import ASSET_NAME, MANIFEST, REPOSITORY, managed_path, safe_path, sha256, verify_tree, write_json  # noqa: E402


def build(output, allow_dirty=False):
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=True)
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT))
    if dirty and not allow_dirty:
        raise ValueError("El build publicable exige un checkout limpio; usa --allow-dirty solo para QA local.")
    pin = json.loads((ROOT / "release_python.json").read_text(encoding="utf-8"))
    cache = output / ("python-" + pin["version"] + "-embed.zip")
    if not cache.exists() or sha256(cache) != pin["sha256"]:
        with urllib.request.urlopen(pin["url"], timeout=60) as response, cache.open("wb") as stream:
            shutil.copyfileobj(response, stream, 1024 * 1024)
    if sha256(cache) != pin["sha256"]:
        raise ValueError("El runtime descargado no coincide con el SHA-256 oficial fijado.")
    with tempfile.TemporaryDirectory(prefix="suite_build_", dir=output) as temp:
        package = Path(temp)
        assert package.is_relative_to(output)
        runtime = package / "runtime"
        runtime.mkdir()
        with zipfile.ZipFile(cache) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                dest = safe_path(package, "runtime/" + info.filename)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(archive.read(info))
        minor = "".join(pin["version"].split(".")[:2])
        (runtime / f"python{minor}._pth").write_text(
            f"python{minor}.zip\n.\nLib/site-packages\n..\nimport site\n", encoding="utf-8")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check", "--no-compile",
                        "--only-binary=:all:", "--python-version", ".".join(pin["version"].split(".")[:2]),
                        "--platform", "win_amd64", "--implementation", "cp", "--abi", "cp" + minor,
                        "--target", str(runtime / "Lib/site-packages"), "-r", str(ROOT / "requirements-release.txt")], check=True)
        # Algunos wheels incluyen tests, cachés e instrucciones de desarrollo;
        # no forman parte del runtime ni se distribuyen con nuestra aplicación.
        extras = [p for p in runtime.rglob("*") if p.name in {".agents", "tests", "__pycache__"}]
        for extra in sorted(extras, key=lambda p: len(p.parts), reverse=True):
            if extra.is_dir():
                assert extra.absolute().is_relative_to(package.absolute())
                shutil.rmtree(extra)
        tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
        for name in tracked:
            if not name or name == MANIFEST or not managed_path(name) or name.startswith("runtime/"):
                continue
            src, dst = safe_path(ROOT, name), safe_path(package, name)
            if src.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        # Incluye módulos nuevos durante QA antes de su primer commit.
        if allow_dirty:
            for name in subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=ROOT).decode().split("\0"):
                if name and managed_path(name) and name != MANIFEST and not name.startswith("runtime/"):
                    dst = safe_path(package, name)
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(safe_path(ROOT, name), dst)
        lock = json.loads((ROOT / "gui_frontend/package-lock.json").read_text(encoding="utf-8"))
        modules = (ROOT / "gui_frontend/node_modules").resolve()
        for name, metadata in lock["packages"].items():
            if not name.startswith("node_modules/") or metadata.get("dev"):
                continue
            installed = ROOT / "gui_frontend" / name
            if not installed.is_dir() or not installed.resolve().is_relative_to(modules):
                raise ValueError(f"Falta una dependencia frontend local verificable: {name}")
            for notice in installed.iterdir():
                if notice.is_file() and notice.name.upper().startswith(("LICENSE", "COPYING", "COPYRIGHT")):
                    if not notice.resolve().is_relative_to(modules):
                        raise ValueError("Un aviso de licencia apunta fuera de node_modules")
                    relative = "licenses/frontend/" + name.removeprefix("node_modules/").replace("/", "__") + "/" + notice.name
                    dest = safe_path(package, relative)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(notice, dest)
        (package / "LEEME_WINDOWS.txt").write_text(
            "Minecraft Bedrock Server Suite\n\nExtrae el ZIP completo y abre iniciar_gui.bat.\n"
            "Incluye Python y dependencias: no requiere Python, Git ni Node instalados.\n"
            "Minecraft/BDS se descarga desde Mojang mediante el asistente inicial.\n"
            "Se recomienda una ruta corta, por ejemplo C:\\BedrockSuite, para evitar límites de Windows.\n"
            "Para actualizar, usa Actualizar la suite en la GUI. Los mundos y configuraciones se conservan.\n"
            "Si una actualización se interrumpe, vuelve a abrir iniciar_gui.bat o Recuperar_suite.bat.\n",
            encoding="utf-8")
        files = {}
        for path in sorted(package.rglob("*")):
            if path.is_file():
                name = path.relative_to(package).as_posix()
                if not managed_path(name):
                    raise ValueError(f"Archivo inesperado en el paquete: {name}")
                files[name] = {"size": path.stat().st_size, "sha256": sha256(path)}
        manifest = {"schema": 1, "repository": REPOSITORY, "platform": "windows-x64",
                    "version": json.loads((ROOT / "version.json").read_text(encoding="utf-8"))["version"],
                    "python": pin["version"], "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip(),
                    "dirty": dirty, "files": files}
        write_json(package / MANIFEST, manifest)
        verify_tree(package)
        archive_path = output / ASSET_NAME
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in sorted(package.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(package).as_posix())
        digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        (output / (ASSET_NAME + ".sha256")).write_text(f"{digest}  {ASSET_NAME}\n", encoding="ascii")
        print(json.dumps({"zip": str(archive_path), "sha256": digest, "version": manifest["version"],
                          "files": len(files), "dirty": dirty}, indent=2))
    return archive_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "output/releases")
    parser.add_argument("--allow-dirty", action="store_true")
    options = parser.parse_args()
    build(options.output, options.allow_dirty)
