# Arquitectura del backend de la GUI y del wrapper

Mapa de módulos tras el refactor de `server_gui_server.py` (1.635 líneas) al
paquete `gui_backend/`. El contrato HTTP/WS está en `docs/API_CONTRACT.md`.

## Mapa de módulos

```text
server_wrapper.py                # Entry point de consola + fachada de
                                 #   compatibilidad/re-exports
wrapper_state.py                 # Estado mutable unico, locks y timeouts
wrapper_console.py               # Regex D5, prefijos y parser save query
wrapper_events.py                # Emisor/rotacion del canal IPC NDJSON
wrapper_schedule.py              # Configuracion, persistencia y helpers diarios
wrapper_backup.py                # Worker subprocess, hot backup y cancelacion
zip_safety.py                    # Fuente unica anti-drift: _is_safe_zip_entry, _pack_dest,
                                 #   _extract_pack_entry, _quarantine_and_restore y CORRUPT_MARKERS
server_properties.py             # Lectura tolerante de server.properties (clave = valor,
                                 #   comentarios #/;): fuente unica de los parsers de props
server_gui_server.py            # Punto de entrada: create_app() (middleware de guarda
                                #   temprana /api/*), lifespan, estáticos, uvicorn
gui_backend/
  config.py                     # BASE_DIR, WEB_DIR, SERVER_EXE, PROPS_PATH,
                                #   SETUP_MARKER, timeouts G8, constantes watchdog
  security.py                   # _ensure_local, _is_allowed_origin,
                                 #   _check_origin, _is_safe_zip_entry (re-export de zip_safety)
  metrics.py                    # _measure_process_tree, get_hardware_metrics,
                                #   _sample_disk (disk_usage con caché TTL 30s:
                                #   1 syscall por ventana; ante fallo sirve el
                                #   último valor conocido en vez de tumbar el poll)
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
                                #   reinicio diario, backup diario en frío.
                                #   Ramas del tick aisladas (un fallo no salta
                                #   las demás) y errores internos logueados con
                                #   rate-limit 60s vía manager.add_log
    players.py                  # vista de jugadores (LECTURA): registro propio
                                #   + permissions.json + allowlist.json
    history.py                  # SQLite data/gui_history.db: metricas (30s),
                                #   logs y sesiones; retencion 7d/7d/90d
  routers/
    system.py                   # /favicon.svg, /, /api/status, /api/command, /api/connectivity (IP LAN/publica + puerto)
    properties.py               # /api/server_properties
    setup.py                    # /api/setup_status, install_bds, complete
    actions.py                  # /api/action/{name}, /api/check_update
    backups.py                  # /api/backups*, /api/restore (+ download/delete/verify, listado filtra _CORRUPTO/_EXCEDIDO/_CRASH)
    schedule.py                 # /api/schedule (GET/POST)
    players.py                  # /api/players (GET, solo lectura)
    history.py                  # /api/history/{metrics,logs,sessions} (GET, retencion 1/6/24h y 7d/90d)
    websocket.py                # /ws (Origin puerto-estricto, stdin_lock 6/6)
```

## Wrapper de consola

`server_wrapper.py` sigue siendo el archivo que lanzan los `.bat` y la GUI,
pero funciona como fachada. Su logica propia queda limitada a `send_command`,
`read_stdout`, `backup_scheduler`, `initiate_shutdown`, `read_stdin`, el backup
final y el bloque `__main__`.

- `wrapper_state.py` es el dueño de `state_lock`, `stdin_lock`,
  `backup_ipc_lock`, los timeouts y todo el estado mutable. No se rebindean
  escalares en la fachada; se usa `import wrapper_state as wstate`.
- `wrapper_console.py` es la fuente unica de regex y parsers puros. La fachada
  los re-exporta porque `gui_backend.supervisor` y tests los importan desde
  `server_wrapper`.
- `wrapper_events.py` posee el handle y el lock NDJSON. `EVENTS_DIR` se parchea
  en ese modulo, aunque el emisor se invoque por la fachada. El emisor hace
  `flush+fsync` por evento y rota handle si `WRAPPER_EVENTS_FILE` cambia.
- `wrapper_schedule.py` posee la cache de configuracion (mtime+size, invalida
  ante reescrituras rapidas sub-segundo) y `last_daily_backup_date`; el
  scheduler accede a sus atributos de modulo. `_coerce_schedule_value` ahora
  acepta `"30.0"` y `"  60 "` como entero.
- `wrapper_backup.py` posee el worker y sus helpers. `subprocess.Popen` se
  parchea en ese modulo; el emisor de comandos se inyecta desde la fachada
  para no crear un ciclo al ejecutar el archivo como `__main__`.

La fachada conserva los re-exports de compatibilidad, pero los nombres de
estado movidos no son targets de escritura: producción y tests usan el módulo
dueño. El detalle de acoplamientos y el inventario del movimiento están en
`docs/INFORME_REFACTOR_WRAPPER_2026-08-16.md`.

## Dirección de dependencias (sin ciclos)

