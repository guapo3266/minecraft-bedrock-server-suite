"""Actualización del BDS oficial: consulta a Mojang, descarga, staging, rollback.

Pipeline COMPARTIDO entre la acción update_bds y el setup inicial (first-run).
No conoce Request/FastAPI/decoradores; las dependencias (requests, config,
estado) se leen por atributo de módulo para que los monkeypatches de los tests
sigan vivos.
"""

import glob
import json
import os
import re
import shutil
import tempfile
import time
import zipfile

import requests

from console_lang import L
from gui_backend import config
from gui_backend.security import _is_safe_zip_entry
from gui_backend.state import manager


def _version_tuple(version: str):
    """Convierte '1.21.30.03' en (1, 21, 30, 3) para comparar versiones semánticamente."""
    parts = []
    for p in str(version).split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])

MOJANG_DOWNLOAD_API = "https://net-secondary.web.minecraft-services.net/api/v1.0/download/links"
MOJANG_DOWNLOAD_PAGE = "https://www.minecraft.net/en-us/download/server/bedrock"
_UA_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def _fetch_latest_bedrock_download():
    """Devuelve (url, version) de la ultima version estable de BDS, o (None, None).

    Fuente primaria: la API interna que usa la propia web de Mojang
    (/api/v1.0/download/links), que devuelve JSON con los links oficiales
    (verificado en vivo 2026-08-04). El HTML de la pagina ya no expone el
    link del zip, asi que el scrape queda solo como ultimo recurso.
    """
    try:
        r = requests.get(MOJANG_DOWNLOAD_API, headers=_UA_HEADERS, timeout=5)
        if r.status_code == 200:
            for link in r.json().get("result", {}).get("links", []):
                if link.get("downloadType") == "serverBedrockWindows":
                    url = link.get("downloadUrl") or ""
                    match = re.search(r"bedrock-server-(\d+\.\d+\.\d+\.\d+)\.zip", url)
                    if match:
                        return url, match.group(1)
    except Exception:
        pass
    # Ultimo recurso: scrape de la pagina oficial (fragil, puede dejar de funcionar).
    try:
        r = requests.get(MOJANG_DOWNLOAD_PAGE, headers=_UA_HEADERS, timeout=5)
        if r.status_code == 200:
            match = re.search(r'https://[^\s"]+?bedrock-server-(\d+\.\d+\.\d+\.\d+)\.zip', r.text)
            if match:
                return match.group(0), match.group(1)
    except Exception:
        pass
    return None, None


def _resolve_update_root(staging_dir):
    """Resuelve la raiz efectiva del staging extraido (D3).

    El zip oficial actual es plano (validado con bedrock-server-1.26.33.2:
    9761 entradas, bedrock_server.exe en la raiz), pero algunas distribuciones
    envuelven el contenido en una unica carpeta raiz (p.ej.
    'bedrock-server-X.Y.Z.W/'). Se acepta solo esa forma inequivoca; cualquier
    estructura ambigua sigue fallando cerrada. Lanza RuntimeError si no hay
    bedrock_server.exe en ninguna de las dos formas.
    """
    update_root = staging_dir
    if not os.path.exists(os.path.join(update_root, "bedrock_server.exe")):
        top_entries = os.listdir(staging_dir)
        top_dirs = [
            name for name in top_entries
            if os.path.isdir(os.path.join(staging_dir, name))
        ]
        top_files = [
            name for name in top_entries
            if os.path.isfile(os.path.join(staging_dir, name))
        ]
        if len(top_dirs) == 1 and not top_files:
            candidate = os.path.join(staging_dir, top_dirs[0])
            if os.path.exists(os.path.join(candidate, "bedrock_server.exe")):
                update_root = candidate

    if not os.path.exists(os.path.join(update_root, "bedrock_server.exe")):
        raise RuntimeError(
            "El zip descargado no contiene bedrock_server.exe; se aborta sin tocar la instalacion."
        )
    return update_root


def _is_preserved_update_path(rel, preserve_files, preserve_dirs):
    """True si una ruta relativa del zip de actualizacion no debe reemplazarse."""
    rel_norm = rel.replace("\\", "/")
    return rel_norm in preserve_files or any(
        rel_norm.startswith(d + "/") for d in preserve_dirs
    )


