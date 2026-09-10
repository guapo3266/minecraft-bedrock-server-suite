# Handoff de verificación independiente — ronda 2026-09-10

**Para:** un agente/IA verificador sin contexto previo.
**Regla del encargo:** NO confíes en este documento. Cada afirmación numerada
(`C1…C20`) trae un comando y un criterio PASS/FAIL. Tu trabajo es intentar
falsarla; si algo no cuadra, repórtalo con evidencia (comando + salida).

---

## 0. Entorno y rutas

| Elemento | Valor |
|---|---|
| Repo de desarrollo (todo ocurre aquí) | `C:\Users\guapo\Downloads\Servidores_Minecraft\TESTTEST` |
| Servidor REAL (producción, sin git) | `C:\Users\guapo\Downloads\Servidores_Minecraft\Servidor de Guapo` |
| Repo público (GitHub) | `C:\Users\guapo\Downloads\Servidores_Minecraft\minecraft-bedrock-server-suite` (origin `https://github.com/guapo3266/minecraft-bedrock-server-suite`, rama `main`) |
| SO / shell | Windows, PowerShell 5.1 (para `agent-browser`, usar Git Bash: `& "C:\Program Files\Git\bin\bash.exe" -c '...'`) |
| Python (venv) | `.venv\Scripts\python.exe` → 3.11.8 |
| Node/npm | v24.15.0 / 11.12.1 |
| Tools | ruff 0.16.6, pytest 9.1.1, hypothesis 6.165.10, httpx 0.28.1, pytest-cov 7.1.0, agent-browser 0.36.0 |
| HEAD al entregar | `12a242a` (código); este handoff se commitó como `4a710a7` y el tag `final-2026-09-10` se movió ahí (78 commits desde `pre-ronda-2026-09-10` al momento de ese commit; ver §8) |

Antes de empezar: `git status --short` en TESTTEST debe estar **vacío**. Si no
lo está, alguien tocó algo después del handoff: revisar `git log --oneline -5`.

---

## 1. Contexto y alcance

Trabajo pedido: auditar el repo (roast/evaluación), correr un plan de mejoras
seguro y documentado, y luego ejecutar los pendientes (e2e reales + sync a
producción y repo público). Se hicieron **77 commits** desde
`pre-ronda-2026-09-10`, en dos franjas (madrugada y mañana del 2026-09-10).

**Se modificó:** tests, documentación, tooling (ruff/CI), código de producción
con cambios acotados y testeados, frontend (src + `dist` reconstruido).
**NO se modificó:** datos de instalación (`worlds/`, `server.properties`,
`data/`, backups), remotos/configs git, ni el `AGENTS.md` del repo público.

Los hallazgos originales y su mapeo a fixes están en:
- `docs/INFORME_REVIEW_2026-09-10.md` (F1–F7 de la ronda 1)
- `docs/INFORME_RONDA2_2026-09-10.md` (mejoras + cobertura)
- `docs/INFORME_RONDA3_2026-09-10.md` (lint, seguridad, tools, frontend, QA visual)
- `docs/REGISTRO_TESTS.md` (resumen por rondas)

---

## 2. Estado observado al entregar

```powershell
cd C:\Users\guapo\Downloads\Servidores_Minecraft\TESTTEST
.venv\Scripts\python.exe -m pytest tests -m "not e2e" -q   # 704 passed, 2 deselected
.venv\Scripts\python.exe -m ruff check .                   # All checks passed!
cd gui_frontend; npm run lint                              # Found 0 warnings and 0 errors
cd ..; git status --short                                  # (vacío)
```

- 70 archivos `tests/test_*.py`; 706 tests colectados; 2 e2e (`-m e2e`).
- Backups de TESTTEST en `..\..\Backups_Minecraft\auto_backups\TESTTEST`: 10.
- Repo público: `main` == `origin/main` == `9d05fef`; árbol limpio.
- Producción: sin procesos `python`/`bedrock_server` al sincronizar.

---

## 3. Mapa de cambios por bloque

### A. Tests: determinismo y aislamiento (ronda 1, F1)
- Causa raíz: el hilo daemon `gui-watchdog` del lifespan de `TestClient`
  sobrevivía a los monkeypatches y podía lanzar **wrappers/BDS reales** al leer
  configs temporales (creó 2 backups reales de 85 MB y hacía la suite flaky).
