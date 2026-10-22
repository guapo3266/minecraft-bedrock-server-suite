# -*- coding: utf-8 -*-
"""Verificacion batch de integridad de backups (CRC) + cuarentena.

Uso: python tools/verify_backups.py [directorio_de_backups]
  - Sin argumento usa el directorio de backups de esta instalacion
    (auto_backup.get_backup_dir()).
  - Recorre los zips no marcados, lee todas sus entradas (CRC y descompresion,
    zip_safety.check_zip_integrity) y renombra los corruptos con el marcador
    _CORRUPTO (misma convencion que la GUI y la rotacion: no se ofrecen para
    restaurar).
  - Los ya marcados (_CORRUPTO/_EXCEDIDO/_CRASH) se saltan.
  - Un ZIP que no se puede leer (bloqueado, error de disco) se avisa y NO se
    marca: eso no prueba que este roto.

Exit code: 0 si todo esta bien (o no hay backups), 1 si se encontro algun
corrupto, 2 si no hay corruptos pero algun ZIP no se pudo leer.
OJO: lee cada zip entero; con muchos backups grandes tarda.
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import auto_backup
from console_lang import L
from wrapper_backup import mark_corrupt_zip
from zip_safety import CORRUPT_MARKERS, check_zip_integrity


def _ya_marcado(name):
    return any(marcador in name for marcador in CORRUPT_MARKERS)


def verify_all(backup_dir):
    """Verifica todos los backups del directorio y marca los corruptos.

    Devuelve (ok, corruptos). Los ilegibles los cuenta revisar_todos().
    """
    ok, corruptos, _omitidos = revisar_todos(backup_dir)
    return ok, corruptos


def revisar_todos(backup_dir):
    """Como verify_all, pero devuelve (ok, corruptos, omitidos)."""
    ok = corruptos = omitidos = 0
    if not os.path.isdir(backup_dir):
        return ok, corruptos, omitidos
    for name in sorted(os.listdir(backup_dir)):
        if not name.endswith(".zip") or _ya_marcado(name):
            continue
        path = os.path.join(backup_dir, name)
        if not os.path.isfile(path):
            continue
        try:
            bad, names = check_zip_integrity(path)
        except OSError as exc:
            print(L(f"[AVISO] {name}: no se pudo leer ({exc}); no se marca.",
                    f"[WARNING] {name}: could not be read ({exc}); not flagged."))
            omitidos += 1
            continue
        if not bad and "level.dat" not in names:
            # Sin level.dat el restore lo rechazara igual (guard de
            # restore_core): no es un backup restaurable aunque el CRC pase
            # (H3-2026-09-25). Se marca con el mismo marcador que la GUI y la
            # rotacion usan para no ofrecerlo ni contarlos como bueno.
            bad = L("sin level.dat (no restaurable)", "missing level.dat (not restorable)")
        if bad:
            print(L(f"[CORRUPTO] {name}: {bad}", f"[CORRUPT] {name}: {bad}"))
            mark_corrupt_zip(path, "CORRUPTO")
            corruptos += 1
        else:
            print(f"[OK] {name}")
            ok += 1
    return ok, corruptos, omitidos


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    backup_dir = args[0] if args else auto_backup.get_backup_dir()
    print(L(f"[*] Verificando backups en: {backup_dir}",
            f"[*] Verifying backups in: {backup_dir}"))
    ok, corruptos, omitidos = revisar_todos(backup_dir)
    print(L(f"[*] Resultado: {ok} OK, {corruptos} corruptos, {omitidos} sin leer.",
            f"[*] Result: {ok} OK, {corruptos} corrupt, {omitidos} unreadable."))
    if corruptos:
        return 1
    return 2 if omitidos else 0


if __name__ == "__main__":
    raise SystemExit(main())
