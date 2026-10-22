"""Carpeta de backups de cada instalacion (fuente unica: wrapper, GUI y CLI).

Sin ajuste, los backups van a <instalacion>\\..\\..\\Backups_Minecraft\\
auto_backups\\<servidor> (H3, comportamiento historico). La GUI puede guardar
otra carpeta raiz en data/backup_location.json ({"backup_root": ...}) y los
backups de esta instalacion pasan a <raiz>\\<servidor>. La subcarpeta por
servidor es la misma defensa que H3: la rotacion borra por mtime cualquier
auto_backup_*.zip de su carpeta, asi que dos instalaciones que eligen la misma
raiz no deben compartir carpeta.

Dentro de la instalacion solo se admite una raiz bajo backups\\: el resto es
de BDS (una actualizacion lo reemplaza), de la suite o de lo que el propio
backup empaqueta. Esa raiz se guarda RELATIVA para que viaje con la carpeta
(otro disco, un USB).

Un ajuste ilegible o que ya no valida se ignora: se usa la carpeta
predeterminada y describe() lo informa en setting_error.

La subcarpeta se nombra por la carpeta de la instalacion, asi que dos
instalaciones con el mismo nombre bajo la misma raiz (C:\\Servers\\Survival\\
Suite y C:\\Servers\\Creative\\Suite) caian en la misma carpeta: la rotacion
mezclaba sus backups y la GUI de una ofrecia restaurar el mundo de la otra
(2026-10-21). Ahora la carpeta tiene dueno (OWNER_FILE, lo escribe
claim_backup_dir con el primer backup) y una instalacion que no es su duena usa
<raiz>\\<servidor>-<id8>. La identidad de la instalacion vive en
data/installation_id.json: sobrevive a mover la carpeta y una COPIA recibe una
propia (ver _identity).

Vive en gui_backend/ aunque lo usen el wrapper y la CLI: las instalaciones
2.1.x validan cada actualizacion con su propia lista de archivos raiz
(suite_release.ROOT_FILES) y rechazan el ZIP entero si trae uno nuevo. Ver
tests/test_paquete_release.py.
"""

import hashlib
import json
import os
import re

import suite_release
from zip_safety import _is_safe_zip_entry

SETTING_KEY = "backup_root"
INSIDE_ALLOWED_DIR = "backups"
# Dueno de una carpeta de backups ({"id", "path"} de la instalacion). Sin el
# sufijo .tmp ni .zip: la limpieza de huerfanos y la rotacion no lo tocan.
OWNER_FILE = ".bedrock_suite_owner.json"
_ID_RE = re.compile(r"[0-9a-f]{32}")

# MAX_PATH de Windows sin rutas largas. Lo que el nombre de un backup (y su
# .tmp) suma a la carpeta, sin contar el nombre del servidor:
# "\auto_backup_" + "_" + disparador (hasta 24) + "_AAAA-MM-DD_HH-MM-SS_xxxxxx.zip.tmp".
_PATH_MAX = 259
_NAME_OVERHEAD = len("\\auto_backup_") + 1 + 24 + len("_2026-10-20_12-00-00_abcdef.zip.tmp")

_BAD_CHARS = re.compile(r'[<>"|?*\x00-\x1f]')
_DRIVE = re.compile(r"^[A-Za-z]:$")
_UNC = re.compile(r'^[\\/]{2}[^\\/:<>"|?*]+[\\/][^\\/:<>"|?*]+$')


