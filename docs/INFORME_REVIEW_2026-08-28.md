# INFORME REVIEW 2026-08-28 — Hallazgos H1–H7 de la revisión read-only

Fecha: 2026-08-28
Alcance: revisión de corrección del repo completo (read-only, ~5.1k líneas de
producción: wrapper, `auto_backup`/`restore_backup`, `gui_backend/`, entrypoints
`.bat`, frontend) seguida de verificación de cada hallazgo con scripts reales y
de su corrección. Metodología y evidencia reproducible en la conversación de la
review; este informe resume los 7 hallazgos, sus fixes y la cobertura de tests.

Estado de verificación: suite completa verde **423 passed, 2 deselected (e2e),
0 failed** tras los fixes, más la nueva suite de regresión
`tests/test_review_ronda9_2026-08-28.py` (21 tests, cada uno RED contra el
código pre-fix).

---

## Resumen

| # | Hallazgo | Severidad | Estado |
|---|----------|-----------|--------|
| H1 | `wrapper_events`: un archivo NDJSON por evento en modo standalone | Media (evidencia real: 47 archivos ≤120 B en `data/wrapper_events`) | CORREGIDO |
| H2 | Guard de arranque del wrapper por-existencia (`already_exists`) | Media (falsos abortos de arranque; reabre en miniatura el incidente de las dos GUIs) | CORREGIDO |
| H3 | `auto_backup`: global `WORLD_DIR` stale + mezcla con `get_world_dir()` | Media (backup silencioso del mundo viejo; arcnames `../` irrecuperables en el caso default) | CORREGIDO |
| H4 | `stop` por WebSocket no marca `stop_requested` → el watchdog revive el servidor | Baja-media (latente: el frontend usa `/api/command`) | CORREGIDO |
| H5 | `_quarantine_and_restore`/`_extract_pack_entry` duplicadas + marcadores divergentes GUI/CLI | Baja (drift real ya producido: `cierre_crash` visible solo en CLI) | CORREGIDO (centralizado) |
| H6 | Excepción general del worker deja `bw_snap_*.json` huérfano en `%TEMP%` | Baja | CORREGIDO |
| H7 | Nits: `\n` inyectable en `server.properties`, binding stale re-exportado, `L` muerto, race benigna en `history._connect`, `release-notes.txt` trackeado | Baja | CORREGIDO |

Metodología: cada hallazgo se verificó con ejecución real (2 scripts en
`%TEMP%` que tocan solo directorios temporales) antes de tocar código. Tras los
fixes, los mismos scripts ya no reproducen los bugs, y cada uno quedó fijado
por un test de regresión.

---

## Fix H1 — eventos NDJSON: 1 archivo por boot, no por evento

**Que**: `_events_path()` componía la ruta standalone con timestamp+nonce en
CADA llamada; `_emit_event` reabre el handle si la ruta cambia → cada evento
creaba su propio `.ndjson` de una línea. Solo la GUI lo evade (fija
`WRAPPER_EVENTS_FILE` en `_spawn_wrapper_process`); `iniciar_servidor.bat`
nunca lo fija.

**Evidencia real**: `data/wrapper_events/` con 76 archivos, 47 de ≤120 B
(un solo evento), hasta 9 en el mismo segundo.

**Fix**: sufijo `_standalone_suffix` generado una sola vez por proceso
(`wrapper_events.py`); `_reset_events_for_tests` también lo limpia (los tests
que parchean `EVENTS_DIR` siguen funcionando porque la ruta se resuelve con el
`EVENTS_DIR` vigente en cada emit).

**Tests**: `test_events_standalone_un_archivo_por_proceso`,
`test_events_reset_for_tests_limpia_cache_standalone`.

---

## Fix H2 — guard de arranque SOLO por adquisición

**Que**: `server_wrapper.py __main__` abortaba con
`wrapper_mutex.already_exists or not acquire(...)`. El `already_exists` de
`CreateMutexW` dispara con cualquier handle abierto del objeto — incluido el de
la sonda del loop de métricas de la GUI (cada 2 s, cuando el wrapper no corre),
o de otra GUI de la misma instalación. Ventana sub-milisegundo por poll: falso
"Ya hay una instancia" justo cuando la GUI lanzaba el wrapper, con crash
posterior si el watchdog estaba activo.

