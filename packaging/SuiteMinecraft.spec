# -*- mode: python ; coding: utf-8 -*-
"""Bundle onedir: solo codigo propio, frontend y dependencias de Python."""

from pathlib import Path
import os
import sys
from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).parent
datas = [
    (str(root / "build" / "portable" / "frontend"), "gui_frontend/dist"),
    (str(root / "gui_frontend" / "public" / "favicon.svg"), "gui_frontend/public"),
    (str(root / "web"), "web"),
]
a = Analysis(
    [str(root / "suite_minecraft.py")],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=["desktop_window", "server_gui_server", "server_wrapper", "backup_worker"] + collect_submodules("uvicorn"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "hypothesis", "IPython", "tkinter"],
    noarchive=False,
)
# QWebEngineWidgets usa Widgets, no una aplicacion QML. Los hooks tambien
# descubren galerias/estilos QML ajenos (con rutas excesivas para Explorer).
# Se conservan las DLL QtQuick/QtQml y todos los recursos propios de WebEngine.
a.datas = [entry for entry in a.datas if not entry[0].replace("\\", "/").startswith("PySide6/qml/")]
a.binaries = [entry for entry in a.binaries if not entry[0].replace("\\", "/").startswith("PySide6/qml/")]
allowed_roots = [Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve(), Path(os.environ["SystemRoot"]).resolve()]
for target, source, kind in a.binaries:
    source_path = Path(source).resolve()
    if not any(source_path.is_relative_to(base) for base in allowed_roots):
        raise RuntimeError(f"DLL ajena al entorno limpio: {source_path}")
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="SuiteMinecraft", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False,
)
host = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="SuiteMinecraftHost", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=True,
)
coll = COLLECT(exe, host, a.binaries, a.datas, strip=False, upx=False, name="SuiteMinecraft")
