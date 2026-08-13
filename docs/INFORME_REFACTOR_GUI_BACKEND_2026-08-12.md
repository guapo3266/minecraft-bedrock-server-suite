# INFORME REFACTOR GUI BACKEND — 2026-08-12

Refactor de `server_gui_server.py` (1.635 líneas) a un paquete modular
`gui_backend/`, ejecutado de forma incremental con verificación lockstep
sobre la suite de tests. Este documento describe qué se hizo, los bugs
encontrados en el camino y cómo se resolvieron.

## 1. Objetivo y contexto

`server_gui_server.py` mezclaba en un solo archivo: estado concurrente
(ServerManager con locks y eventos), control del proceso `server_wrapper.py`,
REST, WebSocket, propiedades, backups, instalación/actualización de BDS y el
arranque de Uvicorn. El objetivo era separar por responsabilidad sin romper
rutas, códigos HTTP, el protocolo WebSocket, ni la API pública que los tests
importan directamente.

La carpeta es un entorno de pruebas (TESTTEST); el código validado se
sincronizó después a "Servidor de Guapo" (servidor real) y se publicó en el
repo `minecraft-bedrock-server-suite` (GitHub).

## 2. Línea base (Commit 0)

- **Git**: no existía repo; se inicializó (`af71b99`) ampliando `.gitignore`
  con `static_analysis_semgrep_1/` y `gui_frontend/node_modules/`. 117
  archivos, 2,65 MB, sin secretos ni archivos grandes inesperados.
- **Contrato**: se documentó toda la API/WS en `docs/API_CONTRACT.md`
  (19 rutas REST + WebSocket, códigos, payloads, invariantes de concurrencia)
  como referencia contra regresiones (`2091abe`).
- **Suite no-e2e**: 162 passed, 2 deselected (marcados `@pytest.mark.e2e`),
  1 warning preexistente de Starlette.

## 3. Ejecución del refactor (commits 1-9)

| Commit | Contenido |
|---|---|
| `a73a36f` | `gui_backend/` + `config.py`, `security.py`, `metrics.py` |
| `9433e18` | `ServerManager` → `state.py` + `build_public_status()` (estado público único) |
| `c185a42` | `supervisor.py` (spawn del wrapper + hilo lector de stdout) |
| `f53dde2` | `services/properties.py` |
| `8c28947` | `services/backups.py` |
| `aa44d8e` | `services/bds_update.py` (Mojang, staging, rollback, recovery) |
| `d8bb88d` | `services/setup.py` |
| `7c6089f` | 6 routers (`system`, `properties`, `setup`, `actions`, `backups`, `websocket`) + `create_app()` |
| `f51fc49` | Cierre: limpieza de re-exports + `docs/ARCHITECTURE.md` |
| `394d270` | `packet-statistics.txt` deja de versionarse |

Resultado: `server_gui_server.py` pasó de 1.635 → **102 líneas** (punto de
entrada + `create_app()`); `gui_backend/` tiene **1.481 líneas / 18 módulos**.
Suite **162/162 en cada commit**. Los e2e reales (API Mojang + ciclo completo
GUI→wrapper→BDS→backup caliente) pasaron al final: **2 passed en 51,7s**.

## 4. Bugs encontrados y cómo se resolvieron

### 4.1 Regresión real: `/api/backups` perdió su decorador (404)
Al extraer `services/backups.py`, el script de corte de líneas eliminó el
decorador `@app.get("/api/backups")` que quedaba justo antes del punto de
corte, dejando `list_backups` sin registrar (habría devuelto 404). Ningún
test no-e2e lo detectaba (probaban el helper directamente, no la ruta HTTP).
**Detección**: smoke HTTP manual con `TestClient` tras el commit. **Solución**:
el decorador se restauró en `gui_backend/routers/backups.py` durante la
extracción de routers (Commit 5) y el smoke confirmó 200.

### 4.2 Parches "muertos" de monkeypatch (trampa de re-exports)
Los tests parcheaban nombres en el namespace de `server_gui_server`
(`sgs.PROPS_PATH`, `sgs.requests.get`, `sgs.subprocess.Popen`,
`sgs.run_wrapper_thread`, `gui._apply_staged_update`, `gui.SERVER_STOP_TIMEOUT_SEC`,
etc.). Un simple re-export no basta: si el código movido lee la constante vía
`gui_backend.config.PROPS_PATH` y el test parchea `sgs.PROPS_PATH`, el test
pasa en verde pero parchea un nombre muerto — peor aún, un test que parcheaba
`PROPS_PATH` habría escrito el **archivo real** de properties.
**Solución**: regla lockstep — cada commit que mueve código migra en el MISMO
commit los targets de `monkeypatch.setattr` y los lectores directos al módulo
definitivo, y la convención de llamar por atributo de módulo en runtime
(`requests.get`, `auto_backup.create_backup`, `supervisor._spawn_wrapper_process`).
Se verificó con grep inverso que todo target parcheado tiene lector real.

