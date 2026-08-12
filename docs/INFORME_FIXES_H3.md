# INFORME FIXES H3 — Backup colgado, backups por servidor, packs y restore CLI

Fecha: 2026-08-12
Alcance: hallazgos de la revision de seguridad/robustez del 2026-08-12, verificados
contra el codigo real y corregidos en esta iteracion.

Estado de verificacion: suite completa verde **122 passed, 1 skipped, 0 failed**
(incluye los 2 tests e2e con BDS real levantado en un workspace aislado).

---

## Resumen

| # | Hallazgo | Severidad | Estado |
|---|----------|-----------|--------|
| 1 | Actualizador BDS "borra packs" | Baja (sintoma no existe) | Sin cambios — ver nota |
| 2 | `backup_in_progress` de la GUI queda en True para siempre tras un backup fallido | Media | CORREGIDO |
| 3 | Carpeta de backups compartida entre servidores (restore cruzado pisa mundos) | Alta | CORREGIDO |
| 4 | `_pack_dest` clasifica un archivo suelto del pack dir como "mundo" | Baja | CORREGIDO |
| 5 | `lines_waited_for_list` nunca se reinicia tras parseo exitoso | Cosmetico | CORREGIDO |
| 6 | `restore_backup.py` (CLI) no verifica si el servidor esta corriendo | Media | CORREGIDO |

---

## Fix #2 — flag de backup colgado en la GUI

**Que**: `manager.backup_in_progress` (server_gui_server.py) se ponia en `True`
al ver la linea del wrapper `[Worker] Iniciando compresion de archivos en proceso
separado...`, pero solo volvia a `False` con `"Compresion exitosa"` o
`"Backup completado"`. Los caminos de fallo del wrapper imprimen otras cadenas
(`Timeout de compresion`, `Reanudando escritura tras fallo de backup`,
`Excepcion en worker de backup`, ruta del watchdog con `return` temprano), que
no matcheaban. Resultado: el boton de backup en frio quedaba bloqueado con
"Ya hay un backup en curso" hasta reiniciar la GUI.

**Por que**: la GUI no tiene estado compartido con el wrapper; se entera por
lineas de log. Matchear cada cadena de fallo es fragil: cualquier camino sin
cubrir (p. ej. el watchdog) vuelve a colgar el flag.

**Como**: se establecio un contrato explicito de un marcador de fin:
- `server_wrapper.py`: `execute_backup_worker` ahora imprime
  `[Worker] Backup finalizado` en un `finally`, que cubre TODOS los caminos
  (exito, fallo, timeout, watchdog, excepcion), incluidos los `return` tempranos.
- `server_gui_server.py`: `run_wrapper_thread` resetea `backup_in_progress`
  con `elif "Backup finalizado" in line_str` (ademas de las cadenas de exito,
  que siguen actualizando `last_backup_time`).

**¿Es recomendable modificarlo?**: No. El contrato por marcador es el punto
unico que garantiza el reset. Si en el futuro se reestructura
`execute_backup_worker`, el `print("[Worker] Backup finalizado")` DEBE seguir
en un `finally` (no al final del `try`): los `return` tempranos del watchdog y
del timeout lo esquivarian. Hay tests de contrato que fijan esta condicion
(`test_wrapper_marca_fin_de_ciclo_en_finally`, `test_gui_resetea_flag_con_backup_finalizado`).

---

## Fix #3 — backups por servidor (aislamiento entre instalaciones)

**Que**: `auto_backup.BACKUP_DIR` era `BASE_DIR\..\..\Backups_Minecraft\auto_backups`
compartida por TODOS los servidores bajo el mismo padre (verificado en disco:
zips de 7 servidores mezclados). El nombre del zip no llevaba el nombre del
servidor (`auto_backup_{trigger}_{timestamp}_{nonce}.zip`) y las entradas del
zip son relativas al mundo, asi que un zip no es atribuible a un servidor ni
siquiera inspeccionandolo. Restaurar desde la GUI del servidor A un backup de B
sobrescribia el mundo de A (mismo `level-name` por defecto, "Bedrock level").