_UPDATE_MANIFEST_NAME = ".bds_update_manifest.json"
_PREVIOUS_META_NAME = "bds_previous.json"

# Resguardo persistente de la ultima version anterior (solo una; se reemplaza
# en cada update/rollback). Dato de instalacion: vive en data/ (ignorado).
PREVIOUS_VERSION_DIR = os.path.join(config.BASE_DIR, "data", "bds_previous")

# Archivos de control que nunca se aplican al sustituir una instalacion (el
# zip oficial no los trae; solo existen dentro de resguardos/previous).
_SKIP_IN_STAGING = {_UPDATE_MANIFEST_NAME, _PREVIOUS_META_NAME}

# Lo que una actualizacion (y por tanto un rollback) JAMAS toca.
PRESERVE_FILES = {"server.properties", "permissions.json", "allowlist.json", "whitelist.json"}
PRESERVE_DIRS = {"worlds", "backups", "web", "gui_frontend"}


def recover_interrupted_updates(base_dir=None):
    """Recupera una actualización interrumpida antes de aceptar operaciones.

    `_apply_staged_update` escribe un manifiesto antes de mover el primer
    binario. Si el proceso muere entre las dos fases, el manifiesto permite
    quitar archivos nuevos y devolver exactamente los archivos que existían.
    Un directorio antiguo sin manifiesto se conserva para inspección manual.
    """
    if base_dir is None:
        base_dir = config.BASE_DIR
    pattern = os.path.join(base_dir, "bds_update_prev_*")
    for prev_dir in glob.glob(pattern):
        if not os.path.isdir(prev_dir):
            continue
        manifest_path = os.path.join(prev_dir, _UPDATE_MANIFEST_NAME)
        if not os.path.isfile(manifest_path):
            continue
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                entries = json.load(f)
            if not isinstance(entries, list):
                raise ValueError("manifiesto no es una lista")

            for entry in entries:
                rel = entry.get("path") if isinstance(entry, dict) else None
                had_previous = entry.get("had_previous") if isinstance(entry, dict) else None
                if not isinstance(rel, str) or not isinstance(had_previous, bool) or not _is_safe_zip_entry(rel):
                    raise ValueError("entrada invalida en manifiesto")
                target = os.path.abspath(os.path.join(base_dir, rel.replace("/", os.sep)))
                if os.path.commonpath([os.path.abspath(base_dir), target]) != os.path.abspath(base_dir):
                    raise ValueError("ruta fuera de la instalacion")
                if os.path.isfile(target):
                    os.remove(target)
                if had_previous:
                    old_path = os.path.join(prev_dir, rel.replace("/", os.sep))
                    if os.path.isfile(old_path):
                        os.makedirs(os.path.dirname(target), exist_ok=True)
                        os.replace(old_path, target)
            shutil.rmtree(prev_dir, ignore_errors=True)
        except Exception as exc:
            # No borrar un resguardo que no se pudo interpretar: conserva la
            # posibilidad de recuperación manual y evita agravar el incidente.
            print(f"[Actualizador BDS] No se pudo recuperar {os.path.basename(prev_dir)}: {exc}")


def _save_prev_dir(prev_dir, keep_prev_dir, prev_version):
    """Conserva el resguardo como version anterior: lo mueve atómico, quita
    el manifiesto (solo sirve para la recuperación de crashes) y escribe la
    metadata de version."""
    if os.path.isdir(keep_prev_dir):
        shutil.rmtree(keep_prev_dir, ignore_errors=True)
    os.makedirs(os.path.dirname(keep_prev_dir), exist_ok=True)
    os.replace(prev_dir, keep_prev_dir)
    manifest_path = os.path.join(keep_prev_dir, _UPDATE_MANIFEST_NAME)
    if os.path.isfile(manifest_path):
        os.remove(manifest_path)
    meta_tmp = os.path.join(keep_prev_dir, _PREVIOUS_META_NAME + ".tmp")
    with open(meta_tmp, "w", encoding="utf-8") as f:
        json.dump({"version": prev_version, "saved_at": time.strftime("%Y-%m-%d %H:%M:%S")}, f)
    os.replace(meta_tmp, os.path.join(keep_prev_dir, _PREVIOUS_META_NAME))


