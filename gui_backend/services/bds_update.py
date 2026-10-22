"""Actualización del BDS oficial: consulta a Mojang, descarga, staging, rollback.

Pipeline COMPARTIDO entre la acción update_bds y el setup inicial (first-run).
No conoce Request/FastAPI/decoradores; las dependencias (requests, config,
estado) se leen por atributo de módulo para que los monkeypatches de los tests
sigan vivos.
"""

import glob
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import zipfile
from urllib.parse import urljoin, urlsplit

import requests

import windows_process_guard as wpg
import zip_safety
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
_BDS_DOWNLOAD_HOSTS = frozenset({"www.minecraft.net", "minecraft.net"})


def _is_official_bds_url(url: str) -> bool:
    """HTTPS al host oficial, puerto 443 y nombre del ZIP de BDS.

    La lista cerrada falla de forma segura si Mojang cambia de dominio;
    no se amplia a dominios arbitrarios por compatibilidad con mocks.
    """
    if not isinstance(url, str) or any(ord(c) <= 32 for c in url) or "\\" in url:
        return False
    try:
        parts = urlsplit(url)
        allowed = (
            parts.scheme == "https" and parts.hostname in _BDS_DOWNLOAD_HOSTS
            and parts.port in (None, 443) and parts.username is None
            and parts.password is None and not parts.fragment
        )
    except ValueError:
        return False
    return allowed and re.search(
        r"(?:^|/)bedrock-server-\d+\.\d+\.\d+\.\d+\.zip$", parts.path
    ) is not None


def _open_bds_download(url):
    """Abre el stream validando CADA salto antes de contactar su destino."""
    for _hop in range(6):
        if not _is_official_bds_url(url):
            raise ValueError(L("URL de descarga BDS fuera de los hosts oficiales", "BDS download URL outside the official hosts"))
        response = requests.get(
            url, headers=_UA_HEADERS, stream=True, timeout=30, allow_redirects=False,
        )
        if getattr(response, "status_code", 0) not in (301, 302, 303, 307, 308):
            return response
        try:
            location = response.headers.get("Location")
            if not location:
                raise ValueError(L("Redireccion BDS sin destino", "BDS redirect without a destination"))
            url = urljoin(url, location)
        finally:
            close = getattr(response, "close", None)
            if close is not None:
                close()
    raise ValueError(L("Demasiadas redirecciones en la descarga BDS", "Too many redirects in the BDS download"))


def _fetch_latest_bedrock_download():
    """Devuelve (url, version) de la ultima version estable de BDS, o (None, None).

    Fuente primaria: la API interna que usa la propia web de Mojang
    (/api/v1.0/download/links), que devuelve JSON con los links oficiales
    (verificado en vivo 2026-08-04). El HTML de la pagina ya no expone el
    link del zip, asi que el scrape queda solo como ultimo recurso.

    Toda URL candidata pasa por `_is_official_bds_url`: un JSON/HTML
    comprometido o un MITM que devuelva otro host/esquema no se descarga.
    """
    try:
        r = requests.get(MOJANG_DOWNLOAD_API, headers=_UA_HEADERS, timeout=5)
        if r.status_code == 200:
            for link in r.json().get("result", {}).get("links", []):
                if link.get("downloadType") == "serverBedrockWindows":
                    url = link.get("downloadUrl") or ""
                    match = re.search(r"bedrock-server-(\d+\.\d+\.\d+\.\d+)\.zip", url)
                    if match and _is_official_bds_url(url):
                        return url, match.group(1)
    except Exception:
        pass
    # Ultimo recurso: scrape de la pagina oficial (fragil, puede dejar de funcionar).
    try:
        r = requests.get(MOJANG_DOWNLOAD_PAGE, headers=_UA_HEADERS, timeout=5)
        if r.status_code == 200:
            match = re.search(r'https://[^\s"]+?bedrock-server-(\d+\.\d+\.\d+\.\d+)\.zip', r.text)
            if match:
                url = match.group(0)
                if _is_official_bds_url(url):
                    return url, match.group(1)
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

