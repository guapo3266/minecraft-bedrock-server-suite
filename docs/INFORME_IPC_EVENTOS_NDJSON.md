# Informe: Canal de eventos NDJSON wrapper → GUI (IPC estructurada, fase 1)

**Fecha:** 2026-08-16
**Alcance:** `server_wrapper.py` (emisor), `gui_backend/supervisor.py` (lector + aplicador + gate), `gui_backend/state.py`, `tests/test_ipc_events.py` (nuevo)
**Estado:** dual-write activo; eventos autoritativos con fallback a marcadores; deprecación de marcadores pendiente (fase 3)

---

## 1. Qué es

El wrapper emite **eventos de máquina** (JSON por línea, NDJSON) en
`data/wrapper_events/<boot>.ndjson` además de sus prints de consola
actuales (**dual-write**). La GUI los consume con un hilo lector y, al
recibir `wrapper_started`, el canal pasa a ser la **fuente autoritativa**
del estado; el parseo de stdout (los marcadores bilingües) queda como
fallback compilado.

Motivación: eliminar la categoría completa de bugs "texto como protocolo"
(marcadores que rompen en silencio si cambian en un idioma, spoofing de
chat H-01, xuids descartados, desenlaces de backup solo inferibles de
prints). El spoofing desaparece de raíz: un jugador no puede escribir el
archivo de eventos; solo el wrapper lo hace, tras su propio gate de chat.

## 2. Contrato del canal

- Una línea JSON por evento: `{"ts": <ms epoch>, "event": "<nombre>", ...}`.
- El wrapper abre el archivo en append al primer evento, escribe con flush
  inmediato bajo un lock propio (`_events_lock`); **cualquier fallo del canal
  se ignora** (el wrapper sigue funcionando solo con prints).
- Path: la GUI lo fija por env `WRAPPER_EVENTS_FILE` al hacer spawn (un
  archivo por boot del wrapper); sin env (modo consola standalone) el
  wrapper genera el suyo en el mismo directorio — el canal está siempre
  activo y sirve de debugging.
- Rotación: al arrancar, el wrapper borra archivos del directorio con mtime
  > 7 días.
- El lector de la GUI (`_tail_events`) es tolerante: espera el archivo si
  aún no existe, salta líneas corruptas, ignora eventos desconocidos
  (compatibilidad futura) y drena lo pendiente tras la muerte del wrapper.

## 3. Esquema de eventos (v1)

| evento | campos | punto de emisión (wrapper) | efecto en la GUI |
|---|---|---|---|
| `wrapper_started` | pid, initial_backup | `__main__` tras mutex + recuperación de restauraciones | `manager.events_alive = True` (activa el gate) |
| `shutdown_initiated` | reason | `initiate_shutdown` (junto al print "Apagado iniciado") | log informativo bilingüe |
| `server_stopped` | returncode | `__main__` finally (junto al marcador G8 "BDS detenido") | `server_stopped_event.set()` |
| `version_captured` | version | eco de la línea `Version: x` en `read_stdout` (detección NUEVA en el wrapper) | `manager.installed_version` |
| `player_connected` | name, xuid | match de `_RE_PLAYER_CONNECT` (tras el gate de chat) | players_online/xuid + registro + sinks |
| `player_disconnected` | name, xuid | match de `_RE_PLAYER_DISCONNECT` | discard + registro + sinks |
| `backup_compress_started` | files | `execute_backup_worker` (marcador de inicio de compresión) | `backup_in_progress = True` |
| `backup_ok` | zip | rama de éxito de la compresión | flag False + `last_backup_time` |
| `backup_finished` | outcome: success/failed/timeout/watchdog/launch_error/exception | finally de `execute_backup_worker` (H3) | flag False incondicional |

Nota: `"Backup completed"/"Backup completado"` era un match muerto en la GUI
(el wrapper nunca lo imprimió); su rol lo cubre `backup_ok`.

## 4. Semántica del gate (fallback)

- `manager.events_alive` se resetea a `False` en cada arranque
  (`_spawn_wrapper_process` y `run_wrapper_thread`) y solo el lector lo
  pone a `True` al recibir `wrapper_started`.
- Con `events_alive == True`: los handlers regex de stdout (jugadores,
  marcadores de backup, captura de versión) se **saltan** — una única fuente
  de verdad, sin dobles registros ni sesiones duplicadas.
- Con `events_alive == False` (wrapper viejo, canal muerto, archivo
  ilegible): el parseo de stdout es autoritativo — **comportamiento
  idéntico al histórico**.
- El marcador `"BDS stopped"` se procesa SIEMPRE (sin gate): `Event.set()`
  es idempotente y es red de seguridad ante un canal caído a mitad de
  sesión.

Orden garantizado en producción: el wrapper escribe `wrapper_started`
antes de arrancar BDS, de modo que el gate siempre está activo antes de que
llegue cualquier línea de jugador/versión de stdout.

## 5. Fases de migración

1. **Dual-write + eventos autoritativos con fallback** (ESTE informe): los
   marcadores bilingües siguen existiendo y sus tests de fuente intactos.
2. *(futura)* Verificación de estabilidad en producción.
3. *(futura)* Deprecación: eliminar los marcadores de estado del wrapper y
   el parseo de la GUI; los prints quedan solo como texto humano. Requiere
   actualizar `test_review_hallazgos.py` (marcadores) y
   `INFORME_CONSOLA_BILINGUE_ES_EN.md` en el MISMO commit.

Criterio sugerido para fase 3: varias semanas de operación real con los
eventos como fuente autoritativa sin incidentes (verificar en
`data/wrapper_events/` que cada boot empieza con `wrapper_started`).

## 6. Verificación

- `tests/test_ipc_events.py` (14 tests): emisor (NDJSON válido, fallo
  silencioso, rotación), emisión desde `read_stdout` con líneas reales
  (incluido chat suplantado que NO genera evento), aplicador evento a
  evento (idempotencia, desconocidos, basura), lector end-to-end sobre
  fixture, gate en ambos sentidos y spawn (env + sin efectos en disco).
- Suite completa: 290 passed (`-m "not e2e"`).
- Prueba real en vivo (2026-08-16): boot del servidor con
  `wrapper_started` → `version_captured 1.26.43.1` → backup periódico
  `backup_compress_started` → `backup_ok` (zip real) consumidos por la GUI.
