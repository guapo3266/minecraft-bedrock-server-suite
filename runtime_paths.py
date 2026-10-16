"""Rutas y comandos compartidos por el codigo fuente y la carpeta portable.

Los recursos empaquetados son de solo lectura. Los datos pertenecen a la
carpeta del ejecutable, nunca a _internal ni al directorio de trabajo ajeno.
"""

import os
import sys


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def installation_dir():
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(*parts, base_dir=None):
    if is_frozen():
        root = sys._MEIPASS
    else:
        root = base_dir or installation_dir()
    return os.path.join(root, *parts)


def backup_dir(base_dir):
    if is_frozen():
        return os.path.join(os.path.abspath(base_dir), "backups")
    return os.path.abspath(os.path.join(
        base_dir, "..", "..", "Backups_Minecraft", "auto_backups",
        os.path.basename(os.path.normpath(base_dir)),
    ))


def process_command(mode, base_dir, *args):
    """Conserva subprocess + pipes; solo cambia la entrada del hijo congelado."""
    scripts = {"wrapper": "server_wrapper.py", "backup-worker": "backup_worker.py"}
    script = scripts[mode]
    if is_frozen():
        return [os.path.join(installation_dir(), "SuiteMinecraftHost.exe"), "--internal-" + mode, *args]
    return [sys.executable, "-u", os.path.join(base_dir, script), *args]


def subprocess_options():
    """Los hijos conservan pipes de consola, pero sin ventanas adicionales."""
    if is_frozen() and sys.platform == "win32":
        import subprocess
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}