def read_previous_version():
    """(hay_resguardo, version_guardada). Version None = desconocida (la GUI
    no llego a ver el log de BDS antes de actualizar). Nunca lanza."""
    prev_dir = PREVIOUS_VERSION_DIR
    if not os.path.isdir(prev_dir):
        return False, None
    try:
        names = os.listdir(prev_dir)
    except OSError:
        return False, None
    if not any(n != _PREVIOUS_META_NAME for n in names):
        return False, None
    try:
        with open(os.path.join(prev_dir, _PREVIOUS_META_NAME), encoding="utf-8") as f:
            version = json.load(f).get("version")
        return True, version if isinstance(version, str) else None
    except (OSError, ValueError, AttributeError):
        # Sin metadata legible el resguardo sigue siendo aplicable
        return True, None


def _apply_staged_update(staging_dir, base_dir, preserve_files, preserve_dirs,
                         keep_prev_dir=None, prev_version=None,
                         preserve_staging_on_failure=False):
    """Aplica un staging extraido a base_dir con rollback ante fallo.

    Fase 1: mueve los archivos actuales que seran reemplazados a un dir
    temporal (mismo volumen). Fase 2: mueve los nuevos desde el staging
    (os.replace, atomico por archivo). Si algo falla en la fase 2, se restauran
    los archivos resguardados y los ya aplicados vuelven a su sitio en el
    staging: la instalacion nunca queda con binarios de versiones mezcladas.

    Con `keep_prev_dir`, el resguardo de los binarios salientes se conserva
    alli como "version anterior" (rollback de un clic) en lugar de borrarse.

    `preserve_staging_on_failure=True` (flujo rollback, donde el staging ES el
    resguardo) impide que un fallo a mitad destruya el staging: los archivos
    aplicados se devuelven a el y no se borra el directorio, de modo que el
    rollback pueda reintentarse.
    """
    prev_dir = tempfile.mkdtemp(prefix="bds_update_prev_", dir=base_dir)
    applied = []  # rutas relativas ya movidas del staging al destino
    failed = False
    try:
        manifest = []
        for root, _dirs, names in os.walk(staging_dir):
            for n in names:
                if n in _SKIP_IN_STAGING:
                    continue
                rel = os.path.relpath(os.path.join(root, n), staging_dir)
                if _is_preserved_update_path(rel, preserve_files, preserve_dirs):
                    continue
                target = os.path.join(base_dir, rel)
                manifest.append({
                    "path": rel.replace("\\", "/"),
                    "had_previous": os.path.isfile(target),
                })
        manifest_tmp = os.path.join(prev_dir, _UPDATE_MANIFEST_NAME + ".tmp")
        with open(manifest_tmp, "w", encoding="utf-8") as f:
            json.dump(manifest, f)
        os.replace(manifest_tmp, os.path.join(prev_dir, _UPDATE_MANIFEST_NAME))

        # Fase 1: resguardar los actuales que seran reemplazados
        for root, _dirs, names in os.walk(staging_dir):
            for n in names:
                if n in _SKIP_IN_STAGING:
                    continue
                rel = os.path.relpath(os.path.join(root, n), staging_dir)
                if _is_preserved_update_path(rel, preserve_files, preserve_dirs):
                    continue
                target = os.path.join(base_dir, rel)
                if os.path.isfile(target):
                    prev_target = os.path.join(prev_dir, rel)
                    os.makedirs(os.path.dirname(prev_target), exist_ok=True)
                    os.replace(target, prev_target)

        # Fase 2: aplicar los nuevos
        for root, _dirs, names in os.walk(staging_dir):
            for n in names:
                if n in _SKIP_IN_STAGING:
                    continue
                rel = os.path.relpath(os.path.join(root, n), staging_dir)
                if _is_preserved_update_path(rel, preserve_files, preserve_dirs):
                    continue
                target = os.path.join(base_dir, rel)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                os.replace(os.path.join(root, n), target)
                applied.append(rel)
    except Exception:
        failed = True
        # Rollback del rollback: los aplicados vuelven AL STAGING (no se
        # borran). En el flujo update el staging se descarta igual en el
        # finally; en el flujo rollback el staging es el resguardo y asi
        # conserva sus binarios para reintentar.
        for rel in applied:
            try:
                staging_back = os.path.join(staging_dir, rel)
                os.makedirs(os.path.dirname(staging_back), exist_ok=True)
                os.replace(os.path.join(base_dir, rel), staging_back)
            except OSError:
                # Sin poder devolverlo, la restauracion de prev_dir de abajo
                # pisa el destino con el archivo original: base queda igual.
                pass
        for root, _dirs, names in os.walk(prev_dir):
            for n in names:
                rel = os.path.relpath(os.path.join(root, n), prev_dir)
                if rel.replace("\\", "/") == _UPDATE_MANIFEST_NAME:
                    continue
                target = os.path.join(base_dir, rel)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                os.replace(os.path.join(root, n), target)
        raise
    finally:
        if failed and preserve_staging_on_failure:
            # El staging es el resguardo anterior: conservarlo integro.
            pass
        else:
            shutil.rmtree(staging_dir, ignore_errors=True)
        if keep_prev_dir and not failed:
            _save_prev_dir(prev_dir, keep_prev_dir, prev_version)
        else:
            shutil.rmtree(prev_dir, ignore_errors=True)


