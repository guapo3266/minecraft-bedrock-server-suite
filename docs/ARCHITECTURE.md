# Arquitectura del backend de la GUI

Mapa de módulos tras el refactor de `server_gui_server.py` (1.635 líneas) al
paquete `gui_backend/`. El contrato HTTP/WS está en `docs/API_CONTRACT.md`.

## Mapa de módulos

```text
server_gui_server.py            # Punto de entrada: create_app(), lifespan,
                                #   estáticos, uvicorn, re-exports mínimos
gui_backend/
  config.py                     # BASE_DIR, WEB_DIR, SERVER_EXE, PROPS_PATH,
                                #   SETUP_MARKER, timeouts G8
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
  routers/
    system.py                   # /favicon.svg, /, /api/status, /api/command
    properties.py               # /api/server_properties
    setup.py                    # /api/setup_status, install_bds, complete
    actions.py                  # /api/action/{name}, /api/check_update
    backups.py                  # /api/backups*, /api/restore
    websocket.py                # /ws
```

## Dirección de dependencias (sin ciclos)

```text
config ← security ← metrics ← state ← supervisor ← services ← routers ← app
                      (console_lang, server_wrapper, auto_backup, restore_backup)
```

Los routers importan servicios y estado; los servicios no conocen `Request`,
`FastAPI` ni decoradores (solo `HTTPException` como error de dominio). Los
logs los emiten siempre los routers, nunca los servicios.

## Reglas de concurrencia (no modificar sin añadir tests)

- `manager` es el **singleton único** creado en `state.py`; nunca crear
  instancias por petición (fragmentaría locks, eventos y el registro WS).
- `manager.lock`: mutaciones y lecturas de `players_online`/`log_history`
  (las mutaciones viven solo en `supervisor.run_wrapper_thread`).
- `manager.stdin_lock`: TODAS las escrituras a `wrapper_process.stdin`
  (6 sitios: command API, command WS, stop, restart, backup caliente,
  update_bds). Hay un test de conteo multi-archivo que exige 6 writes ==
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

- `iniciar_gui.bat` → `python server_gui_server.py` (`uvicorn.run("server_gui_server:app")`).
- Puerto `GUI_PORT` (default 8000), salto al siguiente libre (`_puerto_libre`).
- `create_app()` monta `/assets` (build de Vite si existe) y `/static` (web/).
- `lifespan`: fija `manager.loop`, ejecuta `recover_interrupted_updates()`
  y arranca el bucle de métricas cada 2s.
