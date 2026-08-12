# Informe: Asistente de configuración inicial (First-Run Setup Wizard)

**Fecha:** 2026-08-12
**Alcance:** nueva funcionalidad en TESTTEST (dev) — backend + frontend — sincronizada a Servidor de Guapo (PROD) y a la suite
**Estado:** IMPLEMENTADO — suite completa 159 passed, 1 skipped, 2 e2e deselected; `npm run lint` 0 errores; `npm run build` OK

---

## 1. Resumen ejecutivo

La GUI ahora detecta **instalaciones nuevas** y muestra un asistente de 3 pasos en vez
del dashboard: (1) configuración esencial, (2) instalación del BDS oficial si falta,
(3) finalizar. Las instalaciones ya usadas (BDS presente + mundo existente) **no ven el
wizard** — Servidor de Guapo queda auto-marcado por su mundo. Al terminar, el wizard
**no arranca el servidor**: el usuario lo hace con ▶ Iniciar Servidor.

## 2. Detección de primer arranque

- Marcador: `data/setup_done.json`, escrito solo al completar el wizard.
- `required = NOT marcador AND NOT (bedrock_server.exe Y worlds/*/level.dat)`.
- El mundo nace en el primer boot de BDS: un BDS recién extraído **sí** ve el wizard;
  una instalación que ya arrancó **no** (aunque no tenga marcador, p. ej. tras un sync).
- El marcador se excluye de los syncs y está en `.gitignore` de la suite (nunca viaja
  entre instalaciones).

## 3. Backend (`server_gui_server.py`)

| Endpoint | Comportamiento |
|---|---|
| `GET /api/setup_status` | `{required, bds_installed}` (solo loopback) |
| `POST /api/setup/install_bds` | 409 si el servidor corre; `busy` con `op_lock` ocupado; corre `_download_and_install_bds(tag="[Setup]")` en hilo con progreso por logs |
| `POST /api/setup/complete` | 409 sin BDS instalado; escribe el marcador |

**Refactor clave**: el tramo "descargar (tope 400 MB) → staging anti zip-slip →
`_resolve_update_root` → `_apply_staged_update` (rollback + manifiesto)" se extrajo de
`do_update` a `_download_and_install_bds(tag=...)`, **compartido** por update_bds y el
setup. Los mensajes de log conservan sus textos exactos (el e2e del update los espera).
Sin flag global de "instalando": el wizard hace tracking con su propio `await` + logs.

## 4. Frontend (`gui_frontend/src/`)

- `components/reactbits/Stepper.jsx` + `Stepper.css`: vendored de React Bits,
  **morado `#5227FF` original**. Adaptaciones: import de `framer-motion` (ya instalado;
  `motion/react` es la misma API, se evita una dependencia duplicada) y prop nueva
  `completeButtonText` para el bilingüe.
- `propsFields.js`: `FIELDS` de server.properties en una sola fuente (lo usan
  PropsModal y el wizard; claves validadas en `PROPS_FIELDS` del backend).
- `components/SetupWizard.jsx`: 3 `Step`s —
  1. **Configuración**: idioma ES/EN + nombre/modo/dificultad/puerto/máx. jugadores →
     `POST /api/server_properties`. "Continuar" deshabilitado hasta guardar.
  2. **Instalar BDS** (solo si falta): `POST /api/setup/install_bds` con mini-consola
     de progreso (logs `[Setup]` del WebSocket). Indicadores de paso bloqueados durante
     la instalación; el avance se habilita al confirmar el log de éxito. Fallo → mensaje
     + reintento (sin red no cuelga).
  3. **Finalizar**: `onFinalStepCompleted` → `POST /api/setup/complete`; si falla, el
     Stepper se reinicia al paso 1 (`key={attempt}`).
- `App.jsx`: fetch de `/api/setup_status` al montar; `required` → wizard en vez del
  dashboard (el WebSocket sigue vivo para el progreso). Sin botón "Omitir".
- `i18n.jsx`: claves ES/EN del wizard (`setup*`).

## 5. Verificación

- `tests/test_setup_initial.py` (13 tests): detección (nueva/usada/marcada/BDS-sin-mundo),
  guards 409/`busy`, pipeline compartido (éxito con apply + limpieza, sin red, tope
  400 MB), complete (escribe marcador, 409 sin BDS).
- Suites afectadas por el refactor re-corridas: fault-injection, backup_fixes,
  review_hallazgos, gui_server_properties, gui_new_features → 105 passed.
- Smoke en TESTTEST real: `GET /api/setup_status` → `{required: false, bds_installed: true}`.
- `npm run lint`: 0 errores (12 warnings pre-existentes en otros componentes).
- `npm run build`: OK (warning de chunk >500 kB pre-existente).

## 6. Notas de despliegue

- La GUI sirve `gui_frontend/dist`: **obligatorio** rebuild + sync del `dist/` (~95 MB)
  al desplegar; sin ello la GUI muestra el frontend anterior.
- El marcador NO se sincroniza: en la suite (clon fresco, sin mundo) el wizard aparece
  en su primer arranque; en Servidor de Guapo (mundo existente) nunca.
