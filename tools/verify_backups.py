# -*- coding: utf-8 -*-
"""Verificacion batch de integridad de backups (CRC) + cuarentena.

Uso: python tools/verify_backups.py [directorio_de_backups]
  - Sin argumento usa el directorio de backups de esta instalacion
    (auto_backup.get_backup_dir()).
  - Recorre los zips no marcados, corre testzip() (CRC de todas las entradas)
    y renombra los corruptos con el marcador _CORRUPTO (misma convencion que
    la GUI y la rotacion: no se ofrecen para restaurar).
  - Los ya marcados (_CORRUPTO/_EXCEDIDO/_CRASH) se saltan.

Exit code: 0 si no hay corruptos (o no hay backups), 1 si se encontro alguno.
OJO: testzip() lee el zip entero; con muchos backups grandes tarda.
"""
import os
import sys
import zipfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import auto_backup
from console_lang import L
from wrapper_backup import mark_corrupt_zip
from zip_safety import CORRUPT_MARKERS


def _ya_marcado(name):
    return any(marcador in name for marcador in CORRUPT_MARKERS)


def verify_all(backup_dir):
    """Verifica todos los backups del directorio y marca los corruptos.

    Devuelve (ok, corruptos).
    """
    ok = corruptos = 0
    if not os.path.isdir(backup_dir):
        return ok, corruptos
    for name in sorted(os.listdir(backup_dir)):
        if not name.endswith(".zip") or _ya_marcado(name):
            continue
        path = os.path.join(backup_dir, name)
        if not os.path.isfile(path):
            continue
        try:
            with zipfile.ZipFile(path) as zf:
                bad = zf.testzip()
        except zipfile.BadZipFile:
            bad = L("<cabecera invalida>", "<invalid header>")
        if bad:
            print(L(f"[CORRUPTO] {name}: {bad}", f"[CORRUPT] {name}: {bad}"))
            mark_corrupt_zip(path, "CORRUPTO")
            corruptos += 1
        else:
            print(f"[OK] {name}")
            ok += 1
    return ok, corruptos


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    backup_dir = args[0] if args else auto_backup.get_backup_dir()
    print(L(f"[*] Verificando backups en: {backup_dir}",
            f"[*] Verifying backups in: {backup_dir}"))
    ok, corruptos = verify_all(backup_dir)
    print(L(f"[*] Resultado: {ok} OK, {corruptos} corruptos.",
            f"[*] Result: {ok} OK, {corruptos} corrupt."))
    return 1 if corruptos else 0


if __name__ == "__main__":
    raise SystemExit(main())
