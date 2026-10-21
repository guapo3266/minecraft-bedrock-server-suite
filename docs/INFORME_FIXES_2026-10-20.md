# Revisión y correcciones — 2026-10-20

Alcance: dos revisiones del mismo día sobre TESTTEST. La primera recorrió el
código completo (backend, wrapper, actualizadores de BDS y de la suite, CLI de
restauración y el flujo del actualizador en el frontend) y confirmó 10 bugs por
lectura de implementación y consumidores; dos se reprodujeron además en Python.
Un undécimo, en el frontend, apareció al documentar el problema conocido de 2.1.0.
La segunda revisó el commit de documentación `b3ad093` (registro de la Release
2.1.1) y dejó 8 hallazgos. No se arrancó BDS ni se ejecutaron los e2e.

## Bugs de código

| # | Hallazgo | Evidencia | Corrección |
|---|---|---|---|
| 1 | El restore devolvía los packs que distribuye BDS | El último backup real tenía 2423 entradas en `server_behavior_packs/vanilla` y 1194 en `vanilla_1.20.10`. `restore_core` reemplazaba cada carpeta: tras actualizar BDS, restaurar un backup anterior dejaba el ejecutable nuevo con los packs vanilla viejos. | `zip_safety.is_bds_pack` decide qué carpetas no se restauran: el registro `data/bds_shipped_packs.json` (unión de las carpetas de cada ZIP oficial que instala o revierte `bds_update`) o, sin registro útil, el patrón de nombres de Mojang. Los addons se siguen restaurando. |
| 2 | Watchdog diario fuera de hora | `_tick_daily_restart` no consumía la fecha con el servidor apagado y `_crossed_daily_time` seguía siendo verdadero el resto del día: el primer arranque se reiniciaba en menos de 5 s. El backup en frío repetía tras el primer Detener el diario que el wrapper ya había hecho en caliente y retenía `op_lock` (Iniciar respondía `busy`). | El reinicio se omite si `manager.start_time` es posterior a la hora de hoy (`_launch_wrapper` lo fija bajo `manager.lock`). El backup en frío se omite si el wrapper anotó el diario de hoy (`wrapper_schedule._load_last_daily_backup_date`). |
| 3 | La fase 1 contaba el backup inicial | El wrapper no lee stdin hasta lanzar BDS. Con un backup inicial de más de 75 s, restart/update/actualización de la suite se cancelaban y después el `stop` encolado apagaba igual el servidor, con `stop_requested=True` y sin re-arranque. | Evento NDJSON `bds_launched` y `manager.wrapper_pre_bds`. `lifecycle._wait_server_stopped` no consume el plazo mientras dure el backup inicial (tope: escala del backup final). Sin backup inicial es la misma espera única de siempre. |
| 4 | `progress.json` obsoleto bloqueaba la ventana | `last_progress()` devolvía cualquier fase. Con la GUI cerrada a mitad o un auxiliar que no arrancó, la ventana quedaba «en curso» para siempre, con Instalar y Comprobar deshabilitados. | Una fase activa sin GUI ni auxiliar vivos se resuelve con `journal.json` (`suite_update._stale_progress`): terminada, revertida, cancelada antes de reemplazar o pendiente de `Recuperar_suite.bat`. Nunca lleva `version` (el navegador recargaría en bucle). |
| 5 | Una actualización de BDS completada se revertía | Si `_save_prev_dir` fallaba tras aplicar (rmtree parcial y `os.replace` sobre la carpeta existente), el manifiesto seguía en `bds_update_prev_*` y `recover_interrupted_updates` revertía la actualización en el siguiente arranque. | Punto de confirmación: el manifiesto se retira al completar la fase 2. `_save_prev_dir` aparta la versión previa con un rename. El fallo posterior es `PreviousVersionNotSaved`: éxito con aviso. |
| 6 | Mundos con coma en el nombre | Reproducido: `parse_save_query_files("Mi mundo, el mejor/db/000005.ldb:1234, …")` perdía el prefijo y cada backup en caliente fallaba con `SnapshotDesyncError`. | `wrapper_console._RE_SAVE_QUERY_ENTRY`: una entrada termina en `:<bytes>` seguido de `, ` o del fin de línea. |
| 7 | Escritor de `server.properties` | Reproducido: con un acento guardado en cp1252, `_write_props_values` lanzaba `UnicodeDecodeError` (500). Con `Server-Name = X` añadía una clave duplicada que el lector ignoraba. | Escritor en bytes con `server_properties.parse_line` (la regla del lector): reemplaza todas las líneas activas de la clave y conserva BOM, saltos de línea y líneas ajenas. |
| 8 | La CLI restauraba con el wrapper vivo | `_server_is_running` solo buscaba `bedrock_server.exe`; durante el backup inicial o el final no hay BDS pero el wrapper lee el mundo. | `_wrapper_holds_mutex`, con la regla por adquisición movida a `windows_process_guard.mutex_held_by_other` (compartida con la sonda de la GUI) y el nombre en `wpg.wrapper_mutex_name`. |
| 9 | Guard de relevo de la suite | Solo lo liberaba la llamada de health del auxiliar tras `complete`; un fallo de esa única llamada dejaba `op_lock` tomado y todo POST en 409. | `release_handoff_guard` no lanza y el loop de métricas lo invoca cada ~2 s. El auxiliar reintenta la confirmación (`confirm_handoff`). |
| 10 | `GET /api/backups` durante una rotación | `getmtime`/`getsize` tras el `glob`: si la rotación del wrapper borraba un ZIP en medio, `FileNotFoundError` → 500. | Un `os.stat` tolerante por ZIP. |
| 11 | El sondeo del frontend no terminaba con `idle` | Hallado al documentar el hallazgo 2 de la revisión de documentación: una pestaña que recordaba una actualización en curso (`sessionStorage`) solo dejaba de sondear con una fase final; si el backend respondía `idle` (sin `progress.json`), seguía para siempre con Instalar y Comprobar deshabilitados. | `suiteUpdateLogic.startProgressPolling` (bucle sin React) decide cada respuesta con `nextPollAction`: `idle` termina, las fases activas, la reconexión y lo desconocido siguen. `dist/` reconstruido. |

