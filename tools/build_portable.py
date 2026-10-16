"""Construye un portable privado por lista permitida, sin copiar la instalacion.

Uso (Windows): powershell -ExecutionPolicy Bypass -File crear_portable.ps1
Requiere Node solo durante el build. El resultado incluye el runtime de Python.
"""

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def validate_payload(folder):
    """No publicar datos de instalacion, fuentes de tests ni binarios BDS."""
    forbidden = {
        "bedrock_server.exe", "bedrock_server.pdb", "bedrock_server_symbols.pdb",
        "bedrock_server_how_to.html", "server.properties", "permissions.json",
        "allowlist.json", "worlds", "backups", "data", "config", "resource_packs",
        "behavior_packs", "tests", "node_modules", ".venv", "agents.md",
    }
    for file in folder.rglob("*"):
        if file.name.lower() in forbidden:
            raise RuntimeError(f"Archivo no permitido en el portable: {file.relative_to(folder)}")
        if file.is_symlink() or file.stat().st_file_attributes & 0x400:
            raise RuntimeError(f"Enlace/reparse point no permitido: {file}")


def main():
    if sys.platform != "win32":
        raise SystemExit("El portable se construye en Windows.")
    npm = shutil.which("npm.cmd")
    if not npm:
        raise SystemExit("Se necesita Node.js/npm para reconstruir gui_frontend/dist.")
    subprocess.run([npm, "run", "build"], cwd=ROOT / "gui_frontend", check=True)
    work = ROOT / "build" / "portable"
    frontend_env = dict(os.environ, VITE_SUITE_PORTABLE="1")
    subprocess.run([npm, "run", "build", "--", "--outDir", str(work / "frontend"), "--emptyOutDir"], cwd=ROOT / "gui_frontend", env=frontend_env, check=True)
    # El host tiene utilidades (p. ej. Poppler) en PATH con DLL ICU homonimas.
    # PyInstaller debe resolver las dependencias contra Windows/Python/Qt.
    build_env = dict(os.environ)
    build_env["PATH"] = os.pathsep.join([
        str(Path(sys.executable).parent), str(Path(sys.base_prefix)),
        str(Path(os.environ["SystemRoot"]) / "System32"), os.environ["SystemRoot"],
    ])
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--distpath", str(work / "dist"), "--workpath", str(work / "work"),
        str(ROOT / "packaging" / "SuiteMinecraft.spec"),
    ], cwd=ROOT, env=build_env, check=True)
    bundle = work / "dist" / "SuiteMinecraft"
    shutil.copy2(ROOT / "server.properties.example", bundle)
    shutil.copy2(ROOT / "LICENSE", bundle)
    shutil.copy2(ROOT / "packaging" / "LEEME_PORTABLE.md", bundle / "LEEME.md")
    notices = bundle / "LICENCIAS"
    notices.mkdir(exist_ok=True)
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata["Name"]
        if name.lower() in {"pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "pefile", "packaging", "setuptools", "pip"}:
            continue
        for entry in distribution.files or ():
            rel = str(entry).replace("\\", "/")
            if ".dist-info/licenses/" in rel or (".dist-info/" in rel and Path(entry).name.lower().startswith(("license", "copying", "notice"))):
                src = Path(distribution.locate_file(entry))
                if src.is_file():
                    target = notices / name / Path(entry).name
                    target.parent.mkdir(exist_ok=True)
                    shutil.copy2(src, target)
    validate_payload(bundle)
    manifest = {
        "producto": "SuiteMinecraft", "uso": "personal, no publicado",
        "incluye_bds": False, "python": sys.version.split()[0],
        "ventana_propia": True, "motor_web_incluido": True, "ia_visible": False,
        "dependencias_build": dict(sorted(
            (d.metadata["Name"], d.version) for d in importlib.metadata.distributions()
        )),
        "archivos": {
            p.relative_to(bundle).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(bundle.rglob("*")) if p.is_file()
        },
    }
    (bundle / "MANIFIESTO.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    output = ROOT / "portable"
    output.mkdir(exist_ok=True)
    destination = output / "SuiteMinecraft"
    # Un rebuild conserva la carpeta anterior entera, incluso sus datos de usuario.
    if destination.exists():
        if destination.resolve().parent != output.resolve():
            raise RuntimeError("El destino de reemplazo debe estar dentro de portable/.")
        previous = output / ("SuiteMinecraft_anterior_" + time.strftime("%Y%m%d_%H%M%S") + "_" + str(time.time_ns()))
        destination.rename(previous)
    shutil.copytree(bundle, destination)
    archive = output / "SuiteMinecraft-portable.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(destination.rglob("*")):
            if file.is_file():
                zf.write(file, file.relative_to(output))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(digest + "  " + archive.name + "\n", encoding="ascii")
    print(f"Portable privado: {destination}")
    print(f"ZIP sin BDS: {archive}")


if __name__ == "__main__":
    main()