- Fix: fixture de sesión `_watchdog_de_fondo_desactivado` en `tests/conftest.py`
  (seam `watchdog._start_real` para tests que necesitan la implementación) +
  `_recuperaciones_no_tocan_la_instalacion_real`; fakes deterministas en tests;
  oráculos PBT corregidos (`localhost`, `WORLDS`, U+2028);
  guard `test_watchdog_de_fondo_neutralizado_en_la_suite`.
- Commits: `6681385`, `fb54ced`, `2018a79`, `7d87d39` (lint), `a4e7adc` (CLI).

### B. Guardas HTTP tempranas (F2 de la ronda 2)
- `server_gui_server.create_app()` instala un middleware que aplica
  `_ensure_local` + `_check_origin` a **todo `/api/*` antes del routing y de
  pydantic** (antes un body inválido devolvía 422 y permitía enumerar esquema).
- Inventario anti-drift en `tests/test_router_guards.py` (vía `app.openapi()`;
  FastAPI nuevo ya no aplana `app.routes`). 33 tests.
- Commit: `253b839`.

### C. Semántica de stop y apagado
- `stop_requested` solo se marca **después de entregar** el `stop` por stdin
  (`routers/actions.py`, `lifecycle.restart_wrapper`, `lifecycle.stop_and_wait`).
- `initiate_shutdown` cancela backup y reanuda; idempotente.
- Tests: `test_lifecycle_stdin_roto.py`, `test_shutdown_stdin.py`, `test_actions_router.py`.
- Commits: `38af903` (WIP), `657061d`, `1651c01`.

### D. Backups: integridad y robustez
- Sanidad post-escritura del ZIP (vacío o sin `level.dat` no se publica).
- Aviso de disco libre < snapshot (no bloqueante) + mensaje específico de ENOSPC.
- Resultado atómico del worker (`tmp+fsync+replace`) y snapshot ilegible →
  error `Snapshot:` retryable (sin traceback).
- Límite anti zip-bomb al restaurar: `zip_safety.MAX_RESTORE_UNCOMPRESSED_BYTES`
  (20 GB) aplicado en GUI y CLI antes de extraer.
- `recover_interrupted_restores` con ramas de rollback/cuarentena cubiertas.
- Commits: `b7f26c0`, `4c1dbbb`, `b269800`, `d1c3cf8`, `6000b8f`, `2babca2`,
  `21a2f43` (adaptador `_WorkerProcess`), `25c75a2`.

### E. Config: lector tolerante de `server.properties`
- Nuevo `server_properties.read_value` (acepta `clave = valor`, comentarios
  `#`/`;`, case-insensitive) usado por wrapper, `auto_backup`, CLI y allow-list.
- Tests: `test_server_properties_reader.py` + PBT `test_server_properties_pbt.py`.
- Commit: `91ef10d` (+ `db18ceb` docs).

### F. Tooling, CI y deps
- `ruff.toml` (F/E9) + paso de lint en CI; `server_wrapper.py` ignora F401
  (fachada de re-exports documentada); `requirements-dev.txt`; CI
  `.github/workflows/tests.yml` (windows-latest: ruff + pytest con cobertura +
  lint de frontend); `pytest.ini` `xfail_strict` + `filterwarnings = error`.
- `tools/verify_backups.py` (verificación CRC batch + cuarentena `_CORRUPTO`).
- `pip check`/`pip-audit` sin problemas; `npm audit fix` (nanoid 3.3.18) → 0 vulns.
- Commits: `4585d22`, `000b6f0`, `a0dec1f`, `709670a`, `cbd2957`.

### G. Frontend
- `App.jsx`: rechazo HTTP de `/api/command` visible; `UpdateModal` con
  `max-h-[85vh]`+scroll; 15 warnings de oxlint a 0; `dist` reconstruido.
- QA visual real con agent-browser + agente de visión: dashboard y modales
  renderizan sin errores de consola ni glitches; estáticos 200.
- Commits: `f8b6cf8`, `0903e69`, `5f5a89e`.

### H. Sync y limpieza (post-aprobación del usuario)
- E2E reales ejecutados: 2 passed (incluye GUI+BDS real). Se corrigió una fuga
  de `stdin=PIPE` del subproceso GUI que el gate de warnings convertía en fallo
  (`1307f86`).
- Producción: 129 archivos copiados, dist limpio, datos intactos.
- Público: espejo + 5 commits + push (`9d05fef`); se quitó
  `bedrock_server_how_to.html` y `docs/LEDGER_AGENTE.md`.