## Decisiones

- Packs de BDS: no se excluyen de los backups. Un falso positivo del patrón
  dejaría un addon sin respaldo; solo se dejan de restaurar. Con registro decide
  solo el registro, para que un addon con un nombre parecido siga restaurándose.
  Sin registro (BDS instalado a mano o antes de este cambio): `vanilla` y
  `chemistry` (solos, con `_base` o con versión), `editor`, `experimental_*` y
  `server_*library`. Un registro sin nombres se trata como ausente.
- Fase 1: se espera en la GUI en lugar de cancelar el backup inicial en el
  wrapper. Así se mantiene el contrato de que cada parada produce un backup
  final (lo exige el actualizador de la suite) y no cambia la entrega de los
  comandos escritos durante el arranque. El coste es que BDS arranca para
  cerrarse enseguida.
- Watchdog: con un arranque desconocido (`start_time` nulo) se conserva el
  reinicio, como antes.
- `PreviousVersionNotSaved`: la actualización queda aplicada y el resguardo se
  conserva en `bds_update_prev_*` sin manifiesto, que el recovery ignora.

## Incidente durante la validación

La primera corrida completa de la suite escribió un `data/bds_shipped_packs.json`
vacío en la instalación real: un test existente de `test_review_hallazgos.py`
recorre el pipeline de actualización de BDS con `config.BASE_DIR` real y el apply
simulado. Se borró el archivo (lo había creado la corrida) y se cerró por dos
lados: un registro vacío se lee como ausente (`zip_safety`) y un guard de sesión
de `tests/conftest.py` no escribe el registro en la instalación real. La segunda
corrida no dejó restos.

## Revisión de documentación (`b3ad093`)

