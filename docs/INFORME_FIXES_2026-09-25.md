# INFORME — Ronda de fixes 2026-09-25 (auditoría de practicidad y seguridad de mundos/archivos)

Contexto: revisión completa del repo enfocada en **practicidad y seguridad de los mundos, los archivos y los backups** (seguridad de red tratada solo donde impacta datos/comandos). Todos los hallazgos Alto/Medio y casi todos los Bajos de la revisión quedaron corregidos; los items Info de "pulido" con riesgo de romper contratos se dejaron documentados a propósito (ver §6).

## 1. Backups y mundos (auto_backup.py, wrapper_backup.py, wrapper_state.py, server_wrapper.py)

- **H1 — Timeouts escalados con el tamaño del mundo** (hallazgo Alto): los 120 s de compresión y 240 s del backup de cierre estaban calibrados para mundos pequeños; un mundo de varios GB nunca completaba el backup caliente (el worker se mataba en cada ciclo) y el backup de cierre (hilo daemon) se perdía al salir el proceso. Ahora `wrapper_state.scaled_backup_timeout_sec(total_bytes, base)` escala +120 s por GB sin comprimir (tope 3600 s), con los valores históricos como PISO. El wait del worker usa la suma del snapshot; el join del backup de cierre, `auto_backup.estimate_backup_total_bytes()`. *(Seguimiento 2026-10-19: esta ronda dejó fijos el join de cierre del worker (135 s) y la espera de fase 2 de la GUI (450 s); corregido en `docs/INFORME_TIMEOUTS_CIERRE_2026-10-19.md`.)*
- **H2 — `recover_interrupted_restores` solo toca el formato exacto de debris**: antes borraba/renombraba por subcadena (`.restore_staging_` / `.bak_`) y un mundo legítimo cuyo nombre contenía esos textos se eliminaba silenciosamente al arrancar. Ahora `_RE_STAGING_DEBRIS`/`_RE_BAK_DEBRIS` exigen el formato que genera `restore_core` (`<base>.restore_staging_<8hex>`, `<base>.bak_<8hex>`).
- **H3 — `tools/verify_backups.py` exige `level.dat`**: antes un ZIP sin mundo pasaba como `[OK]` aunque el restore lo rechazaría; ahora se marca con `_CORRUPTO` (mismo marcador que GUI/rotación).
- **H4 — `fsync` antes de publicar/restaurar**: el ZIP se persiste en disco antes del `os.replace` final (best-effort) y el staging del restore se vuelca antes del swap: un apagón ya no deja "backups válidos" o mundos instalados con datos sin volcar.
- **H5 — `_is_safe_zip_entry` endurecido**: rechaza `:` en cualquier segmento (ADS de NTFS como `db/foo.ldb:stream`), nombres de dispositivo Windows (`NUL`, `CON`, `COM1-9`, `LPT1-9`) y punto/espacio final (alias NTFS). La cadena vacía se acepta por compatibilidad (`test_security_hardening.py` lo fija).
- **H6 — GUI y CLI recuperan residuos antes de restaurar**: `auto_backup.restore_backup` y `restore_backup.list_and_restore` llaman `recover_interrupted_restores()` antes de tocar nada (antes solo corría al arrancar).
- **H7 — `create_backup` exige `level.dat` en TODOS los modos** (también el tradicional): se dejaban de publicar backups irrestaurables como válidos.
- **H8 — Empaquetado por chunks** (`auto_backup._write_file_chunked`): la cancelación cooperativa ahora aborta incluso con archivos de GBs (antes `zipf.write` comprimía el archivo entero sin poder interrumpirse). El test de disco lleno (`test_fault_injection.py`) se actualizó al nuevo punto de escritura (`ZipFile.open`).
- **H9 — Verificación post-swap antes de descartar el `.bak`**: si el mundo instalado no llega con `level.dat`, rollback al mundo previo y error (antes el `.bak` se borraba sin comprobar nada).

## 2. GUI backend (security.py, supervisor.py, routers, services)