- `AGENTS.md` nunca commiteado al público (se restauró su ignore: `12a242a` dev,
  `9d05fef` público).
- Eliminados los 2 backups residuales de F1 (85 MB c/u).

---

## 4. Claims verificables (intenta falsificarlos)

> Nota: los comandos asumen `workdir = TESTTEST` y PowerShell.

**C1. Suite no-e2e: 704 passed, 2 deselected, 0 skips, 0 warnings.**
```powershell
.venv\Scripts\python.exe -m pytest tests -m "not e2e" -q
```
PASS = `704 passed, 2 deselected`; FAIL si hay `skipped`, `warning` o `failed`.

**C2. Determinismo: 10 corridas seguidas en verde.**
```powershell
1..10 | ForEach-Object { .venv\Scripts\python.exe -m pytest tests -m "not e2e" -q | Select-Object -Last 1 }
```
PASS = las 10 terminan en `704 passed`.

**C3. La suite no toca la instalación real (ni wrappers ni backups).**
Antes: contar `data\wrapper_events\*` y `..\..\Backups_Minecraft\auto_backups\TESTTEST\*.zip`.
Correr la suite (C2). Después: mismos conteos y
`Get-CimInstance Win32_Process | ? CommandLine -match 'server_wrapper\.py'` vacío.
PASS = sin archivos/procesos nuevos.

**C4. El watchdog de fondo está neutralizado en tests (y hay guard).**
```powershell
.venv\Scripts\python.exe -m pytest tests/test_review_hallazgos.py::test_watchdog_de_fondo_neutralizado_en_la_suite -q
```
Además leer `tests/conftest.py`: fixture `_watchdog_de_fondo_desactivado`.
PASS = test verde y el fixture presente. Falsificar: quitarlo y ver que la
suite vuelve a mostrar efectos reales (lanzará wrappers).

**C5. Middleware `/api/*`: 403 antes de validar body y con Origin externo.**
```powershell
.venv\Scripts\python.exe -m pytest tests/test_router_guards.py -q   # 33 passed
```
Manual real: levantar `uvicorn server_gui_server:app --port 8123` y
`POST /api/command` con `Origin: http://evil.example` y body `{}` → **403**
(no 422). PASS = 403.

**C6. Stop honesto: no se marca `stop_requested` si el stdin falla.**
```powershell
.venv\Scripts\python.exe -m pytest tests/test_lifecycle_stdin_roto.py tests/test_shutdown_stdin.py tests/test_actions_router.py -q
```
Revisar además que en `lifecycle.py`/`actions.py` el flag se marca tras el
write exitoso. PASS = tests verdes y código coherente.

**C7. Anti zip-bomb y guards de restauración.**
```powershell
.venv\Scripts\python.exe -m pytest tests/test_zip_safety.py tests/test_zip_safety_packs.py tests/test_restore_backup.py tests/test_restore_cli.py -q
```
PASS = verde; el rechazo ocurre antes de extraer (mundo intacto).

**C8. `read_value` tolerante a espacios/comentarios/case.**
```powershell
.venv\Scripts\python.exe -m pytest tests/test_server_properties_reader.py tests/test_server_properties_pbt.py -q
```

**C9. CLI interactivo de restauración cubierto (cancelar/rollback/fallos).**
```powershell
.venv\Scripts\python.exe -m pytest tests/test_restore_cli.py -q   # 10 passed
```

**C10. Scheduler de backups por ramas reales.**
```powershell
.venv\Scripts\python.exe -m pytest tests/test_backup_scheduler.py -q   # 5 passed
```

**C11. Worker: resultado atómico y snapshot ilegible retryable.**
```powershell
.venv\Scripts\python.exe -m pytest tests/test_backup_worker_unit.py tests/test_backup_worker_usage.py -q
```

**C12. `tools/verify_backups.py` marca corruptos y devuelve exit 1.**
```powershell
.venv\Scripts\python.exe -m pytest tests/test_verify_backups_tool.py -q
# manual sobre una carpeta de prueba con un zip roto:
.venv\Scripts\python.exe tools\verify_backups.py <carpeta>
```

**C13. Lint backend limpio.**
```powershell
.venv\Scripts\python.exe -m ruff check .
```
PASS = `All checks passed!`. (Único ignore: F401 en `server_wrapper.py`.)