```text
config ← security ← metrics ← state ← supervisor ← services ← routers ← app
                      (console_lang, server_wrapper, auto_backup,
                       restore_backup, zip_safety, wrapper_events)
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
  `state.py`; el router WS solo añade/descarta conexiones. El `finally` del
  router cubre TODA la sesión registrada, incluido el envío del `init`: un
  cliente que muere entre `accept()` y el primer send (o un fallo construyendo
  el status) no deja entradas muertas. El guard S3 deriva el puerto esperado
  con la misma fuente única que los endpoints HTTP (`security._get_request_port`).
  Cobertura sin e2e ni httpx: `tests/test_websocket_router.py` ejercita la
  coroutine real con un WebSocket falso.
- El agendado del broadcast (`ServerManager._schedule_broadcast`) es
  BEST-EFFORT y nunca lanza: si el loop referenciado está cerrado (ventana de
  apagado de la GUI, teardown de un TestClient), `run_coroutine_threadsafe`
  lanzaría un RuntimeError sincrónico con corrutina huérfana; el fallo se
  descarta cerrando la corrutina (la fuente autoritativa del estado es
  history + eventos NDJSON, no el broadcast en vivo). El lifespan resetea
  `manager.loop = None` al apagarse para no dejar un loop muerto como global.
  Cobertura: `tests/test_state_broadcast_robustez.py`.
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
  `manager.events_alive` y el parseo de stdout queda como fallback. El lector
  abre con `errors="replace"`: líneas corruptas a nivel JSON **y bytes**
  (UTF-8 truncado por un write interrumpido) se saltan sin matar al hilo.
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
  Las tres ramas del tick (crash-restart, reinicio diario, backup en frío)
  corren aisladas: una excepción en una rama no salta las demás y se loguea
  con rate-limit (1 mensaje/60 s). Si `start_wrapper` lanza, el intento cuenta
  como fallo para el backoff (evita martillear el arranque cada poll).
  Cobertura sin binario: `tests/test_watchdog_simulacion.py` simula el wrapper
  con un Popen falso que pasa por la ruta real de arranque y el hilo lector.
- **En tests el loop de fondo NO corre**: `tests/conftest.py` neutraliza
  `watchdog.start` durante toda la suite (más un guard de las recuperaciones
  del lifespan que apunta a la instalación real). El hilo daemon sobrevive a
  los monkeypatches; si lee configs temporales de otro test con
  `auto_restart_on_crash` podía lanzar wrappers REALES (backups reales, BDS,
  409 espurios). No quitar esos fixtures: ver `docs/INFORME_REVIEW_2026-09-10.md` (F1).

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
  - `test_watchdog_de_fondo_neutralizado_en_la_suite` → exige el fixture de
    `tests/conftest.py` que desactiva el watchdog en tests (F1).
- `test_web_classic_gui.py` → prohíbe interpolar datos en plantillas
  `innerHTML` de `web/app.js` (los datos del servidor van con `textContent`).
- `test_router_guards.py` → inventario OpenAPI de rutas POST/GET de API y 403
  con cliente/Origin externos (la guarda temprana es middleware).
- `test_console_lang_pbt.py` `L_PY_FILES` → lista explícita de archivos con
  llamadas `L(es, en)`; añadir ahí cualquier módulo nuevo con cadenas i18n.

## Arranque

- `iniciar_gui.bat` → `.venv\Scripts\python.exe server_gui_server.py` (`uvicorn.run("server_gui_server:app")`). El `.bat` crea `.venv` (aislado del Python global) e instala `requirements.txt` la primera vez; si la creación falla, usa el `python` del PATH. El bootstrap está serializado entre lanzamientos con un lock-dir efímero (`.venv_bootstrap.lock`, se borra solo; espera hasta 120 s y roba el lock si quedó abandonado): dos dobles clics simultáneos ya no pisan el venv del otro ni corren dos `pip install` en paralelo.
- Puerto `GUI_PORT` (default 8000), salto al siguiente libre ACOTADO a 65535
  (`_resolver_puerto`: avisa una vez por puerto saltado y lanza `RuntimeError`
  al agotarse el rango — el `while` histórico era infinito si nada llegaba a
  enlazar). `_puerto_libre` soporta hosts IPv6 literales (`AF_INET6`).
- `create_app()` monta `/assets` (build de Vite si existe) y `/static` (web/),
  e instala el **middleware de guarda temprana `/api/*`**: `_ensure_local` +
  `_check_origin` antes del routing y de pydantic (un body inválido de cliente
  externo da 403, no 422). Cobertura: `tests/test_router_guards.py` (inventario
  OpenAPI anti-drift + probes).
- `lifespan`: fija `manager.loop`, ejecuta `recover_interrupted_restores()` +
  `recover_interrupted_updates()`, precarga historial SQLite, arranca el bucle
  de métricas cada 2s (incluye sonda externa y persistencia cada 30s) y el
  watchdog (hilo daemon, opt-in). Al apagarse cancela el task de métricas y
  resetea `manager.loop = None` (no dejar un loop cerrado como global).
- Host `GUI_HOST` / modo LAN `GUI_ALLOW_LAN` (opt-in): por defecto solo
  loopback; con `GUI_ALLOW_LAN=1` el entrypoint abre en `0.0.0.0` y los guards
  S1/S3 de `security.py` aceptan IPs privadas RFC1918
  (`_is_allowed_client_host`, `_is_private_ip`). El parsing de la variable es
  fuente única (`security._allow_lan`) y la resolución del host efectivo vive
  en `_resolver_host_gui(allow_lan, GUI_HOST)` (LAN + loopback explícito se
  fuerza a apertura). Cobertura: `tests/test_security_hardening.py`
  (sección LAN) y `tests/test_entrypoint_puerto_lan.py`.