| # | Hallazgo | Corrección |
|---|---|---|
| D1 | La evidencia de 2.1.1 sugería probada la ruta real de actualización | Sección 2.1.1 y «Validar sin ejecutar BDS»: el verificador arma la instalación «anterior» con el propio paquete; la transición 2.1.0 → 2.1.1 con el auxiliar de 2.1.0 no se probó. |
| D2 | La guía no daba salida al «Acceso denegado» de 2.1.0 → 2.1.1 | «Problema conocido al actualizar desde 2.1.0» con tres casos según el momento. El auxiliar de 2.1.0 escribe el último aviso fuera de su `try`: el caso más probable es una entrega completa con la ventana atascada, y eso motivó resolver el aviso obsoleto con el diario (fix 4). |
| D3 | «La ofreció solo a instalaciones 2.1.0» | Se ofrece a toda versión anterior con actualizador; en la práctica, 2.1.0. |
| D4 | «Tiene 756 archivos» | El ZIP contiene 757: los 756 del manifiesto más el propio manifiesto. |
| D5 | La sección de validación seguía anclada a 2.1.0 | Ejemplo con 2.1.2 y carpeta nueva por intento; el párrafo del 16 de octubre queda acotado a 2.1.0 y enlaza la evidencia de 2.1.1. |
| D6 | Sin `[Sin publicar]` en el CHANGELOG | Sección creada con las correcciones y un apartado de documentación que incluye el registro de 2.1.1. |
| D7 | Enlaces relativos copiados a las notas de la Release | `tools/release_notes.py` los reescribe contra `main` del repo público: el hash y la evidencia de cada entrega se añaden a `docs/` después de etiquetarla. |
| D8 | El procedimiento con `gh` solo estaba en `AGENTS.md` | «Publicar con GitHub CLI» en la guía: borrador, verificación del `digest`, Latest y descarga posterior. `AGENTS.md` remite a ella. |

## Validación

- `tests/test_revision_2026-10-20.py` reúne 68 regresiones de los 10 bugs, del
  ajuste del aviso obsoleto y de las notas de Release. Contra el código de
  `HEAD` fallan 61; las 7 restantes son controles que fijan el comportamiento
  que debía conservarse.
- Suite completa sin e2e: 1083 aprobadas (2 e2e excluidas). `ruff check .`: sin
  avisos. `tools/set_version.py --check`: versión coherente 2.1.1.
- Frontend (bug 11): `npm run lint` sin avisos, `npm test` con 103 tests en
  verde (7 nuevos de sondeo) y `npm run build`, que regeneró `dist/`.

## Segunda revisión: 8 hallazgos externos

Una revisión posterior del mismo día sobre `790f7b2` reportó 3 P1 y 5 P2. Se
verificaron todos contra el código; ninguno era falso, aunque varios tenían
menos alcance del indicado. Dos se reprodujeron (rollback y ZIP64). Al ejecutar
de verdad el lanzador corregido apareció un fallo previo más grave (fila 9).

