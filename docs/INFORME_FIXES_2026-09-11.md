# Informe de fixes — ronda 2026-09-11

Origen: revisión multi-pase (wrapper, backups, GUI backend, tools/web/frontend)
con cada cita verificada contra el código fuente. Criterio: **solo se arregla
lo verificado como real**. Los falsos positivos quedan documentados abajo para
que ninguna ronda futura los persiga de nuevo.

Regresiones en `tests/test_ronda_2026-09-11.py` (22 tests). Validación de la
ronda: `ruff check .` limpio, `pytest tests -m "not e2e"` 726 verdes / 0 fallos,
`oxlint` 0 errores y `dist/` reconstruido.

## Arreglados

### Críticos

- **A1 — restore de ZIP sin mundo destruía el mundo activo.** El guard de
  `level.dat` en `auto_backup.restore_backup` y `restore_backup.py` (CLI) se
  saltaba con `world_infos == []`: un ZIP vacío o solo-packs pasaba
  `testzip`/límite de expansión, instalaba el staging vacío como mundo y
  borraba el `.bak` del mundo real tras el swap. Ahora `level.dat` se exige
  SIEMPRE en el staging. De paso: las entradas de directorio `server_*` se
  descartan antes de clasificar (antes una `server_resource_packs/` suelta
  iba a parar dentro del mundo).
- **M1 — watchdog de backup abortaba la recolección activa.** El `elif` del
  scheduler (`server_wrapper.backup_scheduler`) medía los 60 s desde
  `save_hold_timestamp` sin excluir `save_query_ready_seen`: como el dispatch
  exige 5 s de silencio, un mundo que tardara más en listar abortaba CADA
  ciclo con "Servidor no respondio a save query" aunque sí hubiera respondido
  (backups automáticos que nunca completan, diagnóstico falso). Ahora hay dos
  condiciones: (a) nunca respondió (mide desde `save_hold_timestamp`) y
  (b) respondió con snapshot vacío estancado (mide desde
  `last_snapshot_update_time`); con archivos recolectados NO se aborta.
- **M2 — `server.properties` no-UTF-8 tumbaba el wrapper.**
  `server_properties.read_value` solo atrapaba `OSError`; un `UnicodeDecodeError`
  (editor ANSI/cp1252, `level-name` con `ñ`) escapaba y —vía
  `auto_backup.WORLD_NAME` en el import— el wrapper no arrancaba más. Ahora
  se lee en bytes y se decodifica línea a línea: la línea corrupta se salta y
  el resto parsea.

### Medios

- **M3** — `tools/enable_beta_apis_v2.py` reescribía `level.dat` sin
  resguardo (su predecesora v1 destruyó uno real). Ahora `shutil.copy2` a
  `<ruta>.respaldo_<nonce>` antes de tocar; el sufijo NO es `.bak_` porque
  `recover_interrupted_restores` renombra todo `*.bak_*` de `worlds/` como
  huérfano al arrancar el wrapper. Falla cerrada: sin resguardo no se escribe.
- **M4** — `_tail_events` (GUI) solo terminaba viendo `wrapper_exit_event`
  seteado, pero el `finally` del hilo viejo lo setea y `_spawn_wrapper_process`
  lo limpia tras el `Popen`: con un restart rápido, el poll de 200 ms que
  cayera en medio dejaba el hilo viejo atrapado leyendo el `.ndjson` muerto
  para siempre (hilo + handle por restart, y el handle bloqueaba en silencio
  la rotación de 7 días de `wrapper_events.py`). Ahora termina también si
  `manager.events_file` apunta a otro canal.
- **M5** — El marcador `"BDS stopped"/"BDS detenido"` en
  `supervisor.run_wrapper_thread` evaluaba la línea cruda sin gate de chat:
  `<Jugador> el BDS stopped jaja` seteaba `server_stopped_event` espurio y un
  `stop_and_wait`/restore posterior creía el mundo quieto con BDS vivo. Mismo
  gate anti-spoofing (`is_chat`) que los demás marcadores.
- **M6** — Ctrl+C esperaba `wait(timeout=15)` + kill; la ruta normal espera
  `BDS_STOP_TIMEOUT_SEC=60`. Un mundo grande volcando chunks recibía
  `TerminateProcess` a mitad del save (LevelDB sucio, backup `cierre_crash`
  sobre mundo sucio). Ahora ambos caminos usan la misma constante.
- **M7** — Los tres `os.walk` del empaquetado (mundo tradicional,
  `static_includes`, packs de servidor) seguían junctions: el guard `realpath`
  solo cubría el modo snapshot. Nuevo `_es_punto_reparse`/`_poda_reparse_points`
  en `auto_backup.py` poda dirs y salta archivos reparse point
  (`os.walk` atraviesa junctions porque `is_symlink()` no las detecta).

### Menores (O1 + BAJA)

- **O1 + BAJA-1** — `routers/system.py` (`POST /api/command`) y
  `routers/websocket.py` marcaban `stop_requested` ANTES del write; el WS
  además se tragaba el error en silencio. Ambos alineados con el patrón de
  `actions.py`/`lifecycle.py` (flag solo tras entrega) y el WS loguea
  echo + error. Mirrors de `test_stop_stdin_roto_devuelve_500_y_no_marca_flag`
  para consola y WS.
