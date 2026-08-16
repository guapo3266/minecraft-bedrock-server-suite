# Arquitectura del backend de la GUI

Mapa de módulos tras el refactor de `server_gui_server.py` (1.635 líneas) al
paquete `gui_backend/`. El contrato HTTP/WS está en `docs/API_CONTRACT.md`.

## Mapa de módulos

```text
server_gui_server.py            # Punto de entrada: create_app(), lifespan,
                                #   estáticos, uvicorn, re-exports mínimos
gui_backend/
  config.py                     # BASE_DIR, WEB_DIR, SERVER_EXE, PROPS_PATH,
                                #   SETUP_MARKER, timeouts G8, constantes watchdog
  security.py                   # _ensure_local, _is_allowed_origin,
                                #   _check_origin, _is_safe_zip_entry
  metrics.py                    # _measure_process_tree, get_hardware_metrics
  state.py                      # ServerManager + singleton `manager` +
                                #   build_public_status() (estado público único)
  supervisor.py                 # _spawn_wrapper_process, run_wrapper_thread
  services/
    properties.py               # PROPS_FIELDS, leer/validar/escribir props
    backups.py                  # listado, guard de restore, verify
    bds_update.py               # Mojang, staging, rollback, recuperación
    setup.py                    # detección de instalación (wizard)
    lifecycle.py                # start_wrapper/restart_wrapper/cold_backup
                                #   (única fuente de esas secuencias: la usan
                                #   el router de acciones y el watchdog)
    schedule_config.py          # data/schedule_config.json: defaults, validación,
                                #   escritura atómica (backups programables)
    watchdog.py                 # opt-in: auto-restart tras crash (backoff),
                                #   reinicio diario, backup diario en frío
    players.py                  # vista de jugadores (LECTURA): registro propio
                                #   + permissions.json + allowlist.json
    history.py                  # SQLite data/gui_history.db: metricas (30s),
                                #   logs y sesiones; retencion 7d/7d/90d
  routers/
    system.py                   # /favicon.svg, /, /api/status, /api/command
    properties.py               # /api/server_properties
    setup.py                    # /api/setup_status, install_bds, complete
    actions.py                  # /api/action/{name}, /api/check_update
    backups.py                  # /api/backups*, /api/restore
    schedule.py                 # /api/schedule (GET/POST)
    players.py                  # /api/players (GET, solo lectura)
    history.py                  # /api/history/{metrics,logs,sessions} (GET)
    websocket.py                # /ws
```

## Dirección de dependencias (sin ciclos)

```text
config ← security ← metrics ← state ← supervisor ← services ← routers ← app
                      (console_lang, server_wrapper, auto_backup, restore_backup)
```

Los routers importan servicios y estado; los servicios no conocen `Request`,
`FastAPI` ni decoradores (solo `HTTPException` como error de dominio). Los
logs de los flujos HTTP los emiten los routers; las operaciones que corren
fuera del ciclo de una petición (`lifecycle`, `watchdog`) loguean directamente
vía `manager.add_log`.

## Reglas de concurrencia (no modificar sin añadir tests)

- `manager` es el **singleton único** creado en `state.py`; nunca crear
  instancias por petición (fragmentaría locks, eventos y el registro WS).
- `manager.lock`: mutaciones y lecturas de `players_online`/`log_history`
  (las mutaciones viven solo en `supervisor.run_wrapper_thread`).
- `manager.stdin_lock`: TODAS las escrituras a `wrapper_process.stdin`
  (6 sitios: command API, command WS, stop y backup caliente en `routers/`,
  restart en `services/lifecycle.py`, update_bds en `routers/actions.py`).
  Hay un test de conteo multi-archivo que exige 6 writes ==
  6 bloques `with manager.stdin_lock:`.
- `manager.op_lock`: exclusión mutua de start/restore/update/backup frío/install.
  `start`/`restart` lo toman sin bloqueo (rechazan con `busy`); restore/update
  lo toman bloqueante dentro de sus hilos. El spawn del wrapper ocurre
  SIEMPRE bajo `op_lock` (FIX G1/G2).