**Verificación**: proceso ajeno abriendo el handle sin retener →
`already_exists=True`, `acquire(100ms)=True` (aborta sin motivo); con un
titular real, el `acquire` falla solo y ya detecta el conflicto → el término
`already_exists` es inerte y solo produce falsos abortos.

**Fix**: `if not (acquire(100) or acquire(100)):` — mismo patrón por
adquisición + reintento corto que `_wrapper_mutex_held_by_other`
(`external_probe.py`), regla ya documentada en AGENTS para la sonda.

**Tests**: `test_arranque_wrapper_no_aborta_por_existencia` (anti-drift textual:
`already_exists` no puede volver al guard),
`test_named_mutex_abierto_sin_adquirir_no_bloquea_arranque` (semántica Win32;
el retenedor corre en OTRO hilo porque los mutex son reentrantes por hilo).

---

## Fix H3 — mundo resuelto al vuelo (procesos largos)

**Que**: `create_backup` mezclaba el global `WORLD_DIR` (calculado al importar)
con `get_world_dir()` (dinámico). En la GUI (proceso longinquo): tras cambiar
`level-name` sin reiniciar la GUI, el backup frío y el preventivo de update
empaquetaban el mundo VIEJO en silencio; y si al importar el nivel era el
default "Bedrock level", la divergencia global-vs-dinámico producía arcnames
`../<mundo>/...` en modo snapshot → ZIP irrecuperable (`_is_safe_zip_entry`
rechaza `..`).

**Matices verificados**: el heuristic de `get_world_dir()` no distingue
monkeypatch de test de staleness natural (devolvía el global stale); la
variante `../` exige que el import fuera con el nombre default; el daño
realista es el backup del mundo equivocado.

**Fix**:
- `auto_backup._IMPORT_TIME_WORLD_DIR`: instantánea del valor de import.
  `get_world_dir()` devuelve el global SOLO si difiere de la instantánea
  (monkeypatch de tests, convención intacta para toda la suite `_setup_env`);
  si coincide con ella, RELEE `server.properties` (proceso longinquo apunta al
  mundo real).
- `create_backup` resuelve `world_dir = get_world_dir()` y
  `backup_dir = get_backup_dir()` al INICIO de cada corrida y no toca los
  globales crudos (7 referencias sustituidas): dentro de un backup mundo y
  arcname salen de la MISMA resolución — la divergencia es imposible por
  construcción.
- Backup de emergencia por crash unificado con el cierre normal:
  `execute_final_backup(trigger="cierre_crash")` (mismo `external_lock` y
  `wait_lock_timeout_sec`; antes un lambda sin lock).

**Compatibilidad**: los helpers que parchean `WORLD_DIR`/`BACKUP_DIR`
(`_setup_env` en 4 suites) siguen funcionando: el global parcheado difiere de
la instantánea y se respeta. Suite completa verde sin tocar esos tests.

**Tests**: `test_get_world_dir_relee_properties_sin_patch`,
`test_get_world_dir_respetona_el_parche_de_tests`,
`test_backup_snapshot_sin_arcnames_escape`, `test_backup_frio_usa_mundo_...`
(end-to-end con instalación falsa),
`test_cierre_crash_comparte_lock_y_tope_del_cierre_normal`.

---

## Fix H4 — stop por WS = stop deliberado

**Que**: el router WebSocket acepta `{"type":"command","command":"stop"}` y lo
escribe al stdin del wrapper sin marcar `manager.stop_requested` (a diferencia
de `POST /api/command`, que sí lo hace). Con `auto_restart_on_crash` el
watchdog contaba el stop como crash y re-lanzaba el servidor contra la voluntad
del usuario (verificado con la cadena completa del watchdog). Variante
multi-línea: `"list\nstop"` en `/api/command` tampoco marcaba el flag.

**Fix**: en `websocket.py` y `system.py` el flag se marca comparando por LÍNEA
(`"stop" in {line.strip().lower() for line in cmd.splitlines()}`) — cubre el
caso simple y el multi-línea. Invariante de 6 bloques `stdin_lock` intacta.

**Tests**: `test_ws_stop_command_marca_stop_requested`,
`test_ws_comando_no_stop_no_toca_stop_requested`,
`test_ws_stop_multilinea_marca_stop_requested`.

---

## Fix H5 — fuente única anti-drift ampliada