**C14. Frontend sin warnings y `dist` reproducible.**
```powershell
cd gui_frontend; npm run lint; npm run build; cd ..
```
PASS = `0 warnings and 0 errors`; el build regenera el mismo bundle
(`dist/assets/index-Ci9BdA7d.js`) y, como mucho, cambia el fin de línea del
árbol de trabajo (no el contenido lógico). Si aparece contenido distinto,
investigar (el hash del nombre viene del contenido).

**C15. Cobertura del set del CI ~85%.**
```powershell
.venv\Scripts\python.exe -m pytest tests -m "not e2e" -q --cov=gui_backend --cov=auto_backup --cov=wrapper_backup --cov=wrapper_events --cov=wrapper_schedule --cov=wrapper_state --cov=wrapper_console --cov=zip_safety --cov=console_lang --cov=backup_worker --cov=server_wrapper --cov=restore_backup --cov=server_gui_server --cov=server_properties --cov-report=term:skip-covered
```
PASS ≈ TOTAL 85%, 12–14 módulos al 100%.

**C16. E2E reales pasan (⚠️ destructivo: arranca BDS real).**
```powershell
.venv\Scripts\python.exe -m pytest tests -m e2e -q   # 2 passed (~2-3 min)
```
Advertencias: toca `server.properties` (lo restaura), usa
`worlds/TestWorld` (preexistente: no se borra) y **la rotación del ciclo de
backup recorta backups reales** (por eso no conviene correrlo en bucle).
PASS = 2 passed y `server.properties` con hash idéntico antes/después.

**C17. Dependencias sin problemas.**
```powershell
.venv\Scripts\python.exe -m pip check
.venv\Scripts\python.exe -m pip_audit -r requirements.txt
cd gui_frontend; npm audit; cd ..
```
PASS = sin conflictos y 0 vulnerabilidades.

**C18. Producción sincronizada con el código actual.**
Comparar hashes dev↔`..\Servidor de Guapo` para:
`server_properties.py`, `auto_backup.py`, `gui_backend\routers\websocket.py`,
`gui_frontend\dist\index.html`, `gui_frontend\dist\assets\index-Ci9BdA7d.js`,
`.gitignore`, `README.md`, `tools\verify_backups.py`.
PASS = todos OK; `dist/index.html` referencia `index-Ci9BdA7d.js` y
`index-CyyFGhAX.css`; no hay assets viejos (`index-BWuqduE0.js`,
`index-DOnpjmM_.css`, `index-Nl2_jlvp.js`).

**C19. Repo público sincronizado y pusheado.**
```powershell
cd ..\minecraft-bedrock-server-suite
git fetch origin; git status --short; git rev-parse --short main origin/main; git log --oneline -7
git log --all --oneline -- AGENTS.md     # debe estar VACÍO
git check-ignore -v AGENTS.md            # .gitignore:21:AGENTS.md
Test-Path bedrock_server_how_to.html     # False
```
PASS = árbol limpio, `main == origin/main == 9d05fef`, sin commits de
`AGENTS.md`, HTML ausente. Los branches locales `codex/*` son **previos** y no
se tocaron.

**C20. Residuales del bug F1 eliminados.**
```powershell
Test-Path "..\..\Backups_Minecraft\auto_backups\TESTTEST\auto_backup_TESTTEST_inicio_2026-09-10_02-08-02_f37a8c.zip"
```
PASS = `False` (los dos fueron borrados; el conteo quedó en 10).

---

## 5. Puntos que requieren escepticismo (posibles autos-engaños)

1. **`filterwarnings = error`** (pytest.ini): hace fallar la suite ante
   cualquier warning. Es intencional (cazó el `stdin` sin cerrar del e2e y
   handles de tests), pero es frágil ante dependencias: si una actualización
   emite un deprecation ajeno, habrá que añadir un ignore justificado.
2. **Los fixtures de `tests/conftest.py` desactivan watchdog y recoveries
   reales.** No enmascaran el producto: el e2e arranca la GUI real como
   subproceso y su lifespan real (watchdog incluido) corre de verdad (C16),
   pero es el punto que un revisor debe mirar con más recelo: ¿algún test
   depende de que el watchdog no corra?
3. **Canarios de texto fuente** (p. ej. `with manager.stdin_lock:` == 6,
   prohibición de interpolar en `innerHTML`): protegen invariantes, pero no
   prueban semántica. Están complementados por tests de comportamiento.