**Por que**: riesgo real de perdida de datos en un setup multi-servidor.

**Como**:
- `auto_backup.py`: nueva constante `SERVER_NAME = basename(BASE_DIR)` y
  `_resolve_backup_dir(base_dir)`; `BACKUP_DIR` ahora resuelve a
  `Backups_Minecraft\auto_backups\<servidor>`.
- Nombre del zip: `auto_backup_<servidor>_<trigger>_<timestamp>_<nonce>.zip`
  (la rotacion usa `mtime`, no parsea el nombre: seguro).
- `restore_backup.py`: mismo `BACKUP_DIR` por servidor.
- La GUI no necesito cambios (usa `auto_backup.BACKUP_DIR`).

**¿Es recomendable modificarlo?**: No deshacerlo sin migrar. Notas:
- Los zips viejos de la carpeta compartida NO son atribuibles a un servidor:
  quedan donde estan (o se mueven a `auto_backups\legacy\` para inspeccion
  manual).
- Los demas servidores del mismo padre siguen escribiendo en la carpeta
  compartida hasta que reciban este cambio: hay que propagarlo (ver
  "Propagacion" al final).
- Cambiar el esquema de carpetas es reversible (una linea por archivo), pero
  cada reversa deja los backups en otra ubicacion: decidir el esquema una sola
  vez.

---

## Fix #4 — `_pack_dest` y archivos sueltos en la raiz del pack dir

**Que**: `server_resource_packs/foo.txt` (archivo en la raiz del pack dir, sin
subcarpeta) no cumplia `len(parts) >= 2` y se clasificaba como entrada del
mundo: se extraia a `WORLD_DIR/server_resource_packs/foo.txt` en vez de
`BASE_DIR/resource_packs/foo.txt`. El defecto estaba duplicado en las 2 copias
de `_pack_dest` (auto_backup.py y restore_backup.py).

**Por que**: caso poco realista (los packs reales viven en subcarpetas), pero
la clasificacion ambigua podia devolver archivos al lugar equivocado.

**Como**: `_pack_dest` ahora devuelve `(kind, "", rest)` para un archivo suelto
en la raiz del prefijo; el restore lo lleva a `BASE_DIR/<kind>` (el
`os.path.join` con `folder=""` ya resolvia correctamente). Aplicado a las 2
copias.

**¿Es recomendable modificarlo?**: No por ahora. El riesgo pendiente es la
duplicacion: si se toca una copia y no la otra, hay drift. A medio plazo,
centralizar `_is_safe_zip_entry`/`_pack_dest` en `auto_backup.py` e importarlos
en `restore_backup.py` elimina el problema.

---

## Fix #5 — `lines_waited_for_list` sin reset tras parseo exitoso

**Que**: el contador de lineas esperadas de la lista de jugadores se reiniciaba
solo en la rama de lista vacia; un parseo exitoso lo dejaba con el valor viejo.

**Por que**: sin efecto practico (la rama que lo usa exige
`expecting_list_names == True`, que el parseo exitoso apaga), pero inconsistente.

**Como**: se resetea en los dos parseos exitosos (lista con nombres y
continuacion parseada).

**¿Es recomendable modificarlo?**: Puede revertirse sin riesgo (es higiene).
Los tests de contrato no dependen de el funcionalmente.

---

## Fix #6 — restore CLI sin guard de servidor corriendo

**Que**: `restore_backup.py` (menu CLI de `02_restaurar_backup.bat`) no
verificaba si BDS estaba vivo: dependia de que `os.rename(WORLD_DIR, ...)`
fallara en Windows (permisos de archivos abiertos), con un mensaje confuso.

**Por que**: restaurar con el servidor vivo pisa un mundo en uso; la GUI ya lo
protegia con 409 + re-chequeo atomico, el CLI no.

**Como**: nuevo `_server_is_running()` en restore_backup.py: detecta
`bedrock_server.exe` via psutil y aborta el menu con mensaje claro. El import
de psutil es opcional (`try/except ImportError`): sin psutil el guard se omite
y sigue protegiendo el `os.rename` como red de seguridad.

**¿Es recomendable modificarlo?**: No. Si se cambia, mantener el fail-open:
sin psutil el CLI debe seguir funcionando (los .bat pueden correr en entornos
sin requirements instalados).

---

## Fix #1 — actualizador BDS y packs (SIN cambios, conclusion de revision)

Se verifico que `_apply_staged_update` (server_gui_server.py) solo mueve a
`bds_update_prev_*` los archivos CUYA RUTA EXISTE en el zip nuevo de Mojang.
Los packs de terceros en carpetas propias (ThatMob's Verity, Revolution Vibrant
Visuals, etc.) no estan en el zip oficial: sobreviven intactos. `preserve_dirs`
no incluye `resource_packs/`/`behavior_packs/`, pero eso solo importa para
rutas del zip.

Riesgo residual aceptado: modificaciones hechas DENTRO de carpetas vanilla
(colisionantes con el zip) se pierden silenciosamente. Mitigacion existente: el
backup preventivo `pre_update_backup` ya incluye los packs.

**Recomendacion**: no agregar `resource_packs/`/`behavior_packs/` a
`preserve_dirs` (impediria aplicar los packs vanilla nuevos de cada version).
Regla de uso: no editar packs dentro de carpetas vanilla.

---

## Extra — test PBT flaky (`test_resolve_valid_paths`)

Pre-existente, detectado al correr la suite: el generador de Hypothesis podia
devolver `NUL` (nombre reservado de Windows). `os.path.abspath(".../NUL")`
normaliza a la ruta de dispositivo relativa `\\.\NUL` y `os.path.commonpath`
revienta con "Can't mix absolute and relative paths". El fallback de redraw del
composite no filtraba nombres reservados ni `..`. Se agrego `_safe_fallback`
filtrado (cambio solo de test; el codigo de `_resolve_snapshot_path` no se
toco).

---

## Verificacion

- 122 passed, 1 skipped, 0 failed (suite completa, tests unitarios + PBT +
  fault injection + e2e con BDS real y API real de Mojang).
- E2E real: GUI + wrapper + BDS + worker + backup caliente (mundo TestWorld
  aislado, `server.properties` restaurado, zips de prueba eliminados, sin
  procesos colgados).
- Los 7 tests nuevos + 2 actualizados fijan los contratos:
  - marcador `Backup finalizado` en finally del wrapper y reset en la GUI;
  - `BACKUP_DIR` por servidor y nombre del zip con servidor;
  - `_pack_dest` con archivo suelto como pack (2 copias);
  - reset de `lines_waited_for_list`;
  - `_server_is_running` del CLI.

## Propagacion

Este trabajo se desarrollo en `TESTTEST` (aislado). Para que el resto de
instalaciones tome los fixes, copiar SOLO estos archivos (nunca
`server.properties`, `worlds/`, `allowlist.json`, etc., que son propios de cada
servidor):

- `server_wrapper.py`
- `server_gui_server.py`
- `auto_backup.py`
- `restore_backup.py`
- `tests/test_review_hallazgos.py`
- `tests/test_packs_in_backup.py`
- `tests/test_restore_backup.py`
- `tests/test_backup_fixes.py`
- `tests/test_pbt_properties.py`
- `docs/INFORME_FIXES_H3.md`

Efecto esperado en cada servidor: sus backups nuevos pasan a
`Backups_Minecraft\auto_backups\<nombre>` y el nombre del zip lo identifica.
Los zips historicos quedan en la carpeta compartida.