- Eventos G8: `server_stopped_event` (BDS muerto) ≠ `wrapper_exit_event`
  (wrapper terminado, backup final incluido). restart/update esperan en DOS
  fases con `config.SERVER_STOP_TIMEOUT_SEC` (75s) y
  `config.WRAPPER_EXIT_TIMEOUT_SEC` (450s).
- El registro WebSocket (`active_websockets`) y `broadcast()` viven en
  `state.py`; el router WS solo añade/descarta conexiones.
- `build_public_status(manager, players=None)` es la ÚNICA fuente del payload
  de estado (usada por `/api/status`, el `init` del WS y `update_status`):
  el hardware se muestrea ANTES de tomar `manager.lock`; `players` se puede
  pasar ya leído bajo lock para un snapshot atómico con `log_history`.
- `manager.stop_requested`: True = la ausencia del wrapper es esperada
  (nunca arrancó, o alguien lo paró desde la GUI, la consola o el flujo de
  update). Solo un wrapper muerto con False lo trata el watchdog como crash.
  `_spawn_wrapper_process` lo limpia en cada arranque; lo marcan el stop del
  router, el stop del comando de consola, `restart_wrapper` y `update_bds`.

## Canal de eventos NDJSON (IPC estructurada, fase 1)

- El wrapper emite eventos JSON por línea en `data/wrapper_events/<boot>.ndjson`
  (dual-write: los marcadores de consola siguen intactos como fallback).
  Path por env `WRAPPER_EVENTS_FILE` al spawn; emisor a prueba de fallos.
- `supervisor._tail_events` (hilo daemon por sesión) consume el archivo y
  `_apply_event` aplica cada evento; `wrapper_started` activa
  `manager.events_alive` y el parseo de stdout queda como fallback.
- Contrato y fases: `docs/INFORME_IPC_EVENTOS_NDJSON.md`.

## Rollback de versión BDS (data/bds_previous)

- Cada `_download_and_install_bds` exitoso conserva el resguardo de los
  binarios salientes en `data/bds_previous` (`_apply_staged_update` con
  `keep_prev_dir`): solo la última versión anterior (~220 MB).
- `rollback_bds()` reaplica ese directorio con el MISMO `_apply_staged_update`
  (swap simétrico: la versión que se deja de usar pasa a ser la nueva
  "anterior"; deshacer un rollback es otro rollback). `PRESERVE_FILES/PRESERVE_DIRS`
  protegen worlds/properties/permissions/allowlist en ambos sentidos.
- Si la aplicación falla, el rollback interno restaura la instalación y el
  resguardo existente NO se pisa con uno incompleto.
- `lifecycle.stop_and_wait(tag)` centraliza el stop + espera en dos fases G8
  que comparten update_bds y rollback_bds (misma escritura stdin, conteo 6/6).

## Historial persistente (services/history.py, SQLite en data/gui_history.db)

- Tablas: `metrics` (1 fila/30 s desde el loop de metricas del lifespan),
  `logs` y `sessions`. Retención con barrido diario: 7/7/90 días.
- **Sinks**: `history` está arriba en la cadena y state/supervisor no pueden
  importarlo. Se engancha por registro (mismo patrón que `active_websockets`):
  `manager.log_sinks` (invocado desde `add_log`, fuera de `manager.lock`,
  cada sink envuelto en try/except) y `manager.player_event_sinks`
  (invocado desde `run_wrapper_thread` en connect/disconnect).
- `start()` (lifespan) crea tablas, cierra sesiones huérfanas (la GUI al
  morir mata wrapper+BDS vía Job Object) y **precarga `manager.log_history`**
  con los últimos 200 logs continuando `_log_seq`: el init del WS entrega
  historial tras reiniciar la GUI sin cambios de frontend. Al final de la
  precarga añade un marcador `session_start` (solo memoria, no se persiste)
  que el frontend renderiza como divisor entre sesión anterior y actual.
- Todo falla a historial-vacío ante `sqlite3.Error`; la persistencia jamás
  rompe la GUI en vivo.

## Registro de jugadores conocidos (data/known_players.json)

- Las regexes de conexión/desconexión de `server_wrapper` capturan el xuid
  como grupo 2 (`group(1)` sigue siendo el nombre, exigido por tests);
  `supervisor.run_wrapper_thread` llena `manager.players_xuid` bajo
  `manager.lock` y persiste `data/known_players.json` (atómico) via
  `record_player_event`.
