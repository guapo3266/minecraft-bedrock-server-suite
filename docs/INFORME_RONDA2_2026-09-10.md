# Informe ronda 2 — 2026-09-10

**Contexto:** continuación de la ronda del mismo día (`docs/INFORME_REVIEW_2026-09-10.md`).
Objetivo: mejoras prácticas y reales al repo dev, con verificación, sin tocar datos
reales ni sincronizar a los destinos.

**Estado final:** 478 passed, 2 deselected (e2e), 0 skips — **10/10 corridas
consecutivas en verde**. Sin artefactos nuevos (0 `be_*.ndjson`; el backup más
reciente de `Backups_Minecraft/auto_backups/TESTTEST` sigue siendo de las 02:08
de la ronda 1).

---

## Cambios (todos con commit propio)

| Commit | Tipo | Qué y por qué |
|---|---|---|
| `fb54ced` | test | Fixture de sesión que impide que los lifespans de TestClient ejecuten `recover_interrupted_restores/updates` sobre la instalación REAL (cierra el riesgo residual #1 de la ronda 1). Los tests con tmp siguen ejercitando la implementación real. |
| `1ae5ff9` | fix | El guard de restore del CLI se escopa por ruta del ejecutable (un BDS de otra instalación ya no bloquea; fail-closed si no puede leer la ruta). Alineado con `external_probe` de la GUI. RED→GREEN. |
| `253b839` | feat/security | **Middleware de guarda temprana `/api/*`** (`_ensure_local`+`_check_origin` antes del routing y de pydantic). Hallazgo: un cliente externo podía recibir `422` de esquema (`POST /api/command` sin body) y enumerar rutas sin pasar los guards internos. Nuevo `tests/test_router_guards.py`: inventario anti-drift vía `app.openapi()` + 403 con cliente/Origin externos + regresión 403-antes-de-422. |
| `b7f26c0` | fix | Sanidad post-escritura del ZIP en `create_backup`: sin entradas o sin `level.dat` (modo snapshot) no se publica; el `.tmp` se limpia. Test de fault injection. |
| `4585d22` | ci | `permissions: contents: read`, `concurrency` con cancelación y job `frontend-lint` (Node 20 + `npm ci` + oxlint, verificado en local: 0 errores). `pytest.ini`: `xfail_strict=true`. |
| `21de1d1` | fix | WS `command` con el servidor apagado (o wrapper muerto) ya no desaparece en silencio: mismo feedback que `POST /api/command` (echo + aviso bilingüe) y sin escribir a stdin. |
| `7ac4e25` | fix/security | La GUI clásica (`web/app.js`) pinta jugadores y backups con `textContent` (antes interpolaba en plantillas `innerHTML`). Canary en `tests/test_web_classic_gui.py`; `node --check` OK. |
| `657061d` | fix | `restart_wrapper`/`stop_and_wait` ya no marcan `stop_requested` ni esperan 75s+ si el `stop` no se entregó (misma regla que `/api/action/stop`): cancelan, loguean y dejan el flag en False para no inhibir al watchdog. RED→GREEN sin timeouts reales. |
| `7674db9` | docs | `API_CONTRACT.md` (guarda temprana, WS offline, invariantes), `ARCHITECTURE.md` (middleware, fixtures de aislamiento, inventario de tests) y `AGENTS.md` (contratos y gotchas nuevos). |
| `4c1dbbb` | fix | `create_backup` distingue `ENOSPC` con mensaje accionable; `backup_worker.py` sin argumentos da uso + exit 2 en vez de traceback. Tests. |
| `cead3ea` | test/i18n | `tools/bds_first_run.py` entra en `L_PY_FILES` y en el barrido de higiene; sus mensajes pasan a f-strings. Nuevo guard anti-drift: todo módulo de producción (raíz, `gui_backend/`, `tools/`) que use `L()` debe estar listado. |
| `7b711c0` | fix | `_url_para_navegador`: corchetea IPv6 (`GUI_HOST=::1` generaba URL inválida). `iniciar_gui_lan.bat`: regla de firewall con `profile=private` (la GUI LAN no tiene auth) y fallback claro si no detecta la IP local. Tests del helper. |

## Verificación

- **Suite:** 10× `pytest tests -m "not e2e" -q` → 478 passed en todas.
- **Smoke real (uvicorn, puerto 8123, sin TestClient):**
  - `GET /api/status` → 200 (`running=false`, hardware presente).
  - `GET /` → 200, index del `dist` (545 bytes).
  - `GET /api/backups` → 16 backups.
  - `POST /api/command` con `Origin: http://evil.example` → **403**.
  - `POST /api/command` con body inválido + Origin externo → **403** (prueba de
    que la guarda corre ANTES de pydantic en ASGI real).
  - `POST /api/command` sin Origin (no-navegador), servidor apagado → `offline`.
  - Proceso terminado limpiamente (sin huérfanos).
- **Frontend:** `npm ci` + `npm run lint` → 0 errores (15 warnings). `node --check web/app.js` OK.
- **No contaminación:** 0 `be_*.ndjson` en `data/wrapper_events`; ningún backup
  nuevo tras las 02:08; 0 wrappers vivos al terminar.

## Pendientes (heredados de la ronda 1)

1. Próximo sync al repo público: quitar `bedrock_server_how_to.html` y agregar
   `.github/workflows/tests.yml` (+ `requirements-dev.txt`).
2. LAN sin autenticación: opt-in documentado; ahora el firewall solo abre en
   perfil privado.
3. Sandbox completo de `BASE_DIR` en tests (los recoveries reales ya están
   bloqueados por fixture; el resto del lifespan usa datos de instalación de
   forma inocua).

## Parte 3 — Cobertura de tests (misma noche)

Tests guiados por cobertura, sin tocar producción:

| Commit | Qué cubre | Antes → Después |
|---|---|---|
| `000b6f0` | `tests/test_backups_router.py` (listado/delete/download/verify/restore con `BACKUP_DIR` en tmp). `pytest-cov` en `requirements-dev.txt`, CI reporta cobertura (informativa, sin gate), `.gitignore` para `.coverage`/`htmlcov`. | router backups 60→90%, `services/backups` 70→94% |
| `e3f518a` | `tests/test_system_router.py` (/, favicon, `/api/command` vacío/offline/stdin roto) y `tests/test_zip_safety.py` (camino feliz de cuarentena + fallback de copia recursiva con rename bloqueado). | system 71→86%, fallback de `zip_safety` cubierto |
| `cf31d19` | `tests/test_wrapper_schedule_unit.py` (coerciones, recarga por mtime, estado diario, `_crossed_daily_time`) y `tests/test_wrapper_events_unit.py` (rotación y emisión NDJSON). | wrapper_schedule 76→97%, wrapper_events 77→80% |
| `b4f47b5` | `tests/test_backup_worker_unit.py` (contrato snapshot→result y prefijo `Snapshot:`) y `tests/test_auto_backup_symlink.py` (enlace que escapa rechazado / interno aceptado, con junction sin privilegios). | `_main` del worker y guard symlink cubiertos |

**Estado al cierre de la Parte 3:** 541 passed, 2 deselected (e2e), 10/10
corridas consecutivas en verde.

## Parte 4 — Última tanda de cobertura y generadores (misma noche)

| Commit | Qué |
|---|---|
| `25c75a2` | `tests/test_recover_interrupted_restores.py`: staging archivo, rollback, cuarentena de huérfanos, rename fallido y listdir inaccesible (ramas de no-pérdida-de-datos). |
| `1697836` | `tests/test_actions_router.py` + `test_external_probe.py`: backup caliente con stdin roto (500), update en curso, rollback sin versión (409); sonda tolerante a AccessDenied/NoSuchProcess. |
| `a3c76da` | `tests/test_lifecycle_errores.py` + `test_history_fallos.py`: spawn con error, cold_backup, timeouts de `stop_and_wait`, `watchdog.start` idempotente e historial-vacío con SQLite caído. |
| `89e023c` | `tests/test_supervisor_classify.py`, `test_bds_update_branches.py`, `test_metrics_branches.py`: prioridad/anti-spoofing de `classify_log_line`, límites de descarga del updater, resguardos ilegibles y ramas de métricas. |
| `8dbd622` | Tercer falso fallo de la base de Hypothesis: `_safe_chars` bloquea también `Zl/Zp` (U+2028 rompía el roundtrip de `parse_save_query_files` porque `str.strip()` lo elimina). |
| `6383b90` | `tests/test_supervisor_tail_events.py`, `test_security_origins.py`, `test_schedule_router.py`: lector NDJSON (espera/drena/termina), Origins malformados y `_get_request_port`, y validación del router de programación. |
| `6bc5c89` | Gate `filterwarnings = error` en `pytest.ini` (cualquier warning falla, incluidos handles sin cerrar) + últimos `open()` bare en tests y en `_FileCancelEvent.set()`. |
| `314ddac` | `tools/update_items_v2.py`: escrituras atómicas (tmp+fsync+replace) del `main.js` y de los JSON de packs/manifiestos del mundo, con test por subproceso en árbol falso. |
| `2271a7b` | Mismo patrón atómico en `tools/update_items.py` (v1) y `tools/de_ai.py` (reescribe fuentes); test de v1. |
| `a00063a` | Accesibilidad básica de la GUI clásica (`aria-hidden` en el canvas, `aria-label` en la consola). |
| `e721d90` | Cableado de `_spawn_wrapper_process` (env UTF-8, canal NDJSON, cwd), reapertura del emisor de eventos al cambiar el env y resolución del staging del updater (plano/carpeta/ambiguo/sin exe). |

## Parte 5 — Cierre

**Estado final (definitivo) de la noche:** **616 passed, 2 deselected (e2e),
0 skips; 3/3 y 5/5 corridas finales en verde** (y 10/10 tras los cambios de
producción), más dos corridas con base de Hypothesis fresca. Cobertura de los
módulos del CI: **73% → 89%**. Smoke real con uvicorn: status/index/backups
200, Origin externo y body inválido 403 con el middleware real. Gate de
warnings activo (`filterwarnings = error`) y CI/YAML validado. 0 `be_*.ndjson`,
0 wrappers vivos, ningún backup nuevo tras las 02:08 de la ronda 1.
`git status` limpio; tag final `final-2026-09-10`.