# Configuracion editable que trae el ZIP oficial (2026-10-21). Antes una
# actualizacion o reversion la reemplazaba por la de fabrica y el admin perdia
# sus cambios (modulos de scripting permitidos, limites de paquetes, filtro de
# palabras). Se tratan como los "conffiles" de dpkg: si el archivo instalado
# sigue siendo el de fabrica, se actualiza; si el admin lo edito, se conserva y
# la version nueva de fabrica queda en data/bds_config_defaults/ para comparar.
CONFIG_FILES = ("config/default/permissions.json", "packetlimitconfig.json", "profanity_filter.wlist")
_SHIPPED_CONFIG_NAME = "bds_shipped_config.json"
# Sin huella registrada (instalaciones anteriores a este cambio, o tras una
# reversion) un archivo se da por de fabrica si su fecha esta a menos de esto
# de la de bedrock_server.exe: el instalador extrae el ZIP entero de una vez y
# una edicion posterior cambia la fecha.
_SAME_EXTRACTION_SEC = 600


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _rel_path(root, rel):
    return os.path.join(root, *rel.split("/"))


def shipped_config_path(base_dir):
    """Registro {archivo: sha256 de fabrica instalado} (dato en data/)."""
    return os.path.join(base_dir, "data", _SHIPPED_CONFIG_NAME)


def config_defaults_dir(base_dir):
    """Donde queda la version de fabrica de un archivo que se conservo."""
    return os.path.join(base_dir, "data", "bds_config_defaults")


def read_shipped_config(base_dir):
    try:
        with open(shipped_config_path(base_dir), encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if k in CONFIG_FILES and isinstance(v, str)}


def edited_config_files(base_dir, staging_root):
    """CONFIG_FILES que el admin edito y que el staging cambiaria: se conservan.

    Editado = distinto de la huella de fabrica registrada; sin huella, con una
    fecha lejos de la de bedrock_server.exe. Un archivo que no se puede leer
    tambien se conserva (no se sabe si es de fabrica).
    """
    shipped = read_shipped_config(base_dir)
    exe = os.path.join(base_dir, "bedrock_server.exe")
    keep = set()
    for rel in CONFIG_FILES:
        current, incoming = _rel_path(base_dir, rel), _rel_path(staging_root, rel)
        if not os.path.isfile(current) or not os.path.isfile(incoming):
            continue
        try:
            actual = _sha256_file(current)
            if actual == _sha256_file(incoming):
                continue
        except OSError:
            keep.add(rel)
            continue
        known = shipped.get(rel)
        if known is not None:
            edited = actual != known
        else:
            try:
                edited = abs(os.path.getmtime(current) - os.path.getmtime(exe)) > _SAME_EXTRACTION_SEC
            except OSError:
                edited = True
        if edited:
            keep.add(rel)
    return keep


def _config_hashes(root):
    """Huellas de los CONFIG_FILES presentes en un arbol de BDS (sin lanzar)."""
    hashes = {}
    for rel in CONFIG_FILES:
        try:
            hashes[rel] = _sha256_file(_rel_path(root, rel))
        except OSError:
            continue
    return hashes


