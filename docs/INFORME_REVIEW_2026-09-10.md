# Informe de revisión — 2026-09-10

**Alcance:** suite de tests, documentación y empaquetado del repo dev
(`Servidores_Minecraft\TESTTEST`). El código productivo no se modificó en esta
ronda: todos los hallazgos se resolvieron en tests, `.gitignore`, README y CI,
siguiendo la regla de AGENTS.md ("no tocar reglas de concurrencia sin tests" y
"los cambios de producto necesitan test RED antes").

**Baseline:** commit `38af903` + tag `pre-ronda-2026-09-10`.
**Estado final:** 427 passed, 2 deselected (e2e) — 10/10 corridas consecutivas
en verde.

---

## F1 — Flakiness de la suite y wrappers reales lanzados por los tests

**Severidad:** alta (contaminaba la instalación real y hacía la suite no
determinista).

**Síntoma:** 3 de 4 corridas completas fallaban 1 test distinto
(`test_start_limpia_stop_requested`, `test_watchdog_ciclo_crash_completo_sin_binario`,
4 tests de `test_backup_fixes.py`). Aislados pasaban siempre.

**Causa raíz (con evidencia):** el hilo daemon `gui-watchdog` arranca con el
lifespan del primer `TestClient` y **sobrevive a los monkeypatches de cada
test**. En `test_schedule_watchdog.py::test_pbt_gui_save_wrapper_load_coherentes`
(el PBT asigna `sc.SCHEDULE_PATH` con asignación directa, no monkeypatch) el
hilo leyó un config con `auto_restart_on_crash=true`, vio
`is_running=False` + `stop_requested=False` y llamó a `start_wrapper()` →
`_spawn_wrapper_process()` **real**. Un spy temporal de `pytest` (plugin fuera
del repo, ya retirado) capturó el stack exacto:

```
REAL_SPAWN test=tests/test_schedule_watchdog.py::test_pbt_gui_save_wrapper_load_coherentes
  gui_backend/services/watchdog.py:166 in _tick_crash_restart -> start_wrapper()
  gui_backend/services/lifecycle.py:40 in _launch_wrapper -> supervisor._spawn_wrapper_process()
```

Consecuencias observadas: dos wrappers reales (pids 9980/376) con backup
inicial real de 85 MB cada uno (`Backups_Minecraft/auto_backups/TESTTEST/`),
BDS real, `BDS_Wrapper_<hash>` retenido (409 espurios en `/api/action/start`
y `KeyError: 'status'` en tests de endpoints) y `BDS_Backup_<hash>` ocupado
(`"A backup is already running"` en `test_worker_lectura_...`). El evento
`data/schedule_state_gui.json` quedó con `last_daily_restart_date=2026-09-10`
escrito por la rama de restart diario del watchdog.

**Fix (test-only):**
- `tests/conftest.py`: fixture autouse de sesión que desactiva
  `watchdog.start` durante toda la suite (los tests ejercitan `_watchdog_tick`
  y helpers directamente; el loop de fondo solo se necesita en producción).
- `tests/test_schedule_watchdog.py::test_start_limpia_stop_requested`: patch
  de `supervisor.run_wrapper_thread` a no-op. El fake con stdout EOF inmediato
  cerraba la sesión antes de las aserciones (carrera por el GIL).
- `tests/test_gui_server_properties.py::test_ensure_local_no_other_exceptions`:
  el oráculo PBT olvidaba `"localhost"`, que `security.py:36` acepta como
  loopback; el ejemplo generado por Hypothesis destapó el falso fallo.
- `tests/test_pbt_properties.py::test_resolve_valid_paths`: el generador
  `valid_world_relative_path()` podía producir una primera parte `WORLDS`
  (forma server-relativa legacy) que el producto rechaza con razón: un archivo
  suelto llamado `worlds` en la raíz quedaría fuera del mundo. Se filtra en el
  generador y en el fallback (segundo falso fallo destapado por la base de
  ejemplos de Hypothesis, no relacionado con hilos). Commit `2018a79`.
- Guard anti-regresión:
  `test_review_hallazgos.py::test_watchdog_de_fondo_neutralizado_en_la_suite`
  falla si se elimina el fixture de conftest.

**Verificación:** 10 corridas completas consecutivas verdes tras el fix final
(y otras 10 verdes en la verificación intermedia), 0 archivos `be_*.ndjson`
nuevos, 0 backups nuevos, 0 wrappers residuales (medido antes/después con
conteos y `Get-CimInstance Win32_Process`).

**Commit:** `6681385`.