def _download_and_install_bds(tag="[Actualizador BDS]", log_fn=None):
    """Descarga el BDS oficial y lo aplica a BASE_DIR con staging + rollback.

    Pipeline COMPARTIDO entre update_bds y el setup inicial (first-run):
    descarga con tope de tamano (400 MB), extraccion anti zip-slip, resolucion
    de la raiz del zip (_resolve_update_root) y aplicacion con rollback
    (_apply_staged_update). Los errores operativos quedan en el log y la
    funcion devuelve (False, None); solo las excepciones inesperadas se
    propagan al llamador. La limpieza del zip temporal y del staging ocurre
    en el finally (todos los caminos).

    `log_fn(msg, tipo)`: destino de los mensajes de progreso. Por defecto usa
    manager.add_log (GUI); el primer arranque por consola pasa print.
    """
    if log_fn is None:
        log_fn = manager.add_log
    temp_zip = os.path.join(config.BASE_DIR, "bds_update.zip")
    staging_dir = None
    downloaded_version = None
    try:
        url, downloaded_version = _fetch_latest_bedrock_download()
        if not url:
            log_fn(L(f"{tag} No se pudo obtener la URL de descarga oficial. Abortando.", f"{tag} Could not get the official download URL. Aborting."), "error")
            return False, None

        log_fn(L(f"{tag} Descargando binarios desde Mojang...", f"{tag} Downloading binaries from Mojang..."), "system")
        # S3: límite de tamaño de descarga para no llenar el disco
        max_bytes = 400 * 1024 * 1024
        dl = requests.get(url, headers=_UA_HEADERS, stream=True, timeout=30)
        content_length = dl.headers.get("Content-Length")
        try:
            if content_length and int(content_length) > max_bytes:
                log_fn(L(f"{tag} Descarga demasiado grande ({content_length} bytes). Abortando.", f"{tag} Download too large ({content_length} bytes). Abortando."), "error")
                return False, None
        except (TypeError, ValueError):
            pass
        total_bytes = 0
        total_known = None
        try:
            if content_length:
                total_known = int(content_length)
        except (TypeError, ValueError):
            total_known = None
        # R3: progreso real de descarga cada 10 MB (la fase mas larga: sin
        # estas lineas la GUI parece congelada durante la descarga).
        next_progress_mb = 10
        with open(temp_zip, "wb") as f:
            for chunk in dl.iter_content(chunk_size=8192):
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    log_fn(L(f"{tag} Descarga excede el límite de 400 MB. Abortando.", f"{tag} Download exceeds the 400 MB limit. Aborting."), "error")
                    return False, None
                f.write(chunk)
                if total_bytes >= next_progress_mb * 1024 * 1024:
                    next_progress_mb += 10
                    mb = total_bytes // (1024 * 1024)
                    if total_known and total_known > 0:
                        pct = total_bytes * 100 // total_known
                        log_fn(L(f"{tag} Descargando... {mb} MB ({pct}%)", f"{tag} Downloading... {mb} MB ({pct}%)"), "system")
                    else:
                        log_fn(L(f"{tag} Descargando... {mb} MB", f"{tag} Downloading... {mb} MB"), "system")

        log_fn(L(f"{tag} Descomprimiendo y actualizando ejecutable...", f"{tag} Extracting and updating executable..."), "system")

        # Staging: nunca se toca la instalacion con un zip a medias.
        staging_dir = os.path.join(config.BASE_DIR, "bds_update_staging")
        shutil.rmtree(staging_dir, ignore_errors=True)
        os.makedirs(staging_dir, exist_ok=True)
        extracted = 0
        with zipfile.ZipFile(temp_zip, "r") as z:
            for item in z.infolist():
                name = item.filename
                # S2: anti zip-slip — rechazar rutas con '..', absolutas o con backslash malicioso
                if not _is_safe_zip_entry(name):
                    log_fn(L(f"{tag} Entrada insegura en el zip ignorada: {name}", f"{tag} Unsafe zip entry ignored: {name}"), "error")
                    continue
                z.extract(item, staging_dir)
                extracted += 1
                # Progreso de extraccion (el zip oficial tiene ~9700 entradas)
                if extracted % 1000 == 0:
                    log_fn(L(f"{tag} Descomprimiendo... {extracted} archivos", f"{tag} Extracting... {extracted} files"), "system")

        # D3: raiz efectiva del staging (zip plano actual o una unica
        # carpeta raiz historica); falla cerrada ante estructuras ambiguas.
        update_root = _resolve_update_root(staging_dir)

        # Aplica con rollback: si algo falla a mitad, la instalacion
        # vuelve a los binarios anteriores (sin versiones mezcladas). El
        # resguardo queda en data/bds_previous para volver con un clic.
        # Nota: si la aplicacion FALLA, el resguardo se descarta (la
        # instalacion queda intacta via rollback interno).
        _apply_staged_update(update_root, config.BASE_DIR, PRESERVE_FILES, PRESERVE_DIRS,
                             keep_prev_dir=PREVIOUS_VERSION_DIR,
                             prev_version=manager.installed_version)
        if downloaded_version:
            manager.installed_version = downloaded_version
        return True, downloaded_version
    finally:
        if os.path.exists(temp_zip):
            try:
                os.remove(temp_zip)
            except Exception:
                pass
        if staging_dir and os.path.exists(staging_dir):
            shutil.rmtree(staging_dir, ignore_errors=True)


