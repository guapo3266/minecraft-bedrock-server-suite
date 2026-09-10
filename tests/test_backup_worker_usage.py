"""Uso del worker de compresion lanzado a mano (sin argumentos)."""

import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_backup_worker_sin_argumentos_da_uso_y_exit_2():
    """`python backup_worker.py` a secas no debe morir con un traceback de
    IndexError: mensaje de uso y exit 2 (lanzado por el wrapper siempre lleva
    los 3 argumentos)."""
    r = subprocess.run(
        [sys.executable, os.path.join(BASE_DIR, "backup_worker.py")],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    salida = (r.stdout or "") + (r.stderr or "")
    assert "backup_worker.py" in salida
    assert "Traceback" not in salida
