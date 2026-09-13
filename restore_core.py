# -*- coding: utf-8 -*-
"""restore_core.py — coreografia unica de restauracion de backups.

La GUI (`auto_backup.restore_backup`) y la CLI (`restore_backup.list_and_restore`)
consumen este mismo pipeline: validacion + clasificacion de entradas, staging,
guard de `level.dat` SIEMPRE, swap recuperable con rollback por cuarentena y
limpieza de resguardos. Antes vivia duplicado (~150 lineas por lado) y el
guard de `level.dat` hubo que sincronizarlo a mano entre las dos copias: un bug
del swap habia que corregirlo dos veces o GUI y CLI divergian en la operacion
mas destructiva del sistema.

Contrato:
  - Errores de entrada/validacion: `ValueError` (o `BadZipFile` de zipfile).
  - Fallo de extraccion/intercambio: `RuntimeError`; el mundo original queda
    intacto o recuperado por rollback.
  - Devuelve la ruta del ZIP restaurado.
  - Mensajes via `console_lang.L`: el CLI es es-only y fija el idioma del
    proceso durante la llamada (restaurandolo despues).
"""

import os
import shutil
import zipfile

from console_lang import L
from zip_safety import (
    _is_safe_zip_entry,
    _pack_dest,
    _extract_pack_entry,
    _quarantine_and_restore,
    _exceeds_expansion_limit,
)


def _limpiar_stagings(world_staging, pack_dir_stagings, pack_file_stagings):
    """Borra staging de mundo/packs sin propagar errores (limpieza best-effort)."""
    shutil.rmtree(world_staging, ignore_errors=True)
    for s_dir in pack_dir_stagings.values():
        shutil.rmtree(s_dir, ignore_errors=True)
    for s_file in pack_file_stagings.values():
        if os.path.exists(s_file):
            try:
                os.remove(s_file)
            except Exception:
                pass


