"""Prepara y arranca una copia aislada del EXE real, sin ejecutar BDS.

El simulador C# de tests solo imita stdin/stdout para validar el cierre.
No entra en el ZIP. No se leen datos del servidor ni de carpetas vecinas.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
CURRENT = ROOT / "build" / "portable" / "desktop-qa-current.json"


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "prepare"
    if action == "prepare":
        qa = ROOT / "build" / "portable" / "desktop-qa" / str(time.time_ns())
        base = qa / "Suite con espacios y acentos á"
        shutil.copytree(ROOT / "portable" / "SuiteMinecraft", base, ignore=shutil.ignore_patterns("qml"))
        csc = Path(os.environ["SystemRoot"]) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
        subprocess.run([str(csc), "/nologo", "/target:exe", "/out:" + str(qa / "simulador.exe"), str(ROOT / "tests" / "fixtures" / "portable_stub.cs")], check=True, capture_output=True)
        state = {"base": str(base), "qa": str(qa)}
        CURRENT.write_text(json.dumps(state), encoding="utf-8")
    else:
        state = json.loads(CURRENT.read_text(encoding="utf-8"))
        base, qa = Path(state["base"]), Path(state["qa"])
    if action == "install-stub":
        shutil.copy2(qa / "simulador.exe", base / "bedrock_server.exe")
        world = base / "worlds" / "MundoPrueba"
        world.mkdir(parents=True, exist_ok=True)
        (world / "level.dat").write_bytes(b"QA PORTABLE: datos sinteticos, NO ES UN MUNDO REAL\x00\xff")
        (base / "server.properties").write_text("level-name=MundoPrueba\nbackup-inicio=false\nserver-name=QA portable\n", encoding="utf-8")
        (base / "data").mkdir(exist_ok=True)
        (base / "data" / "setup_done.json").write_text('{"completed":true}', encoding="utf-8")
    if action in {"prepare", "launch", "launch-empty"}:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("GUI_", "WRAPPER_", "PYTHON", "LMSTUDIO_"))}
        env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
        env["GUI_PORT"] = "8765"
        env["WRAPPER_LANG"] = "es"
        env["PORTABLE_QA_PLAYERS"] = "0" if action == "launch-empty" else "1"
        env["QTWEBENGINE_CHROMIUM_FLAGS"] = "--force-renderer-accessibility"
        process = subprocess.Popen([str(base / "SuiteMinecraft.exe")], cwd=qa, env=env)
        state["pid"] = process.pid
        CURRENT.write_text(json.dumps(state), encoding="utf-8")
    print(json.dumps(state, ensure_ascii=True))


if __name__ == "__main__":
    main()