class InvalidBackupRoot(ValueError):
    """La carpeta pedida no sirve; code es el motivo estable que ve la API."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def settings_path(base_dir):
    return os.path.join(base_dir, "data", "backup_location.json")


def server_name(base_dir):
    return os.path.basename(os.path.normpath(base_dir))


def default_root(base_dir):
    return os.path.abspath(os.path.join(
        base_dir, "..", "..", "Backups_Minecraft", "auto_backups",
    ))


def _norm(path):
    return os.path.normcase(os.path.normpath(path))


def _inside(path, parent):
    """True si path es parent o cuelga de el (rutas absolutas)."""
    try:
        return os.path.commonpath([_norm(path), _norm(parent)]) == _norm(parent)
    except ValueError:  # unidades distintas
        return False


def _check_syntax(raw):
    """Ruta absoluta de Windows bien formada -> normalizada."""
    if not isinstance(raw, str):
        raise InvalidBackupRoot("invalid_path")
    path = raw.strip()
    if path.startswith(("\\\\?\\", "\\\\.\\", "//?/", "//./")) or _BAD_CHARS.search(path):
        raise InvalidBackupRoot("invalid_path")
    drive, tail = os.path.splitdrive(path)
    unc = bool(_UNC.match(drive))
    if not drive or not (tail.startswith(("\\", "/")) or (unc and not tail)):
        raise InvalidBackupRoot("not_absolute")
    # Mismo filtro que las entradas de un ZIP: sin '..', ':' (ADS), nombres de
    # dispositivo ni segmentos con punto o espacio final.
    if not (_DRIVE.match(drive) or unc) or not _is_safe_zip_entry(tail.lstrip("\\/")):
        raise InvalidBackupRoot("invalid_path")
    return os.path.normpath(path)


def _check_location(base_dir, root):
    """Valida la raiz absoluta para esta instalacion; devuelve la carpeta final.

    Compara rutas normales y resueltas (realpath): un enlace o junction no
    puede colar los backups dentro de worlds/ o de los packs.
    """
    name = server_name(base_dir)
    target = os.path.join(root, name)
    if len(target) + len(name) + _NAME_OVERHEAD > _PATH_MAX:
        raise InvalidBackupRoot("too_long")
    base = os.path.abspath(base_dir)
    try:
        views = (
            (base, root, target),
            (os.path.realpath(base), os.path.realpath(root), os.path.realpath(target)),
        )
    except OSError:
        raise InvalidBackupRoot("invalid_path")
    for check_base, check_root, check_target in views:
        if _inside(check_base, check_target):
            raise InvalidBackupRoot("contains_installation")
        for path in (check_root, check_target):
            if _inside(path, check_base):
                first = os.path.relpath(path, check_base).split(os.sep)[0]
                if os.path.normcase(first) != INSIDE_ALLOWED_DIR:
                    raise InvalidBackupRoot("inside_installation")
    return target


def _stored_root(base_dir):
    """(raiz absoluta del ajuste o None, codigo si el ajuste se ignora)."""
    try:
        with open(settings_path(base_dir), encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError):
        return None, "unreadable_setting"
    raw = data.get(SETTING_KEY) if isinstance(data, dict) else None
    if raw is None:
        return None, None
    try:
        if isinstance(raw, str) and raw and not os.path.splitdrive(raw)[0] and not raw.startswith(("\\", "/")):
            # Relativa a la instalacion (raiz bajo backups\, ver docstring).
            if _BAD_CHARS.search(raw) or not _is_safe_zip_entry(raw):
                raise InvalidBackupRoot("invalid_path")
            root = os.path.normpath(os.path.join(os.path.abspath(base_dir), raw))
        else:
            root = _check_syntax(raw)
        _check_location(base_dir, root)
    except InvalidBackupRoot as exc:
        return None, exc.code
    return root, None


def resolve_root(base_dir):
    root, _error = _stored_root(base_dir)
    return root or default_root(base_dir)


def identity_path(base_dir):
    return os.path.join(base_dir, "data", "installation_id.json")


def _read_dict(path):
    """JSON de objeto o None (ausente, ilegible o de otro tipo). Nunca lanza."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_dict(path, data):
    """Escritura atomica best-effort: devuelve False si no se pudo."""
    try:
        suite_release.write_json(path, data)
    except OSError:
        return False
    return True


def _identity(base_dir, create):
    """Id estable de la instalacion o None (sin identidad y create=False).

    data/installation_id.json guarda {"id", "path"}. Si "path" no es la carpeta
    actual y la carpeta original sigue llevando el MISMO id, esta es una copia
    de una instalacion viva y necesita un id propio: si no, una copia del
    servidor compartiria la carpeta de backups con su original, que es el caso
    mas comun de dos instalaciones con el mismo nombre. Si la original ya no
    lleva ese id, la instalacion se movio y lo conserva.
    """
    base = os.path.abspath(base_dir)
    path = identity_path(base)
    data = _read_dict(path) or {}
    ident, saved = data.get("id"), data.get("path")
    if isinstance(ident, str) and _ID_RE.fullmatch(ident) and isinstance(saved, str) and saved:
        if _norm(saved) == _norm(base):
            return ident
        original = _read_dict(identity_path(saved))
        if not (original and original.get("id") == ident):
            if create:
                _write_dict(path, {"id": ident, "path": base})
            return ident
    if not create:
        return None
    ident = os.urandom(16).hex()
    return ident if _write_dict(path, {"id": ident, "path": base}) else None


def _owned_by(base_dir, owner):
    """True si el dueno anotado en una carpeta de backups es esta instalacion.

    Coincide la ruta (tambien tras borrar data/) o el id (tambien tras mover la
    carpeta de la instalacion).
    """
    base = os.path.abspath(base_dir)
    path = owner.get("path")
    if isinstance(path, str) and path and _norm(path) == _norm(base):
        return True
    ident = _identity(base, create=False)
    return ident is not None and owner.get("id") == ident