def restore_from_zip(zip_path, base_dir, world_dir, log_fn=None):
    """Restaura `zip_path` sobre `world_dir` con staging + swap recuperable.

    `base_dir` resuelve el destino de los packs de servidor
    (`server_resource_packs/...` -> `resource_packs/...`). El ZIP se valida
    ANTES de tocar el mundo (entradas seguras, CRC y limite de expansion); la
    extraccion va a `.restore_staging_<nonce>` y solo despues del guard de
    `level.dat` se intercambia con el mundo/packs activos. Si el intercambio
    falla, `_quarantine_and_restore` devuelve los resguardos a su sitio.
    """
    log = log_fn or print

    # 1. Validar el ZIP y clasificar entradas: mundo vs packs de servidor.
    log(L("[*] Validando backup antes de tocar el mundo...",
          "[*] Validating backup before touching the world..."))
    with zipfile.ZipFile(zip_path, "r") as zf:
        world_infos, pack_infos = [], []
        for entry in zf.infolist():
            if not _is_safe_zip_entry(entry.filename):
                raise ValueError(L(f"Entrada insegura en el backup: {entry.filename}",
                                   f"Unsafe entry in the backup: {entry.filename}"))
            if entry.filename.replace("\\", "/").endswith("/"):
                # Entrada de directorio: sin datos; y una "server_resource_packs/"
                # suelta clasificaria como mundo dejando carpeta espuria.
                continue
            parsed = _pack_dest(entry.filename)
            if parsed:
                pack_infos.append((entry, parsed))
            else:
                world_infos.append(entry)
        bad = zf.testzip()
        if bad is not None:
            raise ValueError(L(f"Backup corrupto (CRC fallido): {bad}",
                               f"Corrupt backup (CRC failed): {bad}"))
        if _exceeds_expansion_limit(zf.infolist()):
            raise ValueError(L(
                "Backup rechazado: su tamaño descomprimido excede el limite de seguridad.",
                "Backup rejected: its uncompressed size exceeds the safety limit.",
            ))

    nonce = os.urandom(4).hex()
    world_staging = world_dir + f".restore_staging_{nonce}"
    pack_dir_stagings = {}   # dest_dir -> staging_dir
    pack_file_stagings = {}  # dest_file -> staging_file

    for _entry, (kind, folder, rel) in pack_infos:
        if folder:
            dest_dir = os.path.normpath(os.path.join(base_dir, kind, folder))
            if dest_dir not in pack_dir_stagings:
                pack_dir_stagings[dest_dir] = dest_dir + f".restore_staging_{nonce}"
        else:
            dest_file = os.path.normpath(os.path.join(base_dir, kind, rel))
            if dest_file not in pack_file_stagings:
                pack_file_stagings[dest_file] = dest_file + f".restore_staging_{nonce}"

    # 2. Extraer a staging (el mundo y los packs reales no se tocan).
    log(L("[*] Descomprimiendo backup en área temporal (staging)...",
          "[*] Extracting backup to staging area..."))
    try:
        os.makedirs(world_staging, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            for entry in world_infos:
                zf.extract(entry, world_staging)
            for entry, (kind, folder, rel) in pack_infos:
                if folder:
                    dest_dir = os.path.normpath(os.path.join(base_dir, kind, folder))
                    _extract_pack_entry(zf, entry, pack_dir_stagings[dest_dir], rel)
                else:
                    dest_file = os.path.normpath(os.path.join(base_dir, kind, rel))
                    staging_f = pack_file_stagings[dest_file]
                    os.makedirs(os.path.dirname(staging_f), exist_ok=True)
                    with zf.open(entry, "r") as src, open(staging_f, "wb") as out:
                        shutil.copyfileobj(src, out)

        # level.dat se exige SIEMPRE (tambien con world_infos vacio): un ZIP
        # sin entradas de mundo (vacio o solo-packs) pasaba las validaciones
        # previas, instalaba un staging VACIO como mundo activo y borraba el
        # .bak del mundo real (bug real de la ronda 2026-09-11).
        if not os.path.exists(os.path.join(world_staging, "level.dat")):
            raise RuntimeError(L(
                "El backup no contiene un mundo valido (sin level.dat); restauración abortada sin tocar el mundo.",
                "The backup does not contain a valid world (no level.dat); restore aborted without touching the world.",
            ))
    except Exception as exc:
        _limpiar_stagings(world_staging, pack_dir_stagings, pack_file_stagings)
        raise RuntimeError(L(f"Fallo la extraccion: {exc}",
                             f"Extraction failed: {exc}")) from exc

    # 3. Intercambio recuperable (swap).
    log(L("[*] Intercambiando con el mundo y packs activos...",
          "[*] Swapping with the active world and packs..."))
    bak_dir = world_dir + f".bak_{nonce}"
    pack_baks = []  # (active_path, bak_path, is_dir)
    swap_success = False

    try:
        # Resguardar el mundo actual (si existe)
        if os.path.exists(world_dir):
            os.rename(world_dir, bak_dir)

        # Resguardar packs actuales (si existen)
        for dest_dir in sorted(pack_dir_stagings.keys()):
            if os.path.exists(dest_dir):
                bak = dest_dir + f".bak_{nonce}"
                os.rename(dest_dir, bak)
                pack_baks.append((dest_dir, bak, True))

        for dest_file in sorted(pack_file_stagings.keys()):
            if os.path.exists(dest_file):
                bak = dest_file + f".bak_{nonce}"
                os.rename(dest_file, bak)
                pack_baks.append((dest_file, bak, False))

        # Mover staging a destinos finales
        os.rename(world_staging, world_dir)
        for dest_dir, s_dir in pack_dir_stagings.items():
            if os.path.exists(s_dir):
                os.makedirs(os.path.dirname(dest_dir), exist_ok=True)
                os.rename(s_dir, dest_dir)
        for dest_file, s_file in pack_file_stagings.items():
            if os.path.exists(s_file):
                os.makedirs(os.path.dirname(dest_file), exist_ok=True)
                os.rename(s_file, dest_file)

        swap_success = True
    except Exception as swap_err:
        log(L(f"[ERROR] Falló el intercambio de restauración: {swap_err}. Iniciando rollback...",
              f"[ERROR] Swap failed during restore: {swap_err}. Starting rollback..."))

        _quarantine_and_restore(world_dir, bak_dir, is_dir=True)

        for active_p, bak_p, is_d in reversed(pack_baks):
            _quarantine_and_restore(active_p, bak_p, is_dir=is_d)

        _limpiar_stagings(world_staging, pack_dir_stagings, pack_file_stagings)
        raise RuntimeError(L(f"Fallo el intercambio durante la restauracion: {swap_err}",
                             f"Swap failed during restore: {swap_err}")) from swap_err

    # 4. Limpieza de los resguardos solo tras intercambio exitoso.
    if swap_success:
        if os.path.exists(bak_dir):
            shutil.rmtree(bak_dir, ignore_errors=True)
        for _active_p, bak_p, is_d in pack_baks:
            if os.path.exists(bak_p):
                try:
                    if is_d:
                        shutil.rmtree(bak_p, ignore_errors=True)
                    else:
                        os.remove(bak_p)
                except Exception:
                    pass

    return zip_path