| # | Hallazgo | Verificación | Corrección |
|---|---|---|---|
| 1 | Otra GUI recuperaba una operación en curso | Sin exclusión entre GUIs de la misma instalación (el puerto avanza). El recovery de arranque revertía un apply de BDS activo y también borraba el staging de un restore en curso; lo mismo el wrapper y la CLI. | `windows_process_guard.installation_operation` (mutex `BDS_Ops_<hash>`) envuelve aplicar/revertir BDS, el restore de GUI y CLI y los recoveries de GUI (`_recover_installation`) y wrapper. Con el mutex tomado el recovery se omite y el wrapper aborta. |
| 2 | Recovery de un rollback interrumpido | Reproducido: tras morir en la fase 2, el resguardo quedaba sin el EXE, se seguía ofreciendo como v1 y un segundo rollback dejaba EXE-v2 con DLL-v1. | El manifiesto anota el staging (`{"entries", "staging"}`) y el recovery devuelve allí lo ya aplicado. Lee también el formato antiguo. |
| 3 | La CLI comprobaba una sola vez | Un `input()` para elegir y otro para `SI` antes de restaurar, sin volver a mirar. Matiz: con BDS ya abierto, Windows suele impedir el swap. | Re-chequeo bajo el mutex de operación, retenido durante todo el restore. La GUI no arranca (sonda `installation_busy`) y el wrapper se niega. |
| 4 | Junction en la raíz de packs | El backup recorría la raíz redirigida (la poda solo mira subcarpetas) y el restore no la validaba, al contrario que `worlds/`. Requiere una junction creada por el usuario. | `zip_safety.is_redirected_path`: esos packs no se restauran (el mundo sí, con aviso). El backup y el recovery saltan raíces redirigidas. |
| 5 | ZIP64 con más de 2 GiB | Reproducido con Python 3.11.8. En un mundo de Bedrock los archivos pesan MB: casi inalcanzable. | `zinfo.file_size = byte_length` en el escritor del snapshot. |
| 6 | Guardado parcial de la programación | Contradecía el contrato; la GUI siempre envía todo, así que solo afectaba a la API. | `schedule_config.save` combina con lo guardado bajo el mismo lock. |
| 7 | Flag del backup inicial leído una vez | Código de este mismo día: con un stop en los 1-2 s previos a leer `wrapper_started`, la espera volvía a ser fija. | `_wait_server_stopped` sondea mientras `events_alive` sea falso o dure el backup inicial; `_apply_event` fija el flag antes de `events_alive`. |
| 8 | El lanzador del ZIP no instalaba BDS | La rama de `runtime\python.exe` lanzaba el wrapper y salía. | La rama fija `RUN_PY` y `-B` y salta al mismo primer arranque. |
| 9 | `iniciar_servidor.bat` nunca llegaba al wrapper (nuevo) | Ejecutado: «No se esperaba . en este momento.» tras `bds_first_run.py`, con runtime y con `.venv`. El `)` de `(sin respuesta o "no")` cerraba el bloque `if` (`1399d8a`, 2026-08-16). En `iniciar_gui_lan.bat` el mismo patrón hacía salir siempre el aviso de fallo del firewall. | Paréntesis escapados (`^(`/`^)`) y test que analiza todos los `.bat`. Verificado ejecutando el lanzador con un runtime real: éxito, cancelación (2) y error (1). |

Validación de esta ronda: `tests/test_revision_2026-10-20_ronda2.py` (39 tests).
Contra `790f7b2` fallan 23 de los 30 iniciales; los 7 restantes son controles
(staging inseguro, guardado inválido, defaults y plazos que no deben cambiar).
Los tests de los `.bat` detectan las tres líneas rotas de `790f7b2`. La espera
de la fase 1 descuenta el plazo con el timeout de cada espera y no con el
reloj: con un `wait` simulado que vuelve al instante, la primera versión del
arreglo giraba 75 s reales. `test_fase1_sin_backup_inicial_espera_lo_de_siempre`
fija ahora `events_alive`, porque sin el canal confirmado se sondea.

## Riesgo residual

- Sin registro de packs, un addon propio con un nombre como los de Mojang no se
  restaura hasta la siguiente instalación o actualización de BDS desde la suite.
- `confirm_handoff` vive en el auxiliar, que se copia de la instalación actual:
  rige para actualizaciones que partan de la versión que lo incluya. La
  liberación del guard por la propia GUI rige en cuanto se instala.
- La espera de la fase 1 durante el backup inicial está acotada por la escala
  del backup final: un backup inicial aún más lento sigue cancelando la
  operación, como antes.
- En la 2.1.1 publicada, una pestaña que recuerda una actualización en curso
  sigue sondeando si el backend responde `idle`: la guía indica cerrarla. La
  corrección (bug 11) rige desde la versión que la incluya.
- El mutex de operación no impide abrir dos GUIs de la misma instalación; solo
  excluye las operaciones que reescriben archivos y los recoveries. Un recovery
  omitido por estar ocupado se hace en el siguiente arranque.
- Un archivo de más de 2 GiB en el modo tradicional ya usaba el tamaño real
  (`ZipInfo.from_file`); el caso del snapshot se cubrió con un límite reducido,
  no con un archivo real de ese tamaño.
- El lanzador se probó en una carpeta temporal con `runtime\python.exe` real y
  scripts de prueba en lugar de BDS; no se descargó BDS.
