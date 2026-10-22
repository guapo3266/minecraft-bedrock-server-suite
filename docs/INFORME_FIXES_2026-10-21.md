# Revisión y correcciones — 2026-10-21

Alcance: revisión del repositorio completo con cinco subagentes (Claude Sonnet
5.5, esfuerzo máximo), cada uno sobre un área, con verificación antes de
reportar. Dejó 31 hallazgos: 10 de gravedad media (M) y 21 baja (L). Antes de
corregir, los 31 se reprodujeron en esta máquina con el código real: scripts ad
hoc sobre instalaciones temporales, la GUI real en el navegador y los
lanzadores ejecutados en carpetas temporales. Todos resultaron reales. No se
arrancó BDS ni se ejecutaron los e2e. Tampoco se ejecutaron
`iniciar_gui_lan.bat` (toca el firewall) ni el script de Defender (pide UAC):
sus correcciones se probaron con copias y sustitutos en carpetas temporales.

## Hallazgos

| # | Hallazgo | Evidencia | Corrección |
|---|---|---|---|
| M1 | Corchetes en la ruta de backups o de la instalación | Con la carpeta `...\Respaldos [HDD]\...`, `glob` leía `[HDD]` como una clase de caracteres: la GUI y la CLI listaban 0 backups, la rotación no encontraba ninguno (quedaban los 21) y el `.tmp` huérfano no se limpiaba. Con la instalación en `...\Servidor [Survival]` no se veían los `bds_update_prev_*` de una actualización interrumpida. | `glob.escape` de la carpeta en `auto_backup` (huérfanos y rotación), `gui_backend/services/backups.py`, `restore_backup` (CLI), `wrapper_backup` (limpieza tras matar el worker) y `bds_update.recover_interrupted_updates`. Test anti-drift sobre todo `glob.glob` de producción. |
| M2 | La configuración de BDS editada se perdía al actualizar o revertir | `config/default/permissions.json`, `packetlimitconfig.json` y `profanity_filter.wlist` vienen en el ZIP oficial y no estaban en `PRESERVE_FILES`: tras actualizar quedaban los de fábrica. | Tratamiento tipo *conffiles* de dpkg (`bds_update.CONFIG_FILES`): un archivo editado se conserva y la versión de fábrica nueva va a `data/bds_config_defaults/`; uno sin editar se actualiza. Decide el registro `data/bds_shipped_config.json` (SHA-256 de fábrica instalado); sin registro, la fecha (a más de 600 s de la de `bedrock_server.exe` = editado). Revertir respeta lo editado y olvida el registro. |
| M3 | Backup en frío con un servidor externo | Con un wrapper de esta instalación vivo fuera de la GUI, `start` respondía 409 pero `POST /api/action/backup` respondía 200 y `create_backup` copiaba un LevelDB que se estaba escribiendo. | 409 en el endpoint y re-chequeo bajo `op_lock` en `lifecycle.cold_backup` (el watchdog diario llega directo a esa función). |
| M4 | El wrapper con la GUI muerta | La GUI es el único lector del stdout del wrapper. Muerta ésta, cada `print` lanzaba `OSError(22)`: el scheduler dejaba de iniciar backups, el worker dejaba BDS en `save hold` sin `save resume` y el estado colgado, y el backup de cierre fallaba. | `console_lang.proteger_salida_consola()` (`_SalidaTolerante`: descarta la salida una vez rota la tubería y reemplaza lo que la consola no codifica) es lo primero del `__main__` del wrapper y de `backup_worker._main`. |
| M5 | La segunda actualización de la suite fallaba | La GUI relanzada por el auxiliar tiene `recovery/gui.log` abierto como stdout. Archivar `recovery/` en `previous_*` daba WinError 32 y `shutil.move` dejaba una copia a medias en cada intento. | El auxiliar escribe el log en `data/suite_updates/gui.log` (rotado a 5 MiB). La GUI archiva con `suite_update._archive_job`: rename o, si falla, entrada por entrada, copiando el archivo que siga abierto. |
| M6 | Diario terminado en una instalación movida o copiada | `recover()` validaba las rutas absolutas del diario antes de mirar la fase. Con la carpeta movida y el diario `complete`, `Recuperar_suite.bat` salía con 1 e `iniciar_gui.bat` se cerraba sin abrir nada ni mostrar el motivo. | El auxiliar mira primero la fase y `Recuperar_suite.bat` también, con el Python auxiliar (cubre los auxiliares de 2.2.0 o anteriores). Los lanzadores lo llaman con `--sin-pausa` y muestran el error con una sola pausa. |
| M7 | Dos instalaciones con el mismo nombre compartían la carpeta de backups | `C:\Servers\Survival\Suite` y `C:\Servers\Creative\Suite` resolvían `<raíz>\Suite`: la rotación de una borraba los backups de la otra y la GUI ofrecía restaurar el mundo ajeno. | La carpeta tiene dueño (`.bedrock_suite_owner.json`, lo escribe el primer backup publicado) y la otra instalación usa `<raíz>\Suite-<id8>`. La identidad vive en `data/installation_id.json`: mover la instalación conserva el id y una copia recibe otro. `GET /api/backups/location` añade `shared_name`; `setup_defender_exclusions.ps1` replica la regla. |
| M8 | Verificación de backups con datos comprimidos dañados | `testzip()` solo convierte en resultado un CRC distinto; un deflate dañado lanzaba `zlib.error`: `tools/verify_backups.py` moría con traceback sin marcar el ZIP ni revisar los siguientes, y la GUI respondía 500. | `zip_safety.check_zip_integrity` (fuente única GUI/CLI) lee todas las entradas y clasifica como daño `BadZipFile`, `zlib.error`, `EOFError`, `NotImplementedError` y `RuntimeError`. Un `OSError` (archivo bloqueado) no prueba daño: la CLI lo avisa, no lo marca y sale con 2. |
| M9 | El diálogo de actualizar BDS quedaba en «Actualizando BDS…» | Reabrir el diálogo durante la actualización borraba la marca de «la vi empezar» y el cierre no llegaba nunca (reproducido en el navegador). | `bdsUpdateLogic.crearSeguimientoBds`: cierra con cualquier transición vista de `update_in_progress` de true a false (de esta pestaña u otra), con el estado de una reconexión del WebSocket y con `/api/status` tras el POST. |
| M10 | La lista de backups no se actualizaba | El frontend pedía `/api/backups` solo al conectar y tras pulsar un botón: un backup del wrapper estaba en disco mientras la GUI decía «No se encontraron» y los ya rotados daban 404. | `backups_revision` en el estado público sube en cada cambio posible (fin de un backup en caliente, inicial o de cierre; backup en frío o previo a actualizar; borrado; cambio de carpeta; fin de la sesión del wrapper). El frontend pide la lista al verlo cambiar y al abrir la pestaña. |
| L1 | Fechas anteriores a 1980 | `ZipInfo.from_file` (estricto) lanzaba `ValueError: ZIP does not support timestamps before 1980` y cada backup fallaba. | `auto_backup._zipinfo_for`: `strict_timestamps=False` y, si `localtime` no admite la fecha (antes de 1970 en Windows), 1980-01-01. |
| L2 | Carpeta del mundo ilegible omitida | `os.walk` sin `onerror` saltaba en silencio la carpeta que no podía listar: con `db/` sin permiso de lectura se publicó un ZIP con solo `level.dat` que la restauración aceptaba. | `onerror=_walk_error` en los tres `os.walk` del backup: falla y limpia el `.tmp`. |
| L3 | Junction en los `static_includes` del backup en caliente | `os.walk` no poda su propia raíz: una junction en `behavior_packs` o `resource_packs` del mundo metía contenido externo, solo en los backups en caliente. | Se salta con aviso, como ya hacían el modo tradicional y los packs del servidor. |
| L4 | `NamedMutex` fallaba en abierto | Si `CreateMutexW` no podía abrir el mutex (titular elevado con DACL restrictiva: `ERROR_ACCESS_DENIED`), `acquire()` devolvía True: una GUI sin elevar no veía el wrapper elevado. | Sin handle, `acquire()` devuelve False (ocupado) y `open_error` guarda el código. Solo sin `kernel32` (fuera de Windows) devuelve True. Los tests que simulaban un mutex libre con `handle=None` parchean `acquire` (lockstep). |
| L5 | El proxy y la GUI local | `urllib.request.urlopen` usaba el proxy del entorno o del sistema también para `127.0.0.1`: cada sonda fallaba con `URLError` y toda actualización terminaba en rollback. | `suite_updater._LOCAL`: un opener sin proxy para las llamadas a la GUI. |
| L6 | Reanudar Minecraft tras actualizar la suite | Plazo fijo de 75 s, y una sola respuesta fallida (un 503) lanzaba: un backup inicial largo terminaba en «Minecraft no se reinició». | Plazo de arranque de 180 s que no corre durante `initial_backup_in_progress` (nuevo en `/api/status`), hasta 10 fallos seguidos de la API, fallo inmediato si el wrapper termina y tope `RESUME_MAX_SEC` = `BACKUP_TIMEOUT_MAX_SEC` + 180 (test anti-drift). |
| L7 | Carrera del puerto de la GUI | Se probaba el puerto con un bind y uvicorn lo volvía a enlazar. Si otra aplicación lo tomaba en medio, uvicorn terminaba con `SystemExit(3)` y el reintento del `__main__`, que esperaba `OSError`, no corría. | `_enlazar` devuelve el socket enlazado y uvicorn lo sirve (`server.run(sockets=[sock])`); se quitó el reintento muerto. |
| L8 | Sesiones de jugadores perdidas | Si BDS o el wrapper caían con jugadores dentro, la sesión del historial quedaba abierta y la reconexión la reutilizaba: se perdía una sesión. | Al cerrar la sesión del wrapper (`supervisor.run_wrapper_thread`) se emite la desconexión de quienes seguían conectados. |
| L9 | Cuerpos JSON que no son un objeto | `/api/restore` y `/api/server_properties` con `[1]`, `"x"` o `5` daban 500; `/api/schedule` guardaba `[]` o `0` como `{}` y con `Infinity` o `1e400` daba 500 (`OverflowError`). | 400 en los tres; `schedule_config.validate` captura `OverflowError`. |
| L10 | Restaurar cambiaba el «último backup» | `POST /api/restore` fijaba `last_backup_time` a la hora actual. | Se quitó: restaurar no crea ningún backup. |
| L11 | Acciones de jugador «enviadas» que el servidor rechazó | Un 409 (actualización de la suite en curso), 403 o 500 de `/api/command` llega sin `status` y caía en la rama de éxito. | `commandLogic.resultadoComando`: solo `ok` cuenta como enviado. |
| L12 | «Cómo invitar» con el puerto viejo | Tras cambiar `server-port` y reiniciar, la tarjeta mostraba 19132 mientras la API devolvía 19140, hasta recargar la página. | La conectividad se vuelve a pedir al guardar las propiedades y al arrancar el servidor. |
| L13 | Asistente inicial | Los indicadores dejaban saltar al final sin guardar la configuración ni instalar BDS. «Finalizar» volvía a un paso anterior con un aviso que solo existía en el paso final (no se veía) y «Continuar» habilitado. | `setupLogic.pasoMaximo` limita los indicadores (`Stepper.canSelectStep`), el aviso va encima de los pasos y `volverAPaso` fija el paso junto con el Stepper. |
| L14 | `enable_beta_apis_v2` borraba el respaldo recién creado | La poda recorría todo `worlds/` por fecha y el respaldo nuevo heredaba con `copy2` la fecha vieja del `level.dat`: con tres respaldos recientes de otro mundo, se borraba el que protegía la reescritura. | Poda por archivo que nunca toca el recién creado; `copyfile` en lugar de `copy2`. |
| L15 | `update_items.py` (v1) | Sobrescribía sin respaldo, bajaba los packs de 1.0.6 a 1.0.5 después de la v2 y usaba la ruta fija `worlds/Bedrock level` (`FileNotFoundError`). La v2 sobrescribía `main.js` sin respaldo y fallaba sin la carpeta `scripts/`. | La v1 es un alias de la v2 (se conserva: está en `TOOL_FILES`). La v2 incluye el paso de la 1.0.5, respalda `main.js` solo si cambia, comprueba que exista el addon (exit 1 con mensaje) y conserva 3 respaldos por archivo. |
| L16 | El modo LAN saltaba de puerto en silencio | La regla del firewall y la URL que muestra `iniciar_gui_lan.bat` son del puerto pedido; con ese puerto ocupado la GUI arrancaba en otro, inaccesible desde el móvil. | `GUI_PORT_STRICT=1`, que fija el `.bat`: sin salto, y un error que explica cómo elegir otro puerto. |
| L17 | Variables de los lanzadores sin `setlocal` | `GUI_ALLOW_LAN=1` quedaba vivo en la ventana de cmd: un `iniciar_gui.bat` posterior en la misma ventana abría la GUI a la LAN. | `setlocal` en `iniciar_gui.bat`, `iniciar_gui_lan.bat` e `iniciar_servidor.bat`; test sobre todo `.bat` que fija variables. |
| L18 | `iniciar_gui.bat` (runtime del ZIP) cerraba la ventana con el error | Una GUI que salía con error cerraba la ventana al instante. | `:gui_fallida` con pausa; la salida limpia (relevo de una actualización) sigue cerrándola sola. |
| L19 | Texto roto en el script de Defender | `setup_defender_exclusions.ps1` estaba en UTF-8 sin BOM y Windows PowerShell 5.1 lo leía como ANSI (`aÃ±ade`). | Guardado con BOM; test sobre todo `.ps1` con caracteres no ASCII y análisis con el parser de PowerShell 5.1. |
| L20 | «[OK]» sin exclusiones | Con Defender inactivo el script hacía `exit` (código 0) y `configurar_antivirus.bat` anunciaba las exclusiones configuradas. | `exit 2` y un aviso propio en el `.bat`. |
| L21 | Aviso de tipo cruzado oculto por el filtro | Filtrando la pestaña Addons por tipo, `WORLD_REF_KIND_MISMATCH` desaparecía (su `pack` es del otro tipo) mientras su referencia `kind_mismatch` seguía a la vista. | Un diagnóstico de referencia (`scope` = tipo) se conserva; el mismo cambio en el espejo `addonsLogic.js`, con un fixture compartido generado con el analizador. |