4. **`server_wrapper.py` ignora F401**: son re-exports de fachada usados por
   tests y `gui_backend` (`test_pbt_properties.py` verifica identidad). No
   borrarlos sin actualizar consumidores.
5. **E2E son semidestructivos**: además de `server.properties` y `TestWorld`,
   el ciclo de backup real recortó backups de TESTTEST (16→12 en las corridas).
   Correrlos con conocimiento; no en bucle.
6. **El sync a producción es copia sin git**: la única garantía es el hash
   (C18). No hay historial allí.
7. **`data/schedule_state_gui.json` real** quedó tocado por el bug F1
   (`last_daily_restart_date=2026-09-10`); con `daily_restart_time=null` es
   inerte. No se revirtió por no inventar un valor previo.
8. **Venv con extras no declarados**: además de `requirements-dev.txt`, el
   venv tiene `pyyaml` y `pip-audit` (herramientas de esta auditoría). No
   afectan al repo; `ruff` sí quedó declarado.
9. **Tests de introspección usan `Path().read_text`** (F3); si se reformatean
   los archivos fuente, esos canarios se actualizan en lockstep (AGENTS.md).
10. **El tag `final-2026-09-10`** terminó apuntando a `4a710a7` (el commit
    de este mismo handoff), que ya incluye el fix del e2e (`1307f86`) y el
    `.gitignore` (`12a242a`). No es un fallo: el tag cierra la ronda completa
    (código + docs).

---

## 6. Verificación completa en orden (copiar/pegar)

```powershell
cd C:\Users\guapo\Downloads\Servidores_Minecraft\TESTTEST
git status --short                                  # vacío
.venv\Scripts\python.exe -m ruff check .            # C13
.venv\Scripts\python.exe -m pytest tests -m "not e2e" -q   # C1
1..10 | ForEach-Object { .venv\Scripts\python.exe -m pytest tests -m "not e2e" -q | Select-Object -Last 1 }  # C2
cd gui_frontend; npm run lint; cd ..                # C14
.venv\Scripts\python.exe -m pip check               # C17
.venv\Scripts\python.exe -m pip_audit -r requirements.txt
cd ..\minecraft-bedrock-server-suite; git fetch origin; git status --short; git rev-parse --short main origin/main; cd ..\TESTTEST   # C19
# C16 SOLO si se acepta el efecto en la instalación real:
.venv\Scripts\python.exe -m pytest tests -m e2e -q
```

---

## 7. Límites de este trabajo (lo que NO se hizo)

- No se hizo auditoría de accesibilidad formal (axe/`agent-browser a11y`);
  solo QA visual manual con screenshots.
- No hay tests JS del frontend (no hay stack de tests JS en el repo).
- No se corrió análisis de mutación ni fuzzing de red.
- No se tocó la lógica de negocio del wrapper fuera de lo listado en §3.
- La sincronización a producción/público se hizo **por pedido explícito**;
  no hay automatización de sync en CI.
- No se actualizó el `AGENTS.md` del repo público (está ignorado a propósito).

---

## 8. Inventario de commits

```powershell
git log --oneline pre-ronda-2026-09-10..HEAD   # 78 commits (77 de la ronda + el propio handoff)
```

Hitos representativos por bloque (ver §3 para el detalle):

| Bloque | Commits |
|---|---|
| Baseline ronda 1 | `38af903`, `2c76591`, `6681385`, `fb54ced`, `2018a79` |
| README/gitignore/html | `0d0cb8d`, `3bcb082`, `7955a09`, `12a242a` |
| Guardas/middleware | `253b839`, `7d87d39` |
| Backups/seguridad | `b7f26c0`, `4c1dbbb`, `b269800`, `2babca2`, `d1c3cf8`, `6000b8f`, `21a2f43` |
| Stop/lifecycle | `657061d`, `1651c01` |
| Config props | `91ef10d`, `db18ceb` |
| Tooling/CI/deps | `4585d22`, `a0dec1f`, `709670a`, `cbd2957` |
| Cobertura | `a4e7adc`, `ed62c06`, `92f221c`, `364965a`, `01c4818`, `dcfc6bb`, `310b1d2`, `c20e031`, `fc55359` |
| Frontend | `f8b6cf8`, `0903e69`, `5f5a89e` |
| E2E/sync | `1307f86`, docs `42b94a6`→`db9daf9` |

