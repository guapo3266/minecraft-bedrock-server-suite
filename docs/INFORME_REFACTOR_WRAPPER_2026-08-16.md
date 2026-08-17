# INFORME REFACTOR WRAPPER - 2026-08-16

Descomposicion incremental de `server_wrapper.py` sin cambiar el entrypoint,
la coreografia de consola, el protocolo de eventos, los timeouts ni la
jerarquia de locks. El archivo conserva el nombre que usan los `.bat` y la
GUI, pero queda como fachada de compatibilidad.

## 1. Objetivo y linea base

`server_wrapper.py` tenia 1.278 lineas y mezclaba estado mutable, parsers del
log, eventos NDJSON, scheduler, ciclo de backup, consola y arranque de BDS.
La linea base previa al refactor fue el commit `4d04a49`; la suite no-E2E
estaba verde con 298 tests seleccionados.

La red de seguridad se añadio primero en `tests/test_wrapper_choreography.py`.
Fija la secuencia de eventos, comandos, prints y flags para exito, error de
snapshot, error operativo, timeout interno y fallo de lanzamiento, incluyendo
la regla de que un watchdog no envia un segundo `save resume`.

## 2. Commits atomicos

| Fase | Commit | Contenido |
|---|---|---|
| 0 | `93268f5` | Tests de caracterizacion del ciclo de backup |
| 1 | `dc636d4` | `wrapper_console.py`: regex, prefijos y parser puro |
| 2 | `be0aa3e` | `wrapper_events.py`: canal NDJSON y rotacion |
| 3 | `5bfff3c` | `wrapper_schedule.py`: config, cache y backup diario |
| 4 | `0d0f708` | `wrapper_state.py`: dueño unico del estado mutable |
| 5 | `e389ee4` | `wrapper_backup.py`: worker y ciclo de backup completo |
| 6 | `ffc36be` | Documentacion y mapa final |

Cada fase mantiene sus cambios de tests lockstep con el movimiento de codigo.
El directorio `.zcode/` ya existia sin versionar y se mantuvo fuera de todos
los commits.

## 3. Mapa final

| Modulo | Responsabilidad |
|---|---|
| `server_wrapper.py` | Entry point, fachada, comandos, stdout, scheduler, apagado, backup final y `__main__` |
| `wrapper_state.py` | `BASE_DIR`, `SERVER_EXE`, timeouts, locks y estado mutable |
| `wrapper_console.py` | Constantes D5, regex ancladas, `_strip_log_prefix`, `parse_save_query_files` |
| `wrapper_events.py` | `EVENTS_DIR`, handle/lock NDJSON, emision, reset de tests y rotacion |
| `wrapper_schedule.py` | Defaults, rutas, cache, fecha diaria, coercion y helpers de decision |
| `wrapper_backup.py` | Marcado de ZIP, retry, cancelacion por archivo, worker subprocess y backup manual |

`server_wrapper.py` re-exporta explicitamente los simbolos que forman la
superficie publica de facto: patrones y parsers, eventos, helpers de schedule,
constantes/locks de estado y los siete simbolos del ciclo de backup.

## 4. Acoplamientos resueltos

### Estado

Las funciones de produccion leen y escriben `wrapper_state` como `wstate.X`.
Esto evita rebinding invisibles de escalares como `server_process`,
`backup_in_progress`, `active_compress_process` y `backup_ipc_lock`. El lock
IPC sigue siendo un `multiprocessing.Lock()` y se reemplaza en el mismo punto
tras matar un worker.

Un guard de fuente en `test_review_hallazgos.py` rechaza asignaciones bare a
los nombres de estado en `server_wrapper.py` y `wrapper_backup.py`.

### Eventos

`wrapper_events.py` es dueño de `_events_lock`, `_events_handle` y
`_events_file_path`. El target canonico para `EVENTS_DIR` es
`wrapper_events.EVENTS_DIR`; el re-export de la fachada no crea un target
operativo alternativo.

### Scheduler

`wrapper_schedule.py` es dueño de `_schedule_cfg_cache` y
`last_daily_backup_date`. `backup_scheduler()` accede a ambos mediante el
modulo, evitando que una asignacion local en la fachada deje de ser visible.

### Worker y comandos

`wrapper_backup.py` usa `wrapper_backup.subprocess.Popen` y mantiene la ruta
del worker como `dirname(abspath(__file__))/backup_worker.py`. Para no importar
la fachada durante la carga ni crear una segunda instancia cuando el entrypoint
corre como `__main__`, `server_wrapper.py` inyecta un callback lambda a
`set_command_sender()`. El callback resuelve el `send_command` actual, por lo
que los monkeypatches de tests siguen funcionando.

## 5. Contratos preservados

- `server_wrapper.py` sigue siendo el archivo ejecutable.
- Los cuatro marcadores bilingues de la GUI permanecen byte-identicos,
  incluido `Backup finalizado` en el `finally` del worker.
- La jerarquia de timeouts y la exclusividad de `state_lock`, `stdin_lock` y
  `backup_ipc_lock` no cambia.
- El worker sigue siendo `subprocess.Popen` con IPC JSON UTF-8 y cancelacion
  cooperativa por archivo; no se reintroduce `multiprocessing.spawn`.
- `gui_backend/supervisor.py` y `watchdog.py` siguen importando desde la
  fachada y no requieren cambios de produccion.
- `auto_backup.py`, `backup_worker.py`, `restore_backup.py` y `gui_backend/`
  no reciben cambios de produccion por este refactor.

## 6. Verificacion

- Fase 0: `6 passed`.
- Fases 1-4: suite no-E2E verde; ultimo resultado antes de mover el worker:
  `305 passed, 2 deselected`.
- Fase 5: `288 passed, 2 deselected` con todos los no-E2E salvo
  `test_pbt_properties.py`; los tests de caracterizacion, inspeccion,
  timeout, i18n, IPC, schedule y estado pasan.
- `test_pbt_properties.py` mantuvo el patron de flake de Hypothesis bajo carga:
  en dos corridas aisladas un caso distinto de rutas (`db/MANIFEST-000001` y
  `..\\..\\Windows\\system32`) supero el deadline de 200 ms (207 ms y 533 ms).
  El test solo toca `auto_backup.py`, que no cambio en el refactor.
- `python -m pytest tests -m e2e -q` ejecuto 2 tests: 1 paso (API real de
  Mojang) y 1 fallo en `test_e2e_gui_flag_backup_in_progress_nunca_true_caliente`.
  El wrapper emitio correctamente `backup_compress_started`, `backup_ok` y
  `backup_finished` en NDJSON, pero el test no observo `last_backup` actualizado
  por la GUI. Se repitio el E2E aislado y fallo en la misma asercion; queda como
  incidencia de smoke existente para investigar, no como verificacion final
  verde del refactor.
- Un smoke HTTP independiente sobre la GUI (arranque real, `/api/status`,
  `/api/action/start`, `/api/action/backup` y `/api/action/stop`) reprodujo que
  `last_backup` seguia en `Ninguno` durante la ventana observada. En el intento
  el backup caliente fue cancelado al finalizar el limite de espera, por lo
  que no se usa como evidencia contra la secuencia del worker.
- Los E2E dejaron procesos y `worlds/TestWorld` tras fallar; se cerraron solo
  los procesos identificados de esas corridas, se borro el mundo creado y se
  verifico que `server.properties` quedo restaurado.

## 7. Rollback

Cada commit de las fases 0-5 es independiente y puede revertirse con
`git revert <sha>`. La fachada solo debe retirarse junto con el modulo de
responsabilidad correspondiente y sus cambios lockstep de tests.