def _write_json_atomic(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp_" + os.urandom(4).hex()
    try:
        with open(tmp_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def record_shipped_config(base_dir, hashes):
    """Une al registro las huellas de fabrica recien instaladas."""
    data = read_shipped_config(base_dir)
    data.update(hashes)
    _write_json_atomic(shipped_config_path(base_dir), data)


def forget_shipped_config(base_dir):
    """Tras una reversion la huella de fabrica ya no se conoce: se borra."""
    try:
        os.remove(shipped_config_path(base_dir))
    except FileNotFoundError:
        pass


def save_config_defaults(base_dir, staging_root, keep):
    """Copia a data/bds_config_defaults/ la version de fabrica de lo conservado."""
    for rel in sorted(keep):
        target = _rel_path(config_defaults_dir(base_dir), rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(_rel_path(staging_root, rel), target)


def recover_interrupted_updates(base_dir=None):
    """Recupera una actualización interrumpida antes de aceptar operaciones.

    `_apply_staged_update` escribe un manifiesto antes de mover el primer
    binario. Si el proceso muere entre las dos fases, el manifiesto permite
    quitar archivos nuevos y devolver exactamente los archivos que existían.
    Un directorio antiguo sin manifiesto se conserva para inspección manual.

    Con `staging` en el manifiesto (rollback: el staging ES data/bds_previous),
    los archivos ya aplicados vuelven a ese staging en lugar de borrarse o
    pisarse. Antes el recovery reponía la versión actual encima y el resguardo
    se quedaba sin esos archivos, pero se seguía ofreciendo como válido: un
    segundo rollback mezclaba EXE de una versión y DLL de otra (2026-10-20).
    El formato antiguo (lista de entradas, sin staging) se sigue aceptando.
    """
    if base_dir is None:
        base_dir = config.BASE_DIR
    root = os.path.abspath(base_dir)

    def _inside(rel, error):
        if not isinstance(rel, str) or not rel or not _is_safe_zip_entry(rel):
            raise ValueError(error)
        path = os.path.abspath(os.path.join(root, rel.replace("/", os.sep)))
        if os.path.commonpath([root, path]) != root:
            raise ValueError("ruta fuera de la instalacion")
        return path

    # glob.escape: una instalacion en "...\Servidor [Survival]" no veia sus
    # resguardos y nunca recuperaba una actualizacion interrumpida (2026-10-21).
    pattern = os.path.join(glob.escape(base_dir), "bds_update_prev_*")
    for prev_dir in glob.glob(pattern):
        if not os.path.isdir(prev_dir):
            continue
        manifest_path = os.path.join(prev_dir, _UPDATE_MANIFEST_NAME)
        if not os.path.isfile(manifest_path):
            continue
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                doc = json.load(f)
            if isinstance(doc, dict):
                entries = doc.get("entries")
                staging_rel = doc.get("staging")
            else:
                entries, staging_rel = doc, None
            if not isinstance(entries, list):
                raise ValueError("manifiesto no es una lista")
            staging = None if staging_rel is None else _inside(staging_rel, "staging invalido en manifiesto")

            # Validar TODO antes de mover nada; un manifiesto parcialmente
            # invalido tampoco debe provocar una recuperacion parcial.
            validated = []
            for entry in entries:
                rel = entry.get("path") if isinstance(entry, dict) else None
                had_previous = entry.get("had_previous") if isinstance(entry, dict) else None
                if not isinstance(had_previous, bool):
                    raise ValueError("entrada invalida en manifiesto")
                target = _inside(rel, "entrada invalida en manifiesto")
                staged = None if staging is None else os.path.join(staging, rel.replace("/", os.sep))
                validated.append((target, os.path.join(prev_dir, rel.replace("/", os.sep)), staged, had_previous))

            def _return_to_staging(target, staged):
                # El archivo aplicado salio del staging: vuelve alli. Si el
                # staging ya tiene ese archivo, el estado no es el esperado y
                # se conserva todo (manifiesto incluido) para revision manual.
                if os.path.lexists(staged):
                    raise RuntimeError(f"El staging ya contiene {staged}: estado inesperado")
                os.makedirs(os.path.dirname(staged), exist_ok=True)
                os.replace(target, staged)

            for target, old_path, staged, had_previous in validated:
                if had_previous:
                    if os.path.isfile(old_path):
                        if staged is not None and os.path.isfile(target):
                            _return_to_staging(target, staged)
                        os.makedirs(os.path.dirname(target), exist_ok=True)
                        os.replace(old_path, target)
                    elif not os.path.isfile(target):
                        raise RuntimeError(f"Falta el original y su resguardo: {target}")
                    # Sin old_path, el original no se movio todavia O ya fue
                    # recuperado. Conservar target hace el recovery idempotente.
                elif os.path.isfile(target):
                    if staged is not None:
                        _return_to_staging(target, staged)
                    else:
                        os.remove(target)
            shutil.rmtree(prev_dir, ignore_errors=True)
        except Exception as exc:
            # No borrar un resguardo que no se pudo interpretar: conserva la
            # posibilidad de recuperación manual y evita agravar el incidente.
            print(f"[Actualizador BDS] No se pudo recuperar {os.path.basename(prev_dir)}: {exc}")


class PreviousVersionNotSaved(RuntimeError):
    """La actualizacion quedo aplicada, pero su resguardo no paso a data/bds_previous.

    No es un fallo de la actualizacion: los binarios nuevos ya estan en su
    sitio y el manifiesto de recuperacion ya se retiro. Solo falta la version
    anterior para revertir con un clic; el resguardo queda en
    bds_update_prev_* para revision manual.
    """


def _save_prev_dir(prev_dir, keep_prev_dir, prev_version):
    """Conserva el resguardo como version anterior: lo mueve atómico, quita
    el manifiesto (solo sirve para la recuperación de crashes) y escribe la
    metadata de version.

    La version anterior previa se APARTA con un rename antes de colocar la
    nueva y se borra despues. Antes se hacia rmtree + os.replace: si el rmtree
    dejaba un archivo (bloqueado, solo lectura), data/bds_previous quedaba a
    medias y el replace fallaba (2026-10-20).
    """
    aside = None
    if os.path.lexists(keep_prev_dir):
        aside = keep_prev_dir + ".old_" + os.urandom(4).hex()
        os.replace(keep_prev_dir, aside)
    else:
        os.makedirs(os.path.dirname(keep_prev_dir), exist_ok=True)
    try:
        os.replace(prev_dir, keep_prev_dir)
    except OSError:
        if aside is not None:
            try:
                os.replace(aside, keep_prev_dir)
            except OSError:
                pass
        raise
    if aside is not None:
        shutil.rmtree(aside, ignore_errors=True)
    manifest_path = os.path.join(keep_prev_dir, _UPDATE_MANIFEST_NAME)
    if os.path.isfile(manifest_path):
        os.remove(manifest_path)
    # La metadata solo pone nombre a la version: sin ella el resguardo sigue
    # siendo aplicable (read_previous_version devuelve version None).
    try:
        meta_tmp = os.path.join(keep_prev_dir, _PREVIOUS_META_NAME + ".tmp")
        with open(meta_tmp, "w", encoding="utf-8") as f:
            json.dump({"version": prev_version, "saved_at": time.strftime("%Y-%m-%d %H:%M:%S")}, f)
        os.replace(meta_tmp, os.path.join(keep_prev_dir, _PREVIOUS_META_NAME))
    except OSError:
        pass


def _shipped_pack_dirs(root):
    """Carpetas de pack de un arbol de BDS ({kind: [nombres]}); nunca lanza."""
    packs = {}
    for kind in zip_safety.SERVER_PACK_DIRS:
        kind_dir = os.path.join(root, kind)
        try:
            packs[kind] = [n for n in os.listdir(kind_dir) if os.path.isdir(os.path.join(kind_dir, n))]
        except OSError:
            packs[kind] = []
    return packs


def _record_shipped_packs(packs, tag, log_fn):
    """Une al registro las carpetas de pack de BDS recien instaladas (best-effort).

    El restore lo usa para no devolver packs de BDS desde un backup de otra
    version (zip_safety.is_bds_pack). Un fallo aqui no deshace la instalacion.
    """
    try:
        zip_safety.record_bds_shipped_packs(config.BASE_DIR, packs)
    except OSError as exc:
        log_fn(L(f"{tag} No se pudo registrar los packs de BDS instalados ({exc}); el restore usará el registro anterior o el nombre de cada pack.",
                 f"{tag} Could not record the installed BDS packs ({exc}); restore will use the previous record or each pack's name."), "error")


def _record_shipped_config(hashes, kept, tag, log_fn):
    """Registra las huellas de fabrica instaladas y avisa de lo conservado.

    Best-effort como _record_shipped_packs: un fallo no deshace la instalacion
    (sin registro, la proxima actualizacion decide por la fecha del archivo).
    """
    try:
        record_shipped_config(config.BASE_DIR, hashes)
    except OSError as exc:
        log_fn(L(f"{tag} No se pudo registrar la configuración de fábrica instalada ({exc}).",
                 f"{tag} Could not record the installed factory configuration ({exc})."), "error")
    for rel in sorted(kept):
        log_fn(L(f"{tag} Se conservó tu {rel} (lo editaste); la versión de fábrica nueva quedó en data/bds_config_defaults/{rel}.",
                 f"{tag} Your {rel} was kept (you edited it); the new factory version is in data/bds_config_defaults/{rel}."), "system")


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
    """Aplica el staging bajo el mutex de operacion de la instalacion.

    Sin la exclusion, el arranque de otra GUI tomaba el manifiesto activo por
    el de una actualizacion interrumpida y la revertia a mitad (2026-10-20).
    Si otro proceso esta operando, falla sin tocar ningun archivo.
    """
    with wpg.installation_operation(base_dir):
        return _apply_staged_update_unlocked(
            staging_dir, base_dir, preserve_files, preserve_dirs,
            keep_prev_dir=keep_prev_dir, prev_version=prev_version,
            preserve_staging_on_failure=preserve_staging_on_failure)


def _apply_staged_update_unlocked(staging_dir, base_dir, preserve_files, preserve_dirs,
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
    rollback_complete = False
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
        # Si el staging es el resguardo (rollback), el recovery debe devolverle
        # los archivos ya aplicados: se anota su ruta relativa a la instalacion.
        staging_rel = None
        if preserve_staging_on_failure:
            root = os.path.abspath(base_dir)
            staging_abs = os.path.abspath(staging_dir)
            try:
                if os.path.commonpath([root, staging_abs]) == root:
                    staging_rel = os.path.relpath(staging_abs, root).replace("\\", "/")
            except ValueError:  # otra unidad: no es un staging de la instalacion
                pass
        manifest_tmp = os.path.join(prev_dir, _UPDATE_MANIFEST_NAME + ".tmp")
        with open(manifest_tmp, "w", encoding="utf-8") as f:
            json.dump({"entries": manifest, "staging": staging_rel}, f)
            f.flush()
            os.fsync(f.fileno())
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

        # Punto de confirmacion: con todos los archivos nuevos en su sitio, el
        # manifiesto ya no describe una actualizacion a medias. Se retira ANTES
        # de mover el resguardo a keep_prev_dir: si eso fallaba despues, el
        # manifiesto seguia en bds_update_prev_* y recover_interrupted_updates
        # revertia en el siguiente arranque una actualizacion completada
        # (2026-10-20). Si retirarlo falla, el except revierte ahora mismo.
        os.remove(os.path.join(prev_dir, _UPDATE_MANIFEST_NAME))
    except Exception:
        failed = True
        return_failed = False
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
                # Todavia se intenta reponer el original; conservar el journal
                # para cualquier archivo nuevo que no haya podido retirarse.
                return_failed = True
        # El journal enumera los originales: no depender de un os.walk que
        # puede omitir silenciosamente una carpeta inaccesible del resguardo.
        for entry in manifest:
            if not entry["had_previous"]:
                continue
            rel = entry["path"].replace("/", os.sep)
            old_path = os.path.join(prev_dir, rel)
            target = os.path.join(base_dir, rel)
            if os.path.isfile(old_path):
                os.makedirs(os.path.dirname(target), exist_ok=True)
                os.replace(old_path, target)
            elif not os.path.isfile(target):
                raise RuntimeError(f"Falta el original y su resguardo: {target}")
        rollback_complete = not return_failed
        raise
    finally:
        if failed and preserve_staging_on_failure:
            # El staging es el resguardo anterior: conservar lo recuperable.
            pass
        else:
            shutil.rmtree(staging_dir, ignore_errors=True)
        if keep_prev_dir and not failed:
            try:
                _save_prev_dir(prev_dir, keep_prev_dir, prev_version)
            except OSError as exc:
                # Ya confirmada: no se informa como fallo de la actualizacion.
                raise PreviousVersionNotSaved(L(
                    f"el resguardo no pasó a data/bds_previous ({exc}) y queda en {os.path.basename(prev_dir)} para revisión manual",
                    f"the backup was not moved to data/bds_previous ({exc}) and stays in {os.path.basename(prev_dir)} for manual review",
                )) from exc
        elif not failed or rollback_complete:
            shutil.rmtree(prev_dir, ignore_errors=True)
        # Si el rollback falla, prev_dir + manifiesto quedan para recuperacion.


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
    dl = None
    try:
        url, downloaded_version = _fetch_latest_bedrock_download()
        if not url:
            log_fn(L(f"{tag} No se pudo obtener la URL de descarga oficial. Abortando.", f"{tag} Could not get the official download URL. Aborting."), "error")
            return False, None

        log_fn(L(f"{tag} Descargando binarios desde Mojang...", f"{tag} Downloading binaries from Mojang..."), "system")
        # S3: límite de tamaño de descarga para no llenar el disco
        max_bytes = 400 * 1024 * 1024
        try:
            dl = _open_bds_download(url)
        except ValueError as exc:
            log_fn(L(f"{tag} Descarga rechazada: {exc}", f"{tag} Download rejected: {exc}"), "error")
            return False, None
        # Un 404/503 del CDN guardaria la pagina de error como zip y fallaria
        # despues como BadZipFile con un diagnostico enganoso. getattr: los
        # fakes de tests y respuestas parciales pueden no traer status_code.
        try:
            dl_status = int(getattr(dl, "status_code", 0))
        except (TypeError, ValueError):
            dl_status = 0
        if dl_status >= 400:
            log_fn(L(f"{tag} La descarga devolvió HTTP {dl_status}. Abortando.", f"{tag} The download returned HTTP {dl_status}. Aborting."), "error")
            return False, None
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
                # S2: anti zip-slip — un zip parcialmente malicioso no se
                # aplica a medias: se aborta antes de tocar la instalacion.
                if not _is_safe_zip_entry(name):
                    log_fn(L(f"{tag} Entrada insegura en el zip, actualizacion abortada: {name}", f"{tag} Unsafe zip entry, update aborted: {name}"), "error")
                    shutil.rmtree(staging_dir, ignore_errors=True)
                    return False, None
                z.extract(item, staging_dir)
                extracted += 1
                # Progreso de extraccion (el zip oficial tiene ~9700 entradas)
                if extracted % 1000 == 0:
                    log_fn(L(f"{tag} Descomprimiendo... {extracted} archivos", f"{tag} Extracting... {extracted} files"), "system")

        # D3: raiz efectiva del staging (zip plano actual o una unica
        # carpeta raiz historica); falla cerrada ante estructuras ambiguas.
        update_root = _resolve_update_root(staging_dir)
        # Antes de aplicar: la fase 2 vacia el staging al mover los archivos.
        shipped_packs = _shipped_pack_dirs(update_root)
        # La configuracion que el admin edito se conserva (CONFIG_FILES); su
        # version de fabrica nueva se guarda aparte antes de que el staging
        # desaparezca.
        keep_config = edited_config_files(config.BASE_DIR, update_root)
        incoming_config = _config_hashes(update_root)
        try:
            save_config_defaults(config.BASE_DIR, update_root, keep_config)
        except OSError as exc:
            log_fn(L(f"{tag} No se pudo guardar la configuración de fábrica nueva ({exc}); tus archivos se conservan igual.",
                     f"{tag} Could not save the new factory configuration ({exc}); your files are kept anyway."), "error")

        # Aplica con rollback: si algo falla a mitad, la instalacion
        # vuelve a los binarios anteriores (sin versiones mezcladas). El
        # resguardo queda en data/bds_previous para volver con un clic.
        # Si falla tambien el rollback, se conserva bds_update_prev_*.
        try:
            _apply_staged_update(update_root, config.BASE_DIR, PRESERVE_FILES | keep_config, PRESERVE_DIRS,
                                 keep_prev_dir=PREVIOUS_VERSION_DIR,
                                 prev_version=manager.installed_version)
        except PreviousVersionNotSaved as exc:
            log_fn(L(f"{tag} BDS quedó actualizado, pero sin versión anterior para revertir: {exc}.",
                     f"{tag} BDS was updated, but without a previous version to roll back to: {exc}."), "error")
        except wpg.InstallationBusy as exc:
            # Otro proceso restaura o actualiza esta instalacion: no se toco nada.
            log_fn(f"{tag} {exc}", "error")
            return False, None
        _record_shipped_packs(shipped_packs, tag, log_fn)
        _record_shipped_config(incoming_config, keep_config, tag, log_fn)
        if downloaded_version:
            manager.installed_version = downloaded_version
        return True, downloaded_version
    finally:
        if dl is not None:
            close = getattr(dl, "close", None)
            if close is not None:
                close()
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
    shipped_packs = _shipped_pack_dirs(PREVIOUS_VERSION_DIR)
    # Lo que el admin edito tras actualizar tampoco se pisa al revertir.
    keep_config = edited_config_files(config.BASE_DIR, PREVIOUS_VERSION_DIR)
    swap_saved = True
    try:
        _apply_staged_update(PREVIOUS_VERSION_DIR, config.BASE_DIR, PRESERVE_FILES | keep_config, PRESERVE_DIRS,
                             keep_prev_dir=PREVIOUS_VERSION_DIR,
                             prev_version=manager.installed_version,
                             preserve_staging_on_failure=True)
    except PreviousVersionNotSaved as exc:
        # La reversion SI quedo aplicada; solo falta la nueva version anterior.
        swap_saved = False
        log_fn(L(f"{tag} Reversión aplicada, pero la versión que se dejó de usar no queda recuperable: {exc}.",
                 f"{tag} Rollback applied, but the version just left behind is not recoverable: {exc}."), "error")
    except wpg.InstallationBusy as exc:
        log_fn(f"{tag} {exc}", "error")
        return False, None
    except Exception as exc:
        log_fn(L(f"{tag} Error al restaurar; revisa los resguardos de recuperación: {exc}", f"{tag} Error restoring; check the recovery backups: {exc}"), "error")
        return False, None
    _record_shipped_packs(shipped_packs, tag, log_fn)
    # La huella de fabrica de la version restaurada no se conoce: desde ahora
    # decide la fecha de cada archivo (ver edited_config_files).
    try:
        forget_shipped_config(config.BASE_DIR)
    except OSError as exc:
        log_fn(L(f"{tag} No se pudo borrar el registro de configuración de fábrica ({exc}).",
                 f"{tag} Could not remove the factory configuration record ({exc})."), "error")
    for rel in sorted(keep_config):
        log_fn(L(f"{tag} Se conservó tu {rel} (lo editaste).", f"{tag} Your {rel} was kept (you edited it)."), "system")
    manager.installed_version = restore_version
    if swap_saved:
        log_fn(L(f"{tag} Versión anterior restaurada ({version_label}). La versión que se dejó de usar ahora es la recuperable.", f"{tag} Previous version restored ({version_label}). The version just left behind is now the recoverable one."), "system")
    else:
        log_fn(L(f"{tag} Versión anterior restaurada ({version_label}).", f"{tag} Previous version restored ({version_label})."), "system")
    return True, restore_version
