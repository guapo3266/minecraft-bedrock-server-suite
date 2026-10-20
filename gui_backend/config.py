"""Rutas, puertos y constantes globales del backend de la GUI."""

import os

# Raiz de esta instalacion, calculada desde el modulo y no desde cwd.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(BASE_DIR, "web")
SERVER_EXE = os.path.join(BASE_DIR, "bedrock_server.exe")
PROPS_PATH = os.path.join(BASE_DIR, "server.properties")
SETUP_MARKER = os.path.join(BASE_DIR, "data", "setup_done.json")

# G8: tiempos de espera de apagado del wrapper (restart / update_bds).
# La GUI espera en DOS fases: primero que BDS muera (server_stopped_event,
# marcado por la linea "[Wrapper] BDS detenido..." del wrapper) y despues que
# el wrapper termine del todo, incluido el backup final de cierre. Antes se
# esperaba el evento de salida del wrapper con un unico timeout de 30s, pero
# ese evento solo llega tras el backup final (topes internos del wrapper: join
# del worker caliente + backup final, ambos con piso 135s/240s y ESCALADOS con
# el tamano del mundo, wrapper_state.scaled_backup_timeout_sec): con un mundo
# grande el reinicio/actualizacion se abortaban siempre aunque BDS ya se
# hubiera detenido, y el mensaje de error era enganoso ("no se detuvo").
SERVER_STOP_TIMEOUT_SEC = 75      # Fase 1: max segundos esperando que BDS muera
                                  # (mayor que BDS_STOP_TIMEOUT_SEC=60 del wrapper:
                                  # el wrapper fuerza el kill y la GUI solo observa)
WRAPPER_EXIT_TIMEOUT_SEC = 450    # Fase 2: PISO de la espera al wrapper completo
                                  # (135 join worker + 240 backup final + 75 de holgura).
                                  # La espera efectiva es este piso mas
                                  # wrapper_state.shutdown_extra_sec(bytes del mundo)
                                  # -> lifecycle.wrapper_exit_timeout_sec(): crece con
                                  # el mundo (tope 3600s por backup); no leer este
                                  # valor suelto como el limite real.

# Watchdog (gui_backend/services/watchdog.py): opt-in via data/schedule_config.json.
WATCHDOG_POLL_SEC = 5             # Periodo del ciclo de vigilancia
WATCHDOG_STABLE_UPTIME_SEC = 600  # Uptime tras el cual se reinicia el backoff de crashes
WATCHDOG_BACKOFF_SCHEDULE = (30, 60, 120, 300)  # Segundos entre re-arranques consecutivos
WATCHDOG_MAX_CRASH_RESTARTS = 5   # Tope de re-arranques fallidos seguidos (2026-09-25)
