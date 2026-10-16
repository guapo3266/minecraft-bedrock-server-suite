"""Lanzador de SuiteMinecraft: GUI y subprocesos del portable sin Python externo."""

import argparse
import multiprocessing
import os
import runpy
import sys
from pathlib import Path

import runtime_paths
from console_lang import L


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    # El ejecutable de ventana no tiene stdio. Los hijos console=True mantienen
    # sus pipes; aqui solo se sustituyen los streams ausentes del padre.
    if sys.stdout is None or sys.stderr is None:
        logs = Path(runtime_paths.installation_dir()) / "logs"
        logs.mkdir(exist_ok=True)
        logfile = logs / "SuiteMinecraft.log"
        if logfile.exists() and logfile.stat().st_size > 5 * 1024 * 1024:
            logfile.replace(logs / "SuiteMinecraft.anterior.log")
        stream = logfile.open("a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = stream
    # El worker necesita stdout sin buffer tambien al ejecutarse sin `python -u`.
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    if sys.stdin is not None and hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    os.environ.setdefault("WRAPPER_LANG", "es")
    os.environ.setdefault("LMSTUDIO_MODEL", "qwen3-minecraft-v3")
    if args and args[0] in ("--internal-wrapper", "--internal-backup-worker"):
        mode = args.pop(0)
        module = "server_wrapper" if mode == "--internal-wrapper" else "backup_worker"
        # Mismos argv que los scripts originales; no importar GUI en el worker.
        sys.argv = [module + ".py", *args]
        runpy.run_module(module, run_name="__main__")
        return 0

    parser = argparse.ArgumentParser(prog="SuiteMinecraft.exe", description="Minecraft Bedrock Server Suite portable")
    parser.add_argument("--no-browser", action="store_true", help=L("Abrir la GUI sin lanzar el navegador", "Start the GUI without opening the browser"))
    parser.add_argument("--console", action="store_true", help=L("Iniciar solo el wrapper de consola (BDS debe estar instalado)", "Start only the console wrapper (BDS must be installed)"))
    options = parser.parse_args(args)
    os.chdir(runtime_paths.installation_dir())
    if options.no_browser:
        os.environ["GUI_OPEN_BROWSER"] = "0"
    if not options.console and not options.no_browser:
        from desktop_window import main as desktop_main
        return desktop_main()
    module = "server_wrapper" if options.console else "server_gui_server"
    sys.argv = [module + ".py"]
    runpy.run_module(module, run_name="__main__")
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