- **Alto — CSRF entre dispositivos de la LAN**: en modo `GUI_ALLOW_LAN=1`, S3 aceptaba el Origin de cualquier IP privada; una página servida por otro dispositivo de la LAN podía enviar comandos (por POST o WebSocket) desde el navegador del administrador. Ahora `_is_allowed_origin(..., expected_host=...)` exige que el host del Origin coincida con el Host del request (la IP de la propia GUI).
- **Medio — DNS-rebinding**: sin validar el header `Host`, una página re-bindeada leía los GET de `/api/*` (status, backups, logs, XUIDs). Nuevo guard S1b (`security._ensure_valid_host_header`) en el middleware: el hostname debe ser loopback/localhost, IP privada con `GUI_ALLOW_LAN=1`, o estar en `GUI_ALLOWED_HOSTS` (el TestClient se habilita vía fixture de sesión en `tests/conftest.py`).
- **Bajo — Marcador `"BDS stopped"` anclado** (`supervisor._RE_STOP_MARKER`): con substring libre, un gamertag "BDS stopped" en una línea `Player connected: ...` seteaba `server_stopped_event`.
- **Bajo — Detección de `stop` por `\r\n`**: `str.splitlines()` también parte por `\v \f \x1c-\x1e \x85 \u2028 \u2029`; un `"x\x0bstop"` marcaba `stop_requested` con el wrapper vivo e inhibía al watchdog. Ahora se parte igual que el wrapper (`replace("\r", "\n").split("\n")`), en `routers/system.py` y `routers/websocket.py`.
- **Bajo — Watchdog con tope**: tras `WATCHDOG_MAX_CRASH_RESTARTS` (5) re-arranques fallidos seguidos deja de reintentar con aviso único ("intervención manual"); el contador se reinicia con uptime estable.
- **Bajo — Restart con guard de reentrada**: `POST /api/action/restart` responde `busy` si ya hay un restart (o un update) en vuelo (`manager.restart_in_progress`); antes cada clic apilaba un hilo de `restart_wrapper`.
- **Info corregido — Locks de sesión**: los writes de apertura de sesión del hilo del wrapper (`installed_version`, `events_alive`, `is_running`, `start_time`, `wrapper_process`) van bajo `manager.lock`, igual que el cierre.
- **Info corregido — Nombres de backup**: `zip_safety.is_safe_backup_name` (basename puro `.zip`, sin `..`/alias NTFS/caracteres de control) unifica la validación de los 4 endpoints de `routers/backups.py` y `auto_backup.restore_backup`.
- **Bajo — IA robusta**: una respuesta malformada de LM Studio (`tool_calls` con null/cadenas, `arguments` no-dict) devuelve el envelope de error en vez de un 500 con traceback.

## 3. Tools y scripts de arranque

- `tools/update_items_v2.py`: respaldo previo (`.respaldo_<timestamp>`) de cada JSON reescrito, validación de estructura con mensajes claros (sin tracebacks), mundo resuelto por `level-name` vía `server_properties.read_value` (antes `worlds/Bedrock level` hardcodeado) y salida con código 0/1.
- `tools/enable_beta_apis_v2.py`: validación de la cabecera del `level.dat` (`8+length <= len(data)`, `struct.error` capturado), `PermissionError` con mensaje accionable, limpieza del `.tmp_` en `finally` y poda de `.respaldo_*` dejando los 3 más recientes (entraban en cada backup).
- `tools/bds_first_run.py`: mensaje claro ante fallo de descarga (antes el `repr` crudo de la excepción).
- `wrapper_schedule.py`: limpieza del `.tmp_` huérfano si `json.dump` falla.
- `iniciar_*.bat`: **refresh del `.venv` por huella SHA256 de `requirements.txt`** (`.venv\requirements.sha`; antes solo chequeaban imports y un venv viejo nunca se actualizaba). `iniciar_servidor.bat` fija `WRAPPER_LANG=es` si el usuario no lo definió y su banner ya no finge valores de `server.properties`. `iniciar_gui_lan.bat` recrea la regla de firewall con el `GUI_PORT` actual.
- `configurar_firewall.bat`: solo UDP 19132/19133 (BDS no usa TCP) con `profile=private`, recreando la regla homónima (antes la comprobación no miraba puertos y abría también red pública).
- `configurar_antivirus.bat` + `tools/setup_defender_exclusions.ps1`: el exit code del proceso elevado se propaga (antes el padre salía `exit 0` siempre).

## 4. Frontend (gui_frontend/)