**Residual (no borrado):** los 2 backups reales de 85 MB del 2026-09-10
02:08 en `Backups_Minecraft/auto_backups/TESTTEST/` quedan como backups
válidos del mundo; los `be_*.ndjson` de test sí se eliminaron (`7955a09`).
`data/schedule_state_gui.json` quedó con la fecha de restart diario del día;
el config real tiene `daily_restart_time=null`, así que no tiene efecto.

---

## F2 — 24 tests se saltaban en silencio (httpx)

**Síntoma:** `pytest -m "not e2e"` daba 402 passed / 24 skipped con el comando
documentado (`pip install hypothesis pytest`), incluidos guards HTTP/WS,
historial, jugadores y rollback.

**Causa:** `TestClient` requiere `httpx` (dependencia no incluida en
`requirements.txt`) y los tests usan `importorskip("httpx")`.

**Fix:** `requirements-dev.txt` (`-r requirements.txt` + pytest + hypothesis +
httpx). README (ES/EN) y AGENTS actualizados: `pip install -r
requirements-dev.txt`; nota de que `httpx` es obligatorio para no volver a un
verde decorativo. El archivo es dev-only: no se copia a producción.

**Verificación:** los 6 archivos afectados: 156 passed, 0 skipped. Suite total:
426→427 passed, 0 skips por httpx.

**Commit:** `2c76591`.

---

## F3 — Handles de archivo en tests de introspección

**Síntoma:** 43 `open(...).read()` sin context manager en 7 archivos de tests
(CI en CPython los cierra al final de la expresión, pero era deuda de higiene).

**Fix:** transformación mecánica verificada por script a
`Path(...).read_text()/read_bytes()` (misma semántica). Aserciones canario
intactas. **Verificación:** 427 passed.

**Commit:** `f25a476`.

---

## F4 — `.bat` fantasma en el README

**Síntoma:** `01_hacer_backup.bat`, `02_restaurar_backup.bat`,
`03_regresar_al_anterior.bat` figuraban en la tabla de archivos; en realidad
solo existen en `backups/` (gitignoreado) y el repo público no los tiene.

**Fix (docs-only, aprobado):** se quitan de la tabla y se documenta la vía
real (GUI o `python restore_backup.py`). Los informes históricos de `docs/` se
dejan como registro.

**Commit:** `0d0cb8d`.

---

## F5 — `bedrock_server_how_to.html` versionado

**Síntoma:** doc oficial que viaja en el zip de BDS, commiteada, contra el
disclaimer del README ("no redistribuye archivos del juego").

**Fix:** `git rm --cached` (archivo local conservado), alta en `.gitignore`
(sección Mojang) y en la lista de no-copiar de AGENTS. **Pendiente en el
próximo sync:** eliminarlo del repo público.

**Commit:** `3bcb082`.

---

## F6 — Higiene local

**Fix:** `.playwright-mcp/` y `whatsapp-web-qr.png` a `.gitignore` y
eliminados del disco (aprobado). Se eliminaron los `be_*.ndjson` que dejaron
los wrappers reales de F1.

**Commit:** `7955a09`.

---

## F7 — CI y documentación

**Fix:** `.github/workflows/tests.yml` (windows-latest, Python 3.11,
`requirements-dev.txt`, `pytest -m "not e2e"`). Se agrega al repo público en el
próximo sync, junto con este informe y las notas de AGENTS/REGISTRO_TESTS.

**Verificación final:** 10/10 corridas verdes post-cambios; `git status`
limpio; tag `post-ronda-2026-09-10`.

---

## Riesgos residuales / pendientes

1. **Hermeticidad incompleta del lifespan en tests:** cada `TestClient`
   ejecuta `auto_backup.recover_interrupted_restores(config.BASE_DIR)` y
   `bds_update_service.recover_interrupted_updates()` contra la instalación
   real. Hoy son no-ops (no hay staging/`.bak_*`), pero si existieran residuos
   reales, un test podría tocarlos. Follow-up sugerido: sandbox de `BASE_DIR`
   por test o flags de solo-lectura para esos recover en modo test.
2. **LAN sin autenticación:** documentado como opt-in para red doméstica
   (`GUI_ALLOW_LAN=1`). Mantenerlo así o añadir token si se pide.
3. **CI pendiente de sync:** el workflow vive aquí; el repo público aún no lo
   tiene (y aún tiene el HTML de F5).
4. **Backups reales de F1:** no se borran (son válidos). Si se quiere limpiar,
   hacerlo manualmente.
5. **Oráculos PBT:** al activar 24 tests nuevos no aparecieron más fallos, pero
   el caso de `localhost` muestra que conviene revisar oráculos que enumeran
   valores permitidos (mismo patrón que el fix de `console_lang` de agosto).
