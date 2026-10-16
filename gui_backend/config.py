"""Rutas, puertos y constantes globales del backend de la GUI."""

import os
import runtime_paths

# En fuente es la raiz del proyecto; en portable, la carpeta del .exe.
BASE_DIR = runtime_paths.installation_dir()
WEB_DIR = runtime_paths.resource_path("web", base_dir=BASE_DIR)
SERVER_EXE = os.path.join(BASE_DIR, "bedrock_server.exe")
PROPS_PATH = os.path.join(BASE_DIR, "server.properties")
SETUP_MARKER = os.path.join(BASE_DIR, "data", "setup_done.json")

# G8: tiempos de espera de apagado del wrapper (restart / update_bds).
# La GUI espera en DOS fases: primero que BDS muera (server_stopped_event,
# marcado por la linea "[Wrapper] BDS detenido..." del wrapper) y despues que
# el wrapper termine del todo, incluido el backup final de cierre. Antes se
# esperaba el evento de salida del wrapper con un unico timeout de 30s, pero
# ese evento solo llega tras el backup final (tope interno del wrapper: 135s
# de join del worker caliente + 240s del backup final): con un mundo grande
# el reinicio/actualizacion se abortaban siempre aunque BDS ya se hubiera
# detenido, y el mensaje de error era enganoso ("no se detuvo").
SERVER_STOP_TIMEOUT_SEC = 75      # Fase 1: max segundos esperando que BDS muera
                                  # (mayor que BDS_STOP_TIMEOUT_SEC=60 del wrapper:
                                  # el wrapper fuerza el kill y la GUI solo observa)
WRAPPER_EXIT_TIMEOUT_SEC = 450    # Fase 2: max segundos esperando al wrapper completo
                                  # (75 BDS + 135 join worker + 240 backup final + margen)

# Watchdog (gui_backend/services/watchdog.py): opt-in via data/schedule_config.json.
WATCHDOG_POLL_SEC = 5             # Periodo del ciclo de vigilancia
WATCHDOG_STABLE_UPTIME_SEC = 600  # Uptime tras el cual se reinicia el backoff de crashes
WATCHDOG_BACKOFF_SCHEDULE = (30, 60, 120, 300)  # Segundos entre re-arranques consecutivos
WATCHDOG_MAX_CRASH_RESTARTS = 5   # Tope de re-arranques fallidos seguidos (2026-09-25)