**Que**: `_quarantine_and_restore` (58 líneas), `_extract_pack_entry` y las
listas de marcadores estaban duplicadas entre `auto_backup.py` y
`restore_backup.py` (y una tercera en `services/backups.py`), con las mismas
condiciones de drift que ya provocaron la creación de `zip_safety.py`. Ya
habían divergido: la GUI ocultaba los backups `cierre_crash` de la lista de
restauración y la CLI los mostraba (verificado con el mismo directorio).

**Fix**: `zip_safety.py` pasa a ser fuente única también de
`_quarantine_and_restore`, `_extract_pack_entry` y `CORRUPT_MARKERS`
(`("_CORRUPTO", "_EXCEDIDO", "_CRASH", "_crash")`); `auto_backup.py`,
`restore_backup.py` y `services/backups.py` los re-exportan como alias
(idéntico patrón al contrato de `_is_safe_zip_entry`/`_pack_dest`). Política
canónica: lo que la GUI oculta lo oculta la CLI (conservador: los marcadores
rigen a la vez rotación y listas restaurables). −170 líneas de duplicación.
AGENTS.md y `docs/ARCHITECTURE.md` actualizados con el nuevo alcance.

**Tests**: `test_funciones_restauracion_identidad_alias`,
`test_corrupt_markers_consenso_guicli_rotacion`,
`test_listas_guicli_coinciden_mismo_directorio` (mismo directorio → misma
vista). El contrato anti-drift de `test_pbt_properties.py:548` sigue verde
(identidad de alias) y `L_PY_FILES` se actualizó (+`zip_safety.py`,
−`external_probe.py` que ya no usa `L`).

---

## Fix H6 — limpieza incondicional de temporales del worker

**Que**: `execute_backup_worker` borraba `bw_snap_/bw_cancel_/bw_result_` de
`%TEMP%` en timeout, éxito y launch_error, pero la rama `except Exception`
general no: una excepción inesperada (verificado: `poll()` del subproceso
lanzando) dejaba `bw_snap_*.json` huérfano.

**Fix**: `_snap_path = _marker = _result = None` al inicio y limpieza
`os.remove` en el `finally`, DESPUÉS del `print` bilingüe de fin y del emit de
`backup_finished` — el marcador de fin incondicional (contrato IPC fallback)
sigue primero e intocable; un fallo borrando archivos no puede tragárselo.

**Tests**: `test_excepcion_worker_limpia_temporales`,
`test_fin_de_ciclo_sigue_incondicional_en_finally` (orden marcador→limpieza).

---

## Fix H7 — nits

1. **Inyección en `server.properties`**: `server-name` aceptaba `\n` y
   `_write_props_values` escribe línea a línea → inyectaba claves arbitrarias
   fuera de la lista editable (verificado: `Hacked\nserver-port=1` produce las
   dos líneas). Fix en `_validate_props`: rechaza cualquier carácter de control
   en cualquier valor, y los ints deben ser canónicos (`raw == str(int(raw))`:
   fuera `" 12 "`, `"+12"`, `"012"`).
2. **Binding stale en la fachada**: `server_wrapper.py` re-exportaba
   `last_daily_backup_date` (copia del binding de import; toda mutación real va
   por `wrapper_schedule.X`). Fuera del re-export, con comentario que explica
   la regla.
3. **Import muerto**: `external_probe.py` importaba `L` sin usarlo.
4. **Race en `history._connect()`**: creación de conexión SQLite fuera de lock
   con doble-check razonable pero parcial; ahora `_connect_lock` propio con
   doble verificación (los callers toman `_lock` después; sin ciclo).
5. **`release-notes.txt`**: artefacto del zip de Mojang que `_apply_staged_
   update` sobreescribe en cada update — fuera de git (`git rm --cached`) y en
   `.gitignore`. En una instalación queda como dato local; en el repo desnudo
   el fallback de `check_update` simplemente se salta.

**Tests**: `test_validate_rechaza_saltos_de_linea_inyectables`,
`test_validate_rechaza_enteros_no_canonicos`, `test_validate_aceita_valores_
normales`, `test_fachada_no_reexporta_scalares_mutables`.

---

## Compatibilidad y riesgos residuales

- Sin cambios de API HTTP/WS, de esquema de SQLite, de frontend (no hay rebuild
  de `dist/`) ni del grafo de dependencias. Sin cambios de timeouts.
- Invariantes de texto de `test_review_hallazgos.py` intactas: 6 escrituras a
  stdin == 6 bloques `with manager.stdin_lock:`, marcador
  `[Worker] Backup finalizado` en `finally`, etc.
