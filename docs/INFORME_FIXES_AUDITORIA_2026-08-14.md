# INFORME FIXES AUDITORÍA — H-01..H-06 (2026-08-14)

Remediación de los hallazgos críticos de una auditoría externa sobre el wrapper, los backups y la GUI. Commit de referencia: `4fbbbfe` ("fix: remediar hallazgos de auditoria (F6 F1 F2 F5 F4) y refuerzos de seguridad").

## 1. Hallazgos y remediación

| ID | Hallazgo | Solución | Archivos principales | Tests |
|---|---|---|---|---|
| H-01 | Spoofing de chat en stdout: regex sin anclar permitían falsificar conexiones/desconexiones y `save query` (corrupción de `level.dat` a 0 bytes, DoS de backups automáticos) | Regex ancladas a `^` + helper `_strip_log_prefix` + gate anti-chat (línea que tras strip empiece con `<` se descarta para eventos/list/save query), aplicado también en la GUI (`classify_log_line`, tracking de `players_online`) | `server_wrapper.py`, `gui_backend/supervisor.py` | `test_chat_spoofing_defense_no_altera_estado`, PBT `test_parse_chat_lines_always_empty`, lockstep en `test_patrones_bds_centralizados...` |
| H-02 | Snapshot incompleto publicado como backup OK (validación solo exigía `level.dat`; fin de lista por inactividad de 5 s) | Validación estructural: si `db/` existe con archivos en disco, el snapshot debe incluir `level.dat` + descriptor (`db/CURRENT` o `db/MANIFEST-*`); si falta → `SnapshotDesyncError` → reintento con backoff | `auto_backup.py` | `test_snapshot_leveldb_validation_con_or_y_vacio` |
| H-04 | GUI ciega ante instancias externas de wrapper/BDS: restore/update podían operar sobre un servidor vivo tras reinicio de la GUI | Sonda `detect_external_bds()` (NamedMutex + scan psutil excluyendo descendientes de la GUI), campos `external_instance`/`external_instance_reason` en el status, guards 409 en `start`/`update_bds`/`restore` | `gui_backend/services/external_probe.py` (nuevo), `gui_backend/state.py`, `gui_backend/routers/actions.py`, `gui_backend/services/backups.py` | `tests/test_external_probe.py` (6 tests) |
| H-05 | Sin recuperación al arranque tras restore interrumpido (crash entre `rename` → mundo huérfano `.bak_<nonce>`, BDS crea mundo vacío) | `recover_interrupted_restores()`: limpia `.restore_staging_*`, rollback de `.bak_*` si falta el destino, o aislamiento como `.bak_huerfano_<ts>_<nonce>`; invocado en el wrapper (tras el mutex, antes del backup inicial) y en el lifespan de la GUI | `auto_backup.py`, `server_wrapper.py`, `server_gui_server.py` | `test_recover_interrupted_restores_rollback_y_huerfanos` |
| H-06 | `pickle` en `%TEMP%` para IPC del worker (riesgo de ejecución arbitraria) | Migración a JSON UTF-8 con helpers `load_snapshot`/`write_result` en `backup_worker.py`; nonce de nombre intacto | `server_wrapper.py`, `backup_worker.py` | `test_backup_worker_json_roundtrip_unicode_y_errores` (ejercita los helpers reales) |

## 2. Decisiones de diseño (no revertir sin test)

- **No se reintrodujo el chequeo de cobertura de `db/`** (p. ej. exigir ≥1 `.ldb`/`.log` o el 70% de archivos): el snapshot de `save query` es autoritativo y ese tipo de chequeo daba falsos positivos en mundos recién creados (ver `test_cobertura_70_mundo_pequeno_sin_falso_positivo`). La validación exige solo el mínimo estructural: `level.dat` + descriptor cuando el disco tiene base de datos.
- **Descriptor con OR** (`db/CURRENT` **o** `db/MANIFEST-*`): exigir ambos podría dar falsos negativos según la versión de BDS y entrar en backoff eterno (peor que el bug original).
- **El gate anti-chat vive en dos capas**: el parseo del wrapper (`read_stdout`/`parse_save_query_files`) y la clasificación de la GUI (`classify_log_line`). El spoofing de marcadores de backup de la GUI quedó cubierto porque `classify_log_line` devuelve `"info"` para chat ANTES de evaluar los keywords de backup.

## 3. Correcciones adicionales de la revisión

- **Bug real en packs (H-05)**: la primera versión de `recover_interrupted_restores` escaneaba `server_resource_packs`/`server_behavior_packs`; el staging y los `.bak_*` de packs viven en `resource_packs`/`behavior_packs` → residuos sin limpiar. Corregido y cubierto por test.
- **Test de JSON superficial**: el roundtrip probaba `json.dump/load` manual, no el código del worker; ahora ejercita `backup_worker.load_snapshot`/`write_result` (con unicode real: acentos y emoji).
- **Contaminación entre tests**: `test_chat_spoofing_defense_no_altera_estado` mutaba el `players_online` global sin restaurarlo; ahora guarda/restaura en `finally`.

## 4. Lección operativa (e2e)

Correr un test e2e **sin** el filtro `-m "not e2e"` en esta máquina (existe `bedrock_server.exe`) arranca el wrapper real: este retiene el `NamedMutex` durante el backup final de cierre y los tests unitarios posteriores ven **falsos 409 de "instancia externa"** en `/api/action/start` (no es regresión). Además deja `level-name=TestWorld` en el `server.properties` real y puede dejar `worlds/TestWorld` si la limpieza del e2e falla por archivos bloqueados. Documentado en `AGENTS.md`.

## 5. Cambios preexistentes incluidos en el mismo commit

Al commitear la remediación se incluyeron también cambios previos del working tree (misma sesión de trabajo):

- Hardening anti-CSRF: `_is_allowed_origin` valida ahora host **y puerto** (bloquea webs locales en otros puertos); `::1` admitido como host local (`gui_backend/security.py`, `gui_backend/routers/websocket.py`).
- Fix de Job Object: `create_job_object_for_process` cierra el handle y devuelve `None` en las rutas de fallo (`windows_process_guard.py`).
- Resolución dinámica de mundo/backups (`get_world_dir`/`get_backup_dir`/`get_world_name(base_dir)`) y rollback con cuarentena (`_quarantine_and_restore`) en `auto_backup.py` y `restore_backup.py`.

## 6. Verificación

- `python -m pytest tests -m "not e2e"`: **210 passed, 2 deselected, 0 failed** (igual que el baseline previo).
- Warning conocido no bloqueante: `StarletteDeprecationWarning` (httpx → httpx2) del `TestClient` de Starlette 1.3.1; `pip install httpx2` lo silencia si se desea.