## Decisiones

- **M2**: archivos de configuración como *conffiles*. Lo editado nunca se pisa
  y la versión de fábrica nueva queda al lado para comparar. La primera
  actualización tras este cambio no tiene registro y decide la fecha; un
  archivo que no se puede leer se conserva. Tras revertir, la huella de fábrica
  de la versión restaurada no se conoce y el registro se borra.
- **M7**: si dos instalaciones ya comparten la carpeta, se la queda la primera
  que publica un backup y la otra pasa a `<servidor>-<id8>`. Sus backups
  anteriores no se mueven: quedan en la carpeta compartida, a cargo de la
  rotación de la dueña. Se reclama después de publicar, no antes: un backup
  que falla no reclama nada. Sin poder escribir `data/` (solo lectura), el
  sufijo es un hash de la ruta.
- **L16**: solo el modo LAN es estricto. En local se sigue saltando al
  siguiente puerto libre (otra aplicación en el 8000 es habitual) y la URL que
  se abre es la real.
- **L4**: fallar cerrado. El coste: un nombre de mutex tomado por otro tipo de
  objeto también cuenta como ocupado.
- **L15**: `update_items.py` queda como alias y no se borra: está en
  `suite_release.TOOL_FILES` y quitarlo cambiaría la lista que valida cada
  actualización.