Tags: `pre-ronda-2026-09-10` (`38af903` al inicio de la ronda), `post-ronda`,
`post-ronda2`, `final-2026-09-10` (`4a710a7`, incluye el handoff; al cierre
de la ronda 3 apuntaba a `db9daf9`).

---

## 9. Criterio de aceptación del verificador

1. Todos los claims `C1…C20` con PASS, o un informe de fallo con evidencia.
2. Opinión independiente sobre los 10 puntos de §5 (¿enmascaran algo?).
3. Confirmar que los tres destinos quedan consistentes (§C18/C19) y que
   `git status` de TESTTEST sigue limpio al terminar.
4. Reportar cualquier cambio de comportamiento del producto no documentado en
   los informes de `docs/`.

---

## 10. Resultado de la verificación independiente (2026-09-10, tarde)

Ejecutada por un agente sin contexto previo, intentando falsificar cada claim,
con autorización explícita del usuario para el e2e (C16).

**Veredicto: C1–C20 PASS en los 20.** Evidencia clave:

- C1/C2: `704 passed, 2 deselected` — **12 corridas completas en verde**
  (las 10 de C2 + C1 + la de C15 con cobertura).
- C3: `data/wrapper_events` 2→2, backups 10→10, 0 procesos wrapper
  antes/después de las 12 corridas.
- C5: manual real con uvicorn (:8123): `POST /api/command` con
  `Origin: http://evil.example` y body `{}` → **403** (antes de pydantic).
- C12: manual con zip corrupto → renombrado a `*_CORRUPTO.zip`, exit 1, el
  bueno intacto.
- C14: `npm run build` regenera `dist/assets/index-Ci9BdA7d.js` **byte
  idéntico**; `git status` limpio tras el build (0 drift de árbol).
- C15: TOTAL 85%, 12 módulos al 100%.
- C16 (aprobado): `2 passed, 704 deselected` (~2:36 min); hash de
  `server.properties` idéntico antes/después; backups 10→10 (esta vez la
  rotación no recortó); sin huérfanos; 1 `be_*.ndjson` nuevo legítimo de la
  corrida real.
- C17/C18/C19/C20: 0 vulnerabilidades (pip/npm); 8/8 hashes OK contra
  producción; `main == origin/main == 9d05fef`, sin historia de `AGENTS.md`,
  HTML ausente; zip testigo de F1 ausente.

**Errata de este documento, corregida en la misma pasada:**

- C9 decía "9 passed": `tests/test_restore_cli.py` tiene **10** tests.
- §0/§5.10/§8 describían el tag `final-2026-09-10` en `db9daf9`: el tag se
  movió luego al commit del propio handoff (`4a710a7`; 78 commits desde
  `pre-ronda-2026-09-10`).

**Hallazgos nuevos (no bloqueantes; documentados en `AGENTS.md`):**

- **O1 (menor, producto)**: `stop_requested` se marca ANTES del write a
  stdin en `routers/system.py:139-140` (`POST /api/command`) y
  `gui_backend/routers/websocket.py:80-81` (comando WS) — el mismo defecto
  que esta ronda corrigió en `actions.py`/`lifecycle.py`. Si el stdin falla
  justo en un `stop` por consola/WS, el flag queda True con el servidor vivo
  y el watchdog no re-lanzaría un crash posterior. Fix sugerido: mover el
  flag tras el write + tests mirror de
  `test_schedule_watchdog.py::test_stop_stdin_roto_devuelve_500_y_no_marca_flag`
  para consola y WS.
- **O2 (higiene, producción)**: `..\Servidor de Guapo` conserva `tests/`
  (42 archivos) y `docs/` (16) de un sync anterior a esta ronda (fechas de
  agosto); el sync del 2026-09-10 no los copió (verificado por hashes).
  Limpiarlos allá en el próximo sync para respetar la regla de no-copiar.

**Opinión sobre §5 (punto 2 del criterio):** los 10 puntos se sostienen. Los
fixtures de aislamiento no enmascaran el producto: el e2e (C16) arrancó la
GUI real como subproceso (lifespan real incluido) y pasó, mientras la suite
no-e2e deja 0 artefactos — la discriminación entre "test aislado" y
"corrida real" funciona. El punto 10 quedó resuelto al mover el tag.

**Cambio de comportamiento no documentado:** ninguno encontrado
(`git log 12a242a..HEAD` no toca código/tests/src: solo docs de la ronda).