def rollback_bds(tag="[Rollback BDS]", log_fn=None):
    """Vuelve a la version anterior guardada en data/bds_previous.

    Reutiliza _apply_staged_update con el resguardo como staging: los
    binarios actuales pasan a ser la NUEVA version anterior (swap simetrico:
    deshacer un rollback es otro rollback). Solo se tocan binarios; worlds/
    server.properties/permissions/allowlist estan en los preserve sets.
    """
    if log_fn is None:
        log_fn = manager.add_log
    has_previous, restore_version = read_previous_version()
    if not has_previous:
        log_fn(L(f"{tag} No hay una versión anterior guardada para restaurar.", f"{tag} There is no saved previous version to restore."), "error")
        return False, None
    version_label = restore_version or "?"
    log_fn(L(f"{tag} Restaurando la versión anterior ({version_label})...", f"{tag} Restoring the previous version ({version_label})..."), "system")
    try:
        _apply_staged_update(PREVIOUS_VERSION_DIR, config.BASE_DIR, PRESERVE_FILES, PRESERVE_DIRS,
                             keep_prev_dir=PREVIOUS_VERSION_DIR,
                             prev_version=manager.installed_version,
                             preserve_staging_on_failure=True)
    except Exception as exc:
        log_fn(L(f"{tag} Error al restaurar; la instalación quedó como estaba: {exc}", f"{tag} Error restoring; the installation was left as it was: {exc}"), "error")
        return False, None
    manager.installed_version = restore_version
    log_fn(L(f"{tag} Versión anterior restaurada ({version_label}). La versión que se dejó de usar ahora es la recuperable.", f"{tag} Previous version restored ({version_label}). The version just left behind is now the recoverable one."), "system")
    return True, restore_version
