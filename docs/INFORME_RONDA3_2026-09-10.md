# Informe ronda 3 — 2026-09-10 (sesión extendida de la mañana)

**Contexto:** continuación del mismo día (ronda 1 de la madrugada y ronda 2 al
cierre), con el pedido de seguir mejorando hasta las 15:00. **23 commits**
desde el cierre de la ronda 2 (`1296913`), todos verificados.

**Estado final:** `ruff check .` limpio; **702 tests, 2 deselected (e2e), 0
skips**; **10/10 corridas completas en verde** + una con base de Hypothesis
fresca; smoke real con uvicorn OK; 0 artefactos nuevos; `git status` limpio.

---

## 1. Lint estático (ruff)

- `ruff.toml`: reglas F (pyflakes) + E9 (sintaxis). `server_wrapper.py` ignora
  F401 por ser la fachada de re-exports documentada; `security.py` y
  `server_gui_server.py` llevan `# noqa` justificado en sus re-exports.
- Limpieza real de 26 imports/variables muertas en producción y tests, más una
  f-string sin placeholders. CI corre `python -m ruff check .` antes de pytest;
  ruff entra en `requirements-dev.txt` y queda documentado en README/AGENTS.
- Commit: `7d87d39` (+ `dd426e0`).

## 2. Cobertura de tests

| Zona | Antes → Después | Commit |
|---|---|---|
| CLI interactivo de restauración (cancelar, confirmar, corrupto, fallo de extracción, swap con rollback) | 22% → 70% | `a4e7adc` |
| `backup_scheduler` por ramas reales (IDLE/HOLDING/watchdog/despacho) | `server_wrapper` 27% → 57% | `ed62c06` |
| `send_command`, `read_stdout` con error, `execute_final_backup` | — | `92f221c` |
| `initiate_shutdown` (backup+resume, idempotencia) y `read_stdin` | — | `1651c01` |
| `zip_safety` (packs, guards, expansión) y sonda externa | — | `364965a`, `2babca2` |
| Resiliencia del lifespan, `broadcast()` con sockets muertos, resolvers H3 | — | `01c4818` |
| Fallback de stdout (versión y marcadores de backup) | — | `dcfc6bb` |
| Setup/properties (400/500) y path standalone de eventos | — | `310b1d2` |
| Updater (entrada insegura, progreso, `read_previous_version`) y worker | — | `c20e031` |

Cobertura del set de módulos del CI: **84% → 85%** (con 14 módulos al 100%).

## 3. Producto y robustez

- **Lector tolerante `server_properties.read_value`** usado por todos los
  parsers (wrapper, auto_backup, CLI, allow-list de la GUI): `backup-inicio =
  false` editado con espacios ya se respeta (`91ef10d`).
- **Anti zip-bomb al restaurar**: `MAX_RESTORE_UNCOMPRESSED_BYTES` (20 GB) en
  GUI y CLI; el mundo queda intacto si se excede (`2babca2`).
- **Worker**: resultado atómico (`d1c3cf8`), snapshot ilegible → error
  `Snapshot:` retryable en vez de traceback (`6000b8f`), adaptador
  `_WorkerProcess` en lugar de monkeypatch de métodos de `Popen` (`21a2f43`).
- **`mark_corrupt_zip`** idempotente y tolerante a rename bloqueado, sin perder
  el archivo (`6000b8f`).
- **Aviso temprano de disco** cuando el espacio libre es menor que el snapshot
  sin comprimir (no bloqueante; `b269800`).
- **Lifespan**: `await` del task de métricas cancelado y resiliencia a fallos de
  arranque de recoveries/watchdog/history (`d1f66f9`, `01c4818`).
- **`history.sweep`**: `PRAGMA wal_checkpoint(TRUNCATE)` diario best-effort
  (`d1f66f9`).