- Cambio de política visible para el usuario: la CLI `restore_backup.py` ya NO
  lista los backups `cierre_crash` (antes sí; ahora coincide con la GUI y con
  la rotación). Sigue siendo posible restaurarlos renombrando el zip.
- Riesgo residual NO corregido (decisión de feature, fuera de alcance): **modo
  LAN sin autenticación** — con `GUI_ALLOW_LAN=1` cualquier equipo de la red
  privada opera la consola completa. Mitigación sugerida: token compartido
  (`GUI_LAN_TOKEN`) o acotar por firewall.
- Riesgo residual aceptado: hilo `_tail_events` de una sesión vieja puede
  quedar sondeando el archivo de eventos anterior en restarts muy rápidos
  (TOCTOU del clear de `wrapper_exit_event`); leak de 1 hilo por boot, se
  limpia en el siguiente stop.

---

## Post-e2e: endurecimiento del e2e oficial y causa raíz del huérfano

Al validar los fixes con el e2e real (GUI + wrapper + BDS + backup caliente),
la corrida dejó un **huérfano**: wrapper+BDS vivos ~10 min reteniendo el
`NamedMutex`, sin `shutdown_initiated` en el canal NDJSON — el `POST
/api/action/stop` nunca llegó a procesarse. El test PASABA igual porque su
limpieza no asertaba el stop.

**Descarte de regresión (H1–H7)**, verificado antes de tocar nada:
- La cadena de stop está intacta en el diff (`actions.py` sin cambios;
  `read_stdin`/`initiate_shutdown`/`send_command` sin tocar).
- Repro standalone (wrapper + `stop` por stdin, sin GUI): PASS — apagado
  limpio en 9.9 s, `shutdown_initiated` + `server_stopped` + backup de cierre
  + exit 0.
- Repro del flujo GUI real en el estado exacto del e2e (BDS arriba + backup
  caliente + stop por API): PASS — `running=False` en 10.0 s.
- Firma idéntica pre-existente: el boot e2e del 2026-08-24 23:53 (anterior a
  los fixes) también termina sin shutdown y con su zip borrado por la
  limpieza del test.

**Causa raíz (no es concurrencia, es I/O)**: el e2e lanzaba la GUI con
`stdout=subprocess.PIPE` y nunca lo drenaba (solo lo leía si la GUI moría al
arrancar). Uvicorn loguea cada `/api/status` y el test sondea cada ~0.15 s:
el buffer del pipe de Windows (~4–8 KB) se llena en 1–2 minutos → **la GUI se
congela al escribir el access log** → el event loop deja de procesar el stop →
árbol huérfano. El freeze ocurría DESPUÉS de las aserciones del cuerpo, por lo
que el test "pasaba" de forma determinista dejando el huérfano. Los repros
manuales pasaban porque redirigían el stdout de la GUI a archivo.

**Fix (test-only)**:
- `finally` endurecido: aserta que el stop completó (`running=False`),
  mata el árbol GUI→wrapper→BDS con `taskkill /F /T` (el Job Object
  KILL_ON_JOB_CLOSE del wrapper se lleva al BDS) y verifica con psutil que ni
  wrapper ni BDS de ESTA instalación sobreviven (con matanza manual de última
  red). Los asertos solo se lanzan si el cuerpo no estaba ya fallando
  (`sys.exc_info()`), para no enmascarar el fallo original.
- stdout de la GUI **a archivo** (no bloquea), borrado en el `finally`; el
  camino de "GUI murió al arrancar" ahora lee ese archivo.

**Validación**: e2e 2/2 passed (2:07, antes 3:39 — ya no hay congelación),
`server.properties` restaurado byte a byte, cero procesos/logs residuales.
AGENTS.md actualizado (bala de e2e).

---

## Verificación

- Suite completa: `python -m pytest tests -m "not e2e"` → **423 passed,
  2 deselected, 0 failed** (110 s).
- Scripts de verificación previos (post-fix): H1/H5/H6/H7 dejan de reproducir;
  H2 confirmado vía tests nuevos; H3 en su forma de producción (global ==
  valor de import + properties cambiadas) queda cubierto por los tests
  end-to-end; la variante simulada del script viejo ahora falla cerrada
  ("Snapshot file not found" aborta el backup en vez de producir un ZIP con
  `../`).