- **Auxiliar de la suite**: las correcciones que viven en el auxiliar (M5 lado
  auxiliar, M6 lado auxiliar, L5, L6) solo rigen en las actualizaciones que
  parten de la versión que las incluye. Lo que vive en la GUI (`_archive_job`)
  y en `Recuperar_suite.bat` cubre M5 y M6 en cuanto esa versión está
  instalada. Los dos casos que la 2.2.0 publicada no resuelve tienen salida
  documentada en
  [ACTUALIZACIONES_SUITE.md](ACTUALIZACIONES_SUITE.md#qué-corrección-rige-en-cada-actualización).

## Incidente durante la validación

Tras la primera corrida completa aparecieron archivos nuevos en el `data/` de
TESTTEST. Un vigilante ad hoc (plugin de pytest, fuera del repo, que compara
los archivos de datos de la instalación real antes y después de cada test)
encontró tres tests responsables:

1. `test_backup_fixes.py::test_worker_lectura_snapshot_fallida_programa_reintento`
   ejecuta el worker real en otro proceso, con el mundo real, y los guards de
   `tests/conftest.py` no llegan a ese proceso. En la primera versión de M7 el
   reclamo de la carpeta iba antes de empaquetar: ese backup, que el test hace
   fallar a propósito, creó `data/installation_id.json` y el dueño de la carpeta
   de backups real. Ahora se reclama solo tras publicar el ZIP
   (`test_m7_un_backup_fallido_no_reclama_la_carpeta`).
2. `test_setup_initial.py::test_download_and_install_bds_exito`, anterior a esta
   revisión, parcheaba `config.BASE_DIR` pero no `bds_update.PREVIOUS_VERSION_DIR`,
   que se calcula al importar. Cada corrida de la suite movía el resguardo del
   test a `data/bds_previous` de TESTTEST y apartaba la versión anterior que
   hubiera. El test parchea ahora la constante, y un guard de sesión de
   `conftest.py` hace fallar a cualquier test que intente guardar ahí.
3. `test_ronda_2026-09-25.py` (anti-spoofing del marcador «BDS stopped») conecta
   un jugador falso `BDS stopped:12345` sin aislar `supervisor.KNOWN_PLAYERS_PATH`:
   desde el 25 de septiembre ese jugador estaba en el `data/known_players.json`
   de TESTTEST (y desde el 15 de octubre en el del checkout público). L8 añadió
   una escritura más (la salida al cerrar la sesión). Hallado al validar el
   repositorio público, con el vigilante ampliado a todo `data/`. Un fixture de
   `conftest.py` aísla ahora el registro en todos los tests.

Los archivos creados se retiraron de TESTTEST y quedaron en un resguardo fuera
del repo. `data/bds_previous` solo contenía la metadata del test: si hubo una
versión anterior real, ya se había perdido en corridas anteriores, y
`known_players.json` solo tenía el jugador falso. Producción no ejecuta tests y
no se vio afectada.

## Validación

- `tests/test_revision_2026-10-21.py` reúne 79 regresiones. Ejecutan el código
  real sobre instalaciones en `tmp_path`: subprocesos con la tubería cerrada
  (M4), un proceso que retiene `gui.log` (M5), los `.bat` en carpetas temporales
  con un runtime auxiliar enlazado (M6, L18, L20), `icacls` para la carpeta
  ilegible (L2), junctions (L3), un titular del mutex con DACL restrictiva (L4),
  un servidor HTTP local con proxy en el entorno (L5), un reloj virtual (L6),
  uvicorn con el socket enlazado (L7) y el parser de Windows PowerShell 5.1
  (L19). Contra el código de `HEAD` fallan 74; las 5 restantes son controles que
  fijan lo que debía conservarse (salida limpia sin pausa, `[OK]` con código 0,
  el proceso sin protección que muere, el diario pendiente que se sigue
  validando y el fixture fiel al analizador).
- Suite completa sin e2e: 1259 aprobadas (2 e2e excluidas). El vigilante (todo
  `data/`, `worlds/` y `config/`, los archivos de la raíz y la carpeta de
  backups real) no registró ninguna escritura de los tests. `ruff check .`:
  sin avisos.
- Frontend: `npm run lint` sin avisos y `npm test` con 125 tests (17 nuevos:
  `bds-update`, `players-command`, `setup-wizard` y el caso de tipo cruzado en
  `addons`). `npm run build` regeneró `dist/`. El aviso de Vite por el bundle de
  más de 500 kB ya existía (500,9 kB antes, 501,5 kB ahora).
- GUI real en el navegador, sobre instalaciones temporales con el código y el
  `dist/` nuevos (solo BDS, la descarga y la IP pública simulados): la lista de
  backups se actualiza sola al subir `backups_revision` y tras el backup
  preventivo de una actualización (M10); cerrar y reabrir el diálogo durante una
  actualización de BDS muestra «Actualizando BDS…» y se cierra solo al terminar
  (M9); con `/api/command` en 409, «Hacer operador» muestra el error (L11); la
  tarjeta «Cómo invitar» pasa de 19140 a 19141 al guardar el puerto y a 19142 al
  arrancar el servidor (L12); el asistente no deja saltar pasos y el rechazo de
  «Finalizar» se ve encima de los pasos (L13); el filtro «Recursos» de Addons
  muestra `WORLD_REF_KIND_MISMATCH` (L21).
- Entrypoint real (`python server_gui_server.py`, sin el arnés de QA): con el
  puerto pedido ocupado salta al siguiente, avisa y sirve `/api/status`; con
  `GUI_PORT_STRICT=1` sale con código 1 y el mensaje que explica cómo elegir
  otro puerto, sin escuchar en ninguno (L7, L16).
- CLI real (`tools/verify_backups.py`): en una carpeta con corchetes y «ñ», un
  deflate dañado se marca `_CORRUPTO`, se revisa el siguiente y la salida es 1;
  un ZIP abierto sin compartir por otro proceso se avisa, no se marca y la
  salida es 2.