- `GET /api/players` cruza ese registro con `permissions.json` y
  `allowlist.json` (solo lectura, tolerante a archivos ausentes/corruptos).
- **REGLA**: la GUI nunca escribe `permissions.json` ni `allowlist.json`.
  Las mutaciones van por comandos de consola de BDS (`op`/`deop`,
  `allowlist add/remove`, `kick`) a través de `POST /api/command`: BDS
  resuelve el xuid, persiste y aplica al vuelo. Esto mantiene el invariante
  de 6 escrituras stdin/6 locks intacto.
- `bds_update.preserve_files` ya preserva ambos archivos al actualizar BDS.

## Programación y watchdog (data/schedule_config.json)

- Config por instalación en `data/schedule_config.json`; sin archivo (o
  corrupto) los defaults reproducen el comportamiento histórico: intervalo
  30 min, backups solo con jugadores, watchdog inactivo.
- El wrapper relee el archivo por mtime en cada tick de `backup_scheduler`;
  la GUI lo escribe atómico (`services/schedule_config.py`). Los defaults
  del wrapper (`SCHEDULE_DEFAULTS`) y de la GUI (`DEFAULTS`) deben coincidir
  (test anti-drift).
- La hora fija de backup diario dispara en caliente aunque no haya
  jugadores; si el servidor está apagado a esa hora, el watchdog hace el
  backup en frío (`trigger="scheduled"`). Cada lado persiste la fecha del
  último disparo (`data/schedule_state_wrapper.json` /
  `schedule_state_gui.json`) para no re-disparar tras un reinicio.
- El watchdog (`services/watchdog.py`) arranca en el lifespan, es daemon y
  opt-in: sin nada activado en la config nunca actúa. Backoff de re-arranques
  `WATCHDOG_BACKOFF_SCHEDULE` que se reinicia tras `WATCHDOG_STABLE_UPTIME_SEC`.

## Convenciones para monkeypatching en tests

- El código de producción llama por **atributo de módulo** en tiempo de
  ejecución (`requests.get`, `subprocess.Popen`, `auto_backup.create_backup`,
  `supervisor._spawn_wrapper_process`, `bds_update_service._download_and_install_bds`),
  nunca con `from x import y` que fija el binding al importar.
- Los tests parchean el módulo donde el código lee el nombre en runtime
  (p. ej. `gui_backend.services.bds_update.requests.get`, no `sgs.requests`).
- Regla lockstep: cada commit que mueve código actualiza en el MISMO commit
  los targets de `monkeypatch.setattr` y los tests que leen el texto fuente,
  y ejecuta `pytest tests -m "not e2e"` completo.

## Tests que inspeccionan texto fuente (actualizados durante el refactor)

- `test_review_hallazgos.py`:
  - `test_gui_busca_la_cadena_exacta_del_wrapper` → lee `gui_backend/supervisor.py`.
  - `test_gui_players_online_bajo_manager_lock` → mutaciones en
    `supervisor.py`, lectura bajo lock en `state.py`.
  - `test_gui_stdin_bajo_stdin_lock` → escaneo multi-archivo
    (`server_gui_server.py` + `gui_backend/**/*.py`).
- `test_console_lang_pbt.py` `L_PY_FILES` → lista explícita de archivos con
  llamadas `L(es, en)`; añadir ahí cualquier módulo nuevo con cadenas i18n.

## Arranque

- `iniciar_gui.bat` → `.venv\Scripts\python.exe server_gui_server.py` (`uvicorn.run("server_gui_server:app")`). El `.bat` crea `.venv` (aislado del Python global) e instala `requirements.txt` la primera vez; si la creación falla, usa el `python` del PATH.
- Puerto `GUI_PORT` (default 8000), salto al siguiente libre (`_puerto_libre`).
- `create_app()` monta `/assets` (build de Vite si existe) y `/static` (web/).
- `lifespan`: fija `manager.loop`, ejecuta `recover_interrupted_updates()`,
  arranca el bucle de métricas cada 2s y el watchdog (hilo daemon, opt-in).