- **BAJA-3** — `_force_kill_compress_process` hacía `proc.join()` sin tope
  reteniendo `state_lock`, y limpiaba `*.tmp` sin coordinar: constante nueva
  `WORKER_KILL_JOIN_TIMEOUT_SEC=10` y limpieza tras adquirir el NamedMutex de
  backup no bloqueante (no borra el `.tmp` de un backup ajeno en curso).
- **BAJA-4** — early-return de `create_backup` por mutex ocupado no cerraba
  el handle del `NamedMutex` (fuga por llamada).
- **BAJA-5** — la descarga de BDS no chequeaba el HTTP: un 404/503 se
  guardaba como zip y fallaba después como `BadZipFile` con diagnóstico
  engañoso. Ahora aborta con "HTTP <código>".
- **BAJA-6** — GUI clásica (`web/app.js`): `triggerAction` mostraba
  `solicitada: undefined` en errores HTTP (el 409 parecía éxito); ahora
  reporta `data.detail`/`data.message`/`HTTP <código>` y corta. Terminal con
  tope de 800 nodos (antes crecía sin límite).
- **BAJA-10** — `PermissionError` en la copia caliente solo mapeaba
  `FileNotFoundError` a desync; el antivirus reteniendo un archivo abortaba
  el ciclo sin reintento. Ahora ambos son `SnapshotDesyncError`.
- **BAJA-12** — `iniciar_gui*.bat`: `cd gui_frontend` verificado y retorno
  con `cd /d "%~dp0"` (antes un fallo de cd + `cd ..` salía del repo); IP LAN
  prefiere `192.168.` y luego `10.` antes que "la última de ipconfig" (con
  VPN activa la última suele ser el túnel). React: `ConnectivityCard` copia
  con fallback `execCommand` en HTTP no seguro (`navigator.clipboard` no
  existe fuera de contextos seguros y la GUI LAN corre en `http://IP`);
  `Modal` solo cierra el modal superior con Escape (pila de modales por
  módulo); `SideRays` con flag `disposed` por corrida del effect (el await de
  10 ms dejaba renderers + rAF eternos). `dist/` reconstruido.

## Descartados (falsos positivos — no reabrir)

- **BAJA-2 (TOCTOU re-lectura de `wrapper_process`)**: el patrón
  check-then-use suelto es idéntico al de `send_command` del propio wrapper y
  al resto del codebase; no es una regresión introducida y cambiarlo tocando
  la convención de concurrencia exigiría rediseñar los guards (regla AGENTS:
  no modificar reglas de concurrencia sin tests que lo justifiquen).
- **BAJA-8 (residuos `.failed_*` y `result.json.tmp`)**: los `.failed_*` son
  la EVIDENCIA de un rollback que no pudo restaurar (`_quarantine_and_restore`
  los deja deliberadamente); barrearlos destruiría la única copia del mundo
  anterior a un swap fallido. Los `bw_*.json` de `%TEMP%` ya se limpian en
  todos los caminos del worker (H6-2026-08-28).
- **BAJA-9 (CLI restore a mundo stale)**: `restore_backup.get_world_dir`
  relee `server.properties` cuando el global coincide con el valor del import;
  el caso stale real lo cubre la misma heurística H3 que `auto_backup`
  (cambiar `level-name` en sesión dentro de la CLI no es un escenario real:
  la CLI es un proceso corto y fail-closed con BDS vivo).
- **BAJA-11 (doble backup en frío)**: falso. El chequeo de
  `backup_in_progress` fuera de `op_lock` es el primer filtro, pero
  `lifecycle.cold_backup` re-chequea bajo `op_lock` (FIX G5, test
  `test_backup_frio_recheck_bajo_lock`).

## Ambientales (no eran bugs del repo, pero rompían la suite aquí)

- **pytest.ini**: la starlette instalada emite
  `StarletteDeprecationWarning` (httpx deprecado en `starlette.testclient`,
  pide `httpx2`); con `filterwarnings = error` fallaban TODOS los tests con
  `TestClient` (también los preexistentes). Ignore puntual por mensaje,
  justificado en el propio `pytest.ini` (remedio que AGENTS.md prescribe).
- **tests/test_auto_backup_symlink.py**: `mklink /J` devuelve texto en la
  codepage de la consola y el reader de `subprocess` (UTF-8) lanzaba
  `UnicodeDecodeError` en su hilo lector → `PytestUnhandledThreadExceptionWarning`
  → fallo. La junction sí se creaba; solo fallaba el decode. `errors="replace"`.
- **tests/test_supervisor_tail_events.py**: aislado `manager.events_file`
  (otro test lo deja seteado sin monkeypatch y el chequeo de sesión caducada
  de M4 ahora lee ese atributo legítimamente).
- **tests/test_review_hallazgos.py**: fakes `join()` aceptan `timeout=`
  (lockstep con BAJA-3).