### 4.3 Test PBT preexistente defectuoso (flakiness)
`test_extract_placeholders_roundtrip` (test_console_lang_pbt.py) fallaba de
forma intermitente: la estrategia `placeholder_names()` puede generar keywords
de Python (`or`, `as`) y el template `f"inicio {or} fin"` no parsea
(SyntaxError). No tenía relación con el refactor, pero rompía la disciplina
de "suite verde por commit".
**Solución**: fix mínimo en el test (`assume(not any(keyword.iskeyword(n) ...))`),
sin tocar producción. Se documenta aquí para que conste que el test fue
defectuoso desde el principio.

### 4.4 Accidentes de edición propios (mismo commit, corregidos y verificados)
- Una edición con `edit` reemplazó `def _version_tuple` por
  `def _ensure_local`, dejando dos líneas huérfanas y el cuerpo del tuple
  colgando; se detectó al compilar y se revirtió manualmente.
- El mismo tipo de error rompió el salto de línea en una llamada multi-línea
  de `_apply_staged_update` en un test (quedó `(staging, base,` pegado a la
  siguiente línea); se restauró la indentación original.
- El recorte de bloques grandes se hizo con un script Python por marcadores
  (nunca con edición manual de 150 líneas), preservando el EOL exacto (`\n`)
  del archivo para no ensuciar el diff con cambios de línea.
**Lección aplicada**: para bloques grandes, corte por marcadores + `py_compile`
+ suite completa en cada paso; los accidentes quedaron confinados y visibles
en el diff.

### 4.5 `packet-statistics.txt` modificado por los e2e
El test e2e real arrancó BDS y este sobrescribió `packet-statistics.txt`
(dato de runtime versionado en la línea base). Se restauró al HEAD y, a
petición del usuario, se dejó de versionar (`git rm --cached`, conservando
el archivo local) en el commit `394d270`.

### 4.6 Efecto colateral del e2e sobre el `server.properties` real
Al verificar la suite tras el cierre, un test no-e2e pasó a SKIP
(`test_worker_lectura_snapshot_fallida_programa_reintento`): su condición
exige un mundo real con `db/`, y `auto_backup.WORLD_DIR` apuntaba a
`worlds/TestWorld`, que ya no existía. Causa: el test e2e real
(`test_e2e_gui_flag_backup_in_progress_nunca_true_caliente`) reescribe el
`server.properties` real (`level-name=TestWorld`) para arrancar BDS con un
mundo de prueba y, al terminar, borra `worlds/TestWorld`. Si el mundo ya
existía o la restauración de props fallaba, la configuración quedaba
apuntando a un mundo inexistente (afecta al arranque real de la GUI).

**Solución** (test, no producción):
- Restauración de props con `with open(...)` (flush+close explícito) y sin
  `except: pass`: si la configuración no puede restaurarse, el test FALLA
  visible en vez de dejarla tocada.
- El mundo `worlds/TestWorld` se borra SOLO si el test lo creó
  (`world_existed`); un mundo preexistente nunca se elimina.
- Se restauró el `server.properties` local a `level-name=Bedrock level`
  (el resto del archivo intacto). Suite de vuelta a 162/162, 0 skips.

## 5. Decisiones de diseño relevantes

- **`manager` singleton único** en `state.py`; los tests lo resetean por
  atributos, nunca lo reemplazan → cero migración de esos parches.
- **WS broadcast en `state.py`** (registro `active_websockets` + `broadcast`):
  los routers dependen de state, nunca al revés (sin ciclos).
- **`build_public_status()`**: única fuente del payload de estado para
  `/api/status`, el `init` del WS y `update_status` (antes duplicado en 3
  sitios); muestrea hardware ANTES de tomar `manager.lock` y acepta `players`
  pre-leídos bajo lock para snapshots atómicos.
- **Tests de texto fuente migrados**: los que inspeccionaban el contenido de
  `server_gui_server.py` (cadenas del wrapper, mutaciones bajo `manager.lock`,
  conteo de writes a stdin) ahora apuntan a `supervisor.py`/`state.py` o al
  escaneo multi-archivo de `gui_backend/` (invariante 6 writes == 6 locks).
- **`L_PY_FILES`** (PBT de i18n) ampliado con los módulos nuevos que usan `L()`.

## 6. Distribución final

1. TESTTEST: 12 commits (historial completo del refactor).
2. "Servidor de Guapo": código sincronizado (backend, tests, docs); datos del
   servidor (worlds, backups, properties) intactos.
3. `minecraft-bedrock-server-suite`: commit `042996b` pusheado a
   `origin/main` (GitHub). Suite validada en el repo antes del push:
   160 passed, 2 skipped (e2e sin `bedrock_server.exe`), 2 deselected.
   `docs/DISENO_UI_GUI.md` (no rastreado, preexistente) quedó fuera del commit.

## 7. Cómo verificar

```bat
python -m pytest tests -m "not e2e" -q     :: 162 passed (requiere TESTTEST)
python -m pytest tests -m e2e -q           :: 2 passed (requiere bedrock_server.exe + red)
python server_gui_server.py                :: arranque manual de la GUI
```