- **Firewall** idempotente (`configurar_firewall.bat`) y `.gitignore` de
  `bds_update_staging/`/`bds_update_prev_*/` (`d1f66f9`).

## 4. Herramientas y documentación

- **`tools/verify_backups.py`** (`a0dec1f`): verifica CRC de todos los backups,
  renombra corruptos con `_CORRUPTO` y devuelve exit 1 si encontró alguno.
- `tools/test_gui_e2e.py`: base configurable por `GUI_E2E_BASE` y PNG del
  screenshot ignorado (`5f761b4`).
- README: sección de **solución de problemas** ES/EN (`4e630dc`) y filas de
  `requirements-dev`, CI y verificador.
- AGENTS: lint, verificación de backups, límite de expansión y regla
  anti-regresión del lector de properties (`db18ceb`, `5f761b4`).
- ARCHITECTURE: `server_properties.py` en el mapa de módulos (`db18ceb`).

## 5. Frontend y dependencias

- `App.jsx`: el rechazo HTTP de `/api/command` (403/500) ahora se muestra en la
  consola, igual que el resto de los handlers (`f8b6cf8`; dist reconstruido).
- **0 warnings de oxlint** (`0903e69`): variables/params muertos fuera, `catch`
  sin binding, `IntersectionObserver` muerto eliminado en LiquidEther y el
  `exhaustive-deps` de Particles/CountUp documentado como intencional. El CSS
  del build baja al dejar de escanear clases muertas de Tailwind.
- **Dependencias**: `pip check` sin conflictos; `pip-audit -r requirements.txt`
  sin vulnerabilidades conocidas; `npm audit fix` sube `nanoid` a 3.3.18
  (**0 vulnerabilidades**; build idéntico) (`cbd2957`).
- Smoke de estáticos con el dist nuevo: `/`, `/assets/index-gwcnWVLZ.js` y
  `/assets/index-CyyFGhAX.css` responden 200.

## 6. QA visual con navegador real (agent-browser + Playwright)

Sobre el `dist` reconstruido, con la GUI real en `127.0.0.1` (verificado además
con un agente de visión sobre los screenshots):

- **Dashboard completo**: header con estado OFFLINE, botonera, medidores RAM/CPU/
  disco con datos reales, versión BDS, tarjeta de invitación con IPs LAN/pública,
  terminal con historial de la sesión anterior y filtros, tabs
  `Jugadores 0` / `Backups 16`, banner de allow-list desactivada. **0 errores de
  consola y 0 glitches visuales.**
- **Modal Configuración**: carga los valores reales de `server.properties`
  (nombre, modo, dificultad, cheats, max-players, online-mode, allow-list,
  puerto, distancias, timeout, permisos). Sin errores.
- **Modal Programación**: secciones de backups y watchdog completas; a 1440×900
  entra entero sin recortes. En viewports chicos el `max-h-[85vh]` con scroll
  interno cubre el contenido (el recorte aparente del primer QA era el límite de
  scroll, no un bug).
- **`UpdateModal`** era el único modal sin `max-h-[85vh]` + scroll interno: en
  viewports chicos el contenido podía quedar fuera de pantalla. Alineado con sus
  hermanos (`5f5a89e`; dist reconstruido, lint 0 warnings).
- **Estáticos**: `/`, el JS y el CSS del build nuevo responden 200.
- Nada de esto toca BDS ni el mundo: la GUI estaba con el servidor apagado y
  solo se usaron endpoints de lectura.

## Verificación reproducida

```
ruff check .                    -> All checks passed
pytest -m "not e2e" (10x)       -> 702 passed en las 10
Hypothesis con base fresca      -> 702 passed
uvicorn real (:8125)            -> status 200; Origin externo 403;
                                   body inválido + Origin externo 403;
                                   comando sin Origin -> offline; sin huérfanos
eventos/wrappers/artefactos     -> 0 nuevos
```

Tag final: `final-2026-09-10` (apunta al cierre de esta ronda).
