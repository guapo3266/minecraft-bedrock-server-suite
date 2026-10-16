"""Actualiza o comprueba la versión común de la suite sin publicar ni crear tags."""

import argparse
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
STABLE_VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def check_version(root=ROOT):
    """Devuelve los desajustes entre la fuente, npm y la entrada del changelog."""
    version = read_json(root / "version.json")["version"]
    errors = []
    if not isinstance(version, str) or not STABLE_VERSION.fullmatch(version):
        errors.append("version.json debe declarar una versión estable X.Y.Z.")
    package = read_json(root / "gui_frontend/package.json")
    lock = read_json(root / "gui_frontend/package-lock.json")
    for name, value in (
        ("package.json", package["version"]),
        ("package-lock.json", lock["version"]),
        ("package-lock.json packages['']", lock["packages"][""]["version"]),
    ):
        if value != version:
            errors.append(f"{name}: {value!r}; se esperaba {version!r}.")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    if not any(line.startswith(f"## [{version}] - ") for line in changelog.splitlines()):
        errors.append(f"Falta la entrada ## [{version}] - AAAA-MM-DD en CHANGELOG.md.")
    return errors


def set_version(version, root=ROOT):
    """Valida y carga todos los manifiestos antes de escribirlos."""
    if not STABLE_VERSION.fullmatch(version):
        raise ValueError("Usa una versión estable X.Y.Z sin ceros iniciales (por ejemplo, 2.0.1).")
    manifest_path = root / "version.json"
    package_path = root / "gui_frontend/package.json"
    lock_path = root / "gui_frontend/package-lock.json"
    manifest, package, lock = map(read_json, (manifest_path, package_path, lock_path))
    manifest["version"] = package["version"] = lock["version"] = version
    lock["packages"][""]["version"] = version
    for path, value in ((manifest_path, manifest), (package_path, package), (lock_path, lock)):
        path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true", help="Comprobar manifiestos y changelog.")
    action.add_argument("version", nargs="?", help="Nueva versión estable X.Y.Z.")
    args = parser.parse_args()
    try:
        if args.check:
            errors = check_version()
            for error in errors:
                print(error)
            if errors:
                return 1
            print(f"Versión coherente: {read_json(ROOT / 'version.json')['version']}")
        else:
            set_version(args.version)
            print(f"Versión actualizada a {args.version}. Añade su entrada al CHANGELOG.md y reconstruye el frontend.")
    except (OSError, KeyError, TypeError, ValueError) as exc:
        parser.exit(1, f"Error de versionado: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