- Código muerto eliminado (verificado con grep antes de borrar): `reactbits/LiquidEther.jsx`+`.css`, `Silk.jsx`, `Aurora.jsx`, `Particles.jsx`, `BorderGlow.jsx` y las dependencias `three`, `@types/three`, `clsx`, `tailwind-merge` (nadie los importaba).
- Dependencias bien clasificadas (`tailwindcss`, `@tailwindcss/vite` a `devDependencies`).
- Errores de fetch visibles en la consola de la GUI (antes solo `console.error` y datos vacíos sin aviso).
- oxlint estricto (`eqeqeq`, `no-unused-vars`, `no-undef`) con las3 violaciones corregidas.
- i18n: sugerencias del asistente IA traducidas (label y texto), `t()` avisa en dev de claves ausentes y `useI18n()` falla explícitamente fuera del provider.
- `SetupWizard`: matchers de instalación centralizados + fallback de sondeo de `GET /api/setup_status` cada 5 s y estado "sigue en progreso" a los 90 s con reintento manual (antes se quedaba en "Instalando…" para siempre si el WS no conectaba).
- **Tests de frontend** (nuevo): Vitest con `gui_frontend/tests/` (simetría ES/EN del diccionario i18n + canary de seguridad sin `innerHTML`/`dangerouslySetInnerHTML`/`eval`). CI pasa a correr lint + test + build.

## 5. Tests añadidos/actualizados (lockstep)

- Nuevo `tests/test_ronda_2026-09-25.py`: timeouts escalados (piso/escala/tope + uso en el worker), estimación de bytes, fsync antes de publicar, `level.dat` obligatorio en modo tradicional, rollback post-swap, recover previo en GUI y CLI, hardening de nombres de backup, marcador anclado vs gamertag, CSRF same-host, Host anti-rebinding, `stop` con separadores de control, tope del watchdog, tool_calls malformados y guard de reentrada del restart.
- Actualizados en lockstep: `test_recover_interrupted_restores.py` (nonces hex8 + blindaje de nombres legítimos), `test_zip_safety_packs.py` (ADS/dispositivos/aliases), `test_gui_server_properties.py` (`ref_safe` y `safe_name` al contrato nuevo), `test_verify_backups_tool.py` (ZIP sin `level.dat`), `test_fault_injection.py` (ENOSPC sobre `ZipFile.open`), `test_review_hallazgos.py` (restart doble: "busy" en el segundo clic, blindaje de un solo wrapper intacto), `test_console_lang_pbt.py` (`L_PY_FILES` con `tools/*_v2.py`).
- `tests/conftest.py`: fixture de sesión que habilita `GUI_ALLOWED_HOSTS=testserver` para el TestClient (el guard S1b rechazaría su `Host`).

## 6. Deliberadamente NO tocados (riesgo > beneficio)

- Envolvente de error inconsistente de la API (`{"detail"}` vs `{"status","message"}`): unificar rompería `web/app.js` y clientes existentes.
- `set_lang` del WS es global (un cliente cambia el idioma de todos): cambiarlo a por-conexión altera el contrato del frontend.
- `delete` de backups sin papelera/confirmación server-side: UX elegida para una GUI local.
- Descarga de BDS sin hash/firma: Mojang no publica hashes (riesgo aceptado y documentado; staging+rollback previos mitigan).
- Exclusiones de Defender sin script de undo y sin escaneo de `behavior_packs` (JS de scripting): alcance documentado en README.
- Riesgo residual del dispatch del `save query` por "5 s de silencio": inherente al protocolo (sin marcador de fin de listado); no se reintroduce cobertura de `db/` por contrato.

## 7. Verificación

- `python -m pytest tests -m "not e2e"` → verde (incluye los ~780 tests + los nuevos de la ronda).
- `python -m ruff check .` → limpio.
- `npm run lint` / `npm test` / `npm run build` en `gui_frontend/` → verde (oxlint 0 errores, 8 tests vitest, dist regenerado).
- README y AGENTS.md actualizados con los contratos nuevos (escalado de timeouts, `level.dat` obligatorio, S1b/S3 same-host, `GUI_ALLOWED_HOSTS`, formato exacto de debris, refresh del venv, i18n de tools, tests de frontend).