def _folder_for(base_dir, root):
    """<raiz>\\<servidor>, o <raiz>\\<servidor>-<id8> si esa tiene otro dueno."""
    name = server_name(base_dir)
    primary = os.path.join(root, name)
    owner = _read_dict(os.path.join(primary, OWNER_FILE))
    if owner is None or _owned_by(base_dir, owner):
        return primary
    ident = _identity(base_dir, create=True)
    # Sin poder escribir la identidad (data/ de solo lectura) queda el hash de
    # la ruta: estable mientras la carpeta no se mueva.
    suffix = ident[:8] if ident else hashlib.sha256(_norm(os.path.abspath(base_dir)).encode("utf-8")).hexdigest()[:8]
    return os.path.join(root, f"{name}-{suffix}")


def resolve_backup_dir(base_dir):
    """Carpeta donde esta instalacion escribe, lista y rota sus backups.

    <raiz>\\<servidor>, salvo que esa carpeta tenga otro dueno: entonces
    <raiz>\\<servidor>-<id8> (ver el docstring del modulo).
    """
    return _folder_for(base_dir, resolve_root(base_dir))


def claim_backup_dir(base_dir, backup_dir):
    """Anota esta instalacion como duena de backup_dir (best-effort, nunca lanza).

    Solo si backup_dir es la carpeta que resolve_backup_dir le asigna (un
    BACKUP_DIR parcheado por tests no se reclama) y nadie mas la reclamo. Si
    el dueno es esta misma instalacion con otra ruta o con otro id (se movio o
    se borro data/), se actualiza.
    """
    if _norm(backup_dir) != _norm(resolve_backup_dir(base_dir)):
        return
    marker = os.path.join(backup_dir, OWNER_FILE)
    owner = _read_dict(marker)
    if owner is not None and not _owned_by(base_dir, owner):
        return
    ident = _identity(base_dir, create=True)
    if ident is None:
        return
    wanted = {"id": ident, "path": os.path.abspath(base_dir)}
    if owner != wanted:
        _write_dict(marker, wanted)


def describe(base_dir):
    """Estado para la GUI (GET /api/backups/location)."""
    root, error = _stored_root(base_dir)
    name = server_name(base_dir)
    fallback = default_root(base_dir)
    backup_dir = resolve_backup_dir(base_dir)
    return {
        "backup_dir": backup_dir,
        "root": root or fallback,
        "custom": root is not None,
        "portable": root is not None and _inside(root, os.path.abspath(base_dir)),
        "default_root": fallback,
        "default_backup_dir": os.path.join(fallback, name),
        "server_name": name,
        # True si <raiz>\<servidor> es de otra instalacion con el mismo nombre
        "shared_name": _norm(backup_dir) != _norm(os.path.join(root or fallback, name)),
        "exists": os.path.isdir(backup_dir),
        "setting_error": error,
    }


def _prepare(target):
    """Crea la carpeta y comprueba que se puede escribir en ella."""
    if os.path.exists(target) and not os.path.isdir(target):
        raise InvalidBackupRoot("not_a_directory")
    try:
        os.makedirs(target, exist_ok=True)
        # Sin sufijo .tmp: create_backup borra los *.tmp huerfanos de la carpeta.
        probe = os.path.join(target, f".bedrock_suite_probe_{os.urandom(4).hex()}")
        with open(probe, "xb"):
            pass
        os.remove(probe)
    except OSError:
        raise InvalidBackupRoot("not_writable")


def save_root(base_dir, raw):
    """Valida, prepara y guarda la raiz pedida; devuelve la carpeta final.

    None o una cadena vacia (o la propia raiz predeterminada) vuelven a la
    carpeta predeterminada. Los backups ya existentes no se mueven.
    """
    path = settings_path(base_dir)
    root = None
    if raw is not None and not (isinstance(raw, str) and not raw.strip()):
        root = _check_syntax(raw)
        if _norm(root) == _norm(default_root(base_dir)):
            root = None
    if root is None:
        suite_release.write_json(path, {SETTING_KEY: None})
        return resolve_backup_dir(base_dir)
    _check_location(base_dir, root)
    # La carpeta real puede llevar el sufijo -<id8> (otra instalacion con el
    # mismo nombre ya es duena de <raiz>\<servidor>): se valida y prepara esa.
    target = _folder_for(base_dir, root)
    if len(target) + len(server_name(base_dir)) + _NAME_OVERHEAD > _PATH_MAX:
        raise InvalidBackupRoot("too_long")
    _prepare(target)
    base = os.path.abspath(base_dir)
    stored = os.path.relpath(root, base) if _inside(root, base) else root
    suite_release.write_json(path, {SETTING_KEY: stored})
    return target
