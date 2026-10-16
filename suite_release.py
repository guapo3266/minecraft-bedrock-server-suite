"""Formato de entrega y actualización transaccional de código; nunca datos BDS."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import zipfile

from zip_safety import _is_safe_zip_entry

MANIFEST = "suite_release_manifest.json"
REPOSITORY = "guapo3266/minecraft-bedrock-server-suite"
ASSET_NAME = "BedrockSuite-Windows-x64.zip"
MAX_BYTES = 1024 ** 3
MAX_FILES = 15000
VERSION_RE = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")
ROOT_FILES = frozenset("""addon_inventory.py addon_inventory_cli.py auto_backup.py
backup_worker.py console_lang.py restore_backup.py restore_core.py server_gui_server.py
server_properties.py server_wrapper.py suite_version.py suite_release.py suite_updater.py
windows_process_guard.py wrapper_backup.py wrapper_console.py wrapper_events.py
wrapper_schedule.py wrapper_state.py zip_safety.py iniciar_gui.bat iniciar_gui_lan.bat
iniciar_servidor.bat configurar_antivirus.bat configurar_firewall.bat Recuperar_suite.bat
requirements.txt version.json server.properties.example README.md CHANGELOG.md LICENSE
LEEME_WINDOWS.txt suite_release_manifest.json""".split())
TOOL_FILES = frozenset("""bds_first_run.py enable_beta_apis.py enable_beta_apis_v2.py
update_items.py update_items_v2.py verify_backups.py setup_defender_exclusions.ps1""".split())


def managed_path(name):
    """Lista positiva adicional a zip-slip/NTFS; no depende de .gitignore."""
    if not isinstance(name, str) or not name or "\\" in name or not _is_safe_zip_entry(name):
        return False
    parts = name.split("/")
    if any(not p or p.startswith(".") or any(ord(c) < 32 for c in p) for p in parts):
        return False
    if any(p.casefold() in {"bedrock_server.exe", "server.properties", "permissions.json", "allowlist.json",
                            "worlds", "backups", "data", "config", "resource_packs", "behavior_packs"} for p in parts):
        return False
    return (name in ROOT_FILES
            or (name.startswith("gui_backend/") and name.endswith(".py"))
            or name.startswith(("gui_frontend/dist/", "gui_frontend/public/", "web/", "runtime/"))
            or name.startswith("licenses/")
            or name in {"gui_frontend/src/appearance/NOTICE.md", "gui_frontend/src/vendor/NOTICE.md"}
            or (len(parts) == 2 and parts[0] == "tools" and parts[1] in TOOL_FILES))


def safe_path(root, name):
    if not managed_path(name):
        raise ValueError(f"Archivo fuera del programa: {name!r}")
    root = Path(os.path.abspath(root))
    path = root / name
    # Sin resolve() previo: resolver ocultaría una junction.
    current = root
    for part in [None, *name.split("/")]:
        if part is not None:
            current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError(f"Enlace/reparse point no permitido: {current}")
    return path


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp_" + os.urandom(4).hex())
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def validate_manifest(value):
    if (not isinstance(value, dict) or value.get("schema") != 1
            or value.get("repository") != REPOSITORY or value.get("platform") != "windows-x64"
            or not isinstance(value.get("version"), str) or not VERSION_RE.fullmatch(value["version"])):
        raise ValueError("Manifiesto de entrega incompatible")
    files = value.get("files")
    if not isinstance(files, dict) or not 1 <= len(files) <= MAX_FILES:
        raise ValueError("Inventario de entrega inválido")
    names = set()
    total = 0
    for name, item in files.items():
        if name == MANIFEST or not managed_path(name) or name.casefold() in names:
            raise ValueError(f"Entrada de manifiesto rechazada: {name}")
        names.add(name.casefold())
        if (not isinstance(item, dict) or type(item.get("size")) is not int or item["size"] < 0
                or not isinstance(item.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])):
            raise ValueError("Tamaño o hash inválido")
        total += item["size"]
    if total > MAX_BYTES or not {"version.json", "server_gui_server.py", "suite_updater.py", "runtime/python.exe"} <= files.keys():
        raise ValueError("Entrega incompleta o demasiado grande")
    # Un archivo nunca puede ser a la vez padre de otro (también sin distinguir mayúsculas).
    for name in names:
        if any("/".join(name.split("/")[:i]) in names for i in range(1, len(name.split("/")))):
            raise ValueError("Colisión archivo/directorio")
    return value


def read_manifest(root):
    path = safe_path(root, MANIFEST)
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("Manifiesto excesivo")
    return validate_manifest(json.loads(path.read_text(encoding="utf-8")))


def verify_tree(root, manifest=None):
    manifest = manifest or read_manifest(root)
    for name, item in manifest["files"].items():
        path = safe_path(root, name)
        if not path.is_file() or path.stat().st_size != item["size"] or sha256(path) != item["sha256"]:
            raise ValueError(f"Integridad incorrecta: {name}")
    if json.loads(safe_path(root, "version.json").read_text(encoding="utf-8"))["version"] != manifest["version"]:
        raise ValueError("La versión no coincide con el manifiesto")
    return manifest


def extract_package(archive, destination, expected_version):
    """Valida el inventario entero antes de escribir; después valida cada hash."""
    destination = Path(destination)
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("El staging debe estar vacío")
    with zipfile.ZipFile(archive) as package:
        infos = package.infolist()
        if not 1 <= len(infos) <= MAX_FILES + 1 or sum(i.file_size for i in infos) > MAX_BYTES:
            raise ValueError("Límites de expansión excedidos")
        names = set()
        for info in infos:
            name = info.filename
            if (info.is_dir() or not managed_path(name) or name.casefold() in names
                    or stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1):
                raise ValueError(f"Entrada ZIP rechazada: {name}")
            names.add(name.casefold())
        if MANIFEST not in package.namelist() or package.getinfo(MANIFEST).file_size > 4 * 1024 * 1024:
            raise ValueError("Falta un manifiesto válido")
        manifest = validate_manifest(json.loads(package.read(MANIFEST)))
        if manifest["version"] != expected_version or set(package.namelist()) != set(manifest["files"]) | {MANIFEST}:
            raise ValueError("Versión o inventario ZIP distinto del manifiesto")
        for info in infos:
            if info.filename != MANIFEST and info.file_size != manifest["files"][info.filename]["size"]:
                raise ValueError("Tamaño declarado distinto del inventario")
        destination.mkdir(parents=True, exist_ok=True)
        for info in infos:
            path = safe_path(destination, info.filename)
            path.parent.mkdir(parents=True, exist_ok=True)
            with package.open(info) as src, path.open("xb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
    return verify_tree(destination, manifest)


def prepare_update(stage, target, job):
    stage, target, job = map(Path, (stage, target, job))
    if (target / ".git").exists():
        raise ValueError("La actualización automática no reemplaza un checkout Git")
    manifest = verify_tree(stage)
    old = read_manifest(target)["files"] if (target / MANIFEST).exists() else {}
    inventory = dict(manifest["files"])
    inventory[MANIFEST] = {"size": (stage / MANIFEST).stat().st_size, "sha256": sha256(stage / MANIFEST)}
    operations = []
    untouched = {}
    for name in sorted(set(inventory) | set(old)):
        path = safe_path(target, name)
        safe_path(stage, name)
        if path.exists() and not path.is_file():
            raise ValueError(f"El destino no es un archivo: {name}")
        previous = sha256(path) if path.exists() else None
        expected = inventory.get(name, {}).get("sha256")
        if previous == expected:
            if previous is not None:
                untouched[name] = previous
            continue
        if expected is None and previous != old[name]["sha256"]:
            raise ValueError(f"Archivo obsoleto modificado localmente: {name}")
        operations.append({"path": name, "old_sha256": previous, "new_sha256": expected,
                           "started": False, "backed_up": False})
    required = sum((safe_path(target, op["path"]).stat().st_size if op["old_sha256"] else 0)
                   + (inventory.get(op["path"], {}).get("size", 0)) for op in operations)
    if shutil.disk_usage(target).free < required + 64 * 1024 * 1024:
        raise ValueError("Espacio insuficiente para actualización y rollback")
    journal = {"schema": 1, "target": str(target.absolute()), "stage": str(stage.absolute()),
               "version": manifest["version"], "phase": "prepared", "operations": operations,
               "untouched": untouched}
    write_json(job / "journal.json", journal)
    return journal


def _atomic_copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".suite_tmp_" + os.urandom(4).hex())
    try:
        with Path(source).open("rb") as src, tmp.open("xb") as dst:
            shutil.copyfileobj(src, dst, 1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()


def apply_update(job, journal):
    job = Path(job)
    target, stage = Path(journal["target"]), Path(journal["stage"])
    verify_tree(stage)
    journal["phase"] = "applying"
    write_json(job / "journal.json", journal)
    for op in journal["operations"]:
        path = safe_path(target, op["path"])
        backup = safe_path(job / "previous", op["path"])
        current = sha256(path) if path.exists() else None
        if current != op["old_sha256"]:
            raise ValueError(f"El destino cambió durante la preparación: {op['path']}")
        if current is not None:
            _atomic_copy(path, backup)
            if sha256(backup) != current:
                raise ValueError("Resguardo incompleto")
            op["backed_up"] = True
        op["started"] = True
        write_json(job / "journal.json", journal)
        if op["new_sha256"] is None:
            path.unlink()
        else:
            _atomic_copy(safe_path(stage, op["path"]), path)
            if sha256(path) != op["new_sha256"]:
                raise ValueError("El archivo instalado no coincide")
    verify_tree(target)
    journal["phase"] = "checking"
    write_json(job / "journal.json", journal)


def rollback_update(job, journal):
    """Restaura solo lo empezado; conserva todos los resguardos, incluso al fallar."""
    job = Path(job)
    target = Path(journal["target"])
    errors = []
    for op in reversed(journal["operations"]):
        if not op["started"]:
            continue
        try:
            path = safe_path(target, op["path"])
            backup = safe_path(job / "previous", op["path"])
            if op["old_sha256"]:
                if not op["backed_up"] or not backup.is_file() or sha256(backup) != op["old_sha256"]:
                    raise ValueError("Resguardo ausente o alterado")
                _atomic_copy(backup, path)
                if sha256(path) != op["old_sha256"]:
                    raise ValueError("No se pudo verificar la recuperación")
            elif path.exists():
                if sha256(path) != op["new_sha256"]:
                    raise ValueError("El archivo nuevo cambió; se conserva para revisión")
                path.unlink()
        except (OSError, ValueError) as exc:
            errors.append(f"{op['path']}: {exc}")
    for name, expected in journal.get("untouched", {}).items():
        try:
            if sha256(safe_path(target, name)) != expected:
                errors.append(f"Archivo ajeno al reemplazo modificado durante la operación: {name}")
        except (OSError, ValueError) as exc:
            errors.append(f"{name}: {exc}")
    journal["phase"] = "rollback_failed" if errors else "rolled_back"
    journal["rollback_errors"] = errors
    write_json(job / "journal.json", journal)
    if errors:
        raise ValueError("; ".join(errors))
