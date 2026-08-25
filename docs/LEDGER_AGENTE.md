# LEDGER_AGENTE — Minecraft Bedrock Server Suite (agente 24/7)

Formato por entrada: fecha | tarea | archivos | tests | fuente | outcome

## 2026-08-24 — P0-1: Amplía PBT schedule_config (interval 5-1440, HH:MM) y watchdog backoff. Anti-drift DEFAULTS wrapper vs GUI
- **Tarea**: P0-1 de la cola priorizada. Ampliar PBT para `schedule_config` (rango 5-1440, HH:MM) y `watchdog` backoff. Anti-drift entre `wrapper_schedule.SCHEDULE_DEFAULTS` y `gui_backend/services/schedule_config.DEFAULTS` + bounds del intervalo.
- **Archivos**:
  - `wrapper_schedule.py:15-22` — añade `MIN_INTERVAL_MIN=5`, `MAX_INTERVAL_MIN=1440` y corrige `_coerce_schedule_value` para intervalo: `5 <= iv <= 1440` (antes `>=1`). Elimina drift donde wrapper aceptaba 1-4 y GUI rechazaba.
  - `tests/test_schedule_watchdog.py:1-8, 417-599` — añade imports hypothesis+re+tempfile y 11 PBTs: `test_pbt_interval_valido_aceptado`, `test_pbt_interval_invalido_rechazado`, `test_pbt_interval_tipos_no_enteros_rechazados`, `test_pbt_hhmm_valido_aceptado`, `test_pbt_hhmm_invalido_rechazado`, `test_pbt_hhmm_casos_borde`, `test_pbt_watchdog_backoff_monotono_y_acotado`, `test_pbt_watchdog_schedule_constantes`, `test_pbt_defaults_anti_drift_extendido`, `test_pbt_crossed_daily_never_crash`, `test_pbt_gui_save_wrapper_load_coherentes`. Cubre validación interval 5-1440, HH:MM regex `^([01]\d|2[0-3]):[0-5]\d$`, coherencia GUI save → wrapper load, backoff monotono/acotado y defaults.
- **Tests**: `python -m pytest -m "not e2e" -q` → **316 passed, 2 deselected** (antes 290). `tests/test_schedule_watchdog.py` solo → 44 passed. Sin flake. Cubre P1 `test_rotate_old_survivors...` sigue verde con retry automático.
- **Fuente**: No toca BDS/red/SO — lógica local de validación y watchdog. No requiere websearch (intervalo y HH:MM vienen de `API_CONTRACT.md:76-77` y `gui_backend/config.py:31`).
- **Outcome**: PASS. Drift de intervalo corregido. PBT amplían cobertura interval/HH:MM/backoff y anti-drift de bounds. Listo para P0-2.

## 2026-08-24 — P0-2: Extrae _is_safe_zip_entry/_pack_dest duplicado a módulo compartido zip_safety.py
- **Tarea**: P0-2 de la cola priorizada. Centraliza guards anti zip-slip y clasificacion de packs duplicados en `zip_safety.py` (fuente unica) y re-exporta en `auto_backup.py`, `restore_backup.py` y `gui_backend/security.py` sin romper anti-drift.
- **Archivos**:
  - `zip_safety.py:1-60` — nuevo modulo central: `SERVER_PACK_DIRS`, `PACK_ZIP_PREFIX`, `_is_safe_zip_entry` y `_pack_dest` (logica identica previa, tests Hypothesis preservan comportamiento). Alias `_SERVER_PACK_DIRS`, `_PACK_ZIP_PREFIX` para compatibilidad.
  - `auto_backup.py:1-16, 152-158, 551-592` — importa `_is_safe_zip_entry`/`_pack_dest` y constantes desde `zip_safety`; elimina definiciones duplicadas (con comentario de centralizacion). Re-export mantiene `auto_backup._is_safe_zip_entry is zip_safety._is_safe_zip_entry`.
  - `restore_backup.py:1-17, 130-193` — importa desde `zip_safety`, alias `_SERVER_PACK_DIRS`/`_PACK_ZIP_PREFIX`; elimina duplicados con comentarios.
  - `gui_backend/security.py:1-8, 65-79` — re-exporta `_is_safe_zip_entry` desde `zip_safety` (mantiene API `server_gui_server`/`bds_update`).
  - `tests/test_pbt_properties.py:548-630` — extiende anti-drift: `test_pack_dest_consensus` (Hypothesis 300 ejemplos sobre `server_resource_packs/...`), `test_zip_shared_module_identity` (alias `is` a `zip_safety` y constantes). Consenso sigue cubriendo 3 modulos (incluye `gui_backend.security`).
  - `AGENTS.md:53` — actualiza regla de oro #5: duplicado → centralizado en `zip_safety.py` con test `test_pbt_properties.py:548`.
  - `docs/ARCHITECTURE.md:14-22` — añade `zip_safety.py` al mapa y anota `security.py` como re-export.
- **Tests**: `python -m pytest -m "not e2e" -q` → **318 passed, 2 deselected** (antes 316; +2 PBT P0-2). `test_packs_in_backup.py` 7/7 verde; consenso zip y pack_dest 300 ejemplos cada uno.
- **Fuente**: No toca BDS/red/SO — refactor local de guards puro-Python. No requiere websearch.
- **Outcome**: PASS. Drift eliminado sin duplicacion; mismos objetos compartidos, rotacion y restore intactos. Listo para P0-3.

