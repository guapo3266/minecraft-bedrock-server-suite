# Informe: Correcciones de revisión R2 (2026-08-12) — timeout de compresión, `players_online` y stdin de la GUI

**Fecha:** 2026-08-12
**Alcance:** revisión de código + correcciones en TESTTEST (dev) — sincronizado a Servidor de Guapo (PROD) y a la suite
**Estado:** CORREGIDO — suite completa 146 passed, 1 skipped, 2 e2e deselected

---

## 1. Resumen ejecutivo

Revisión del backend de la GUI (`server_gui_server.py`) y del wrapper (`server_wrapper.py`)
que encontró **1 defecto grave** y **2 races de concurrencia menores**:

| # | Severidad | Hallazgo | Archivo |
|---|-----------|----------|---------|
| 1 | ALTA | El timeout de compresión (CASO A) era **código muerto**: el proceso huérfano retenía el lock de backups | `server_wrapper.py` |
| 2 | BAJA | `players_online` se mutaba sin lock mientras el event loop lo iteraba | `server_gui_server.py` |
| 3 | BAJA | Escrituras al stdin del wrapper desde varios hilos sin exclusión mutua | `server_gui_server.py` |

## 2. Hallazgo 1 (ALTO): timeout de compresión inalcanzable

### Qué pasaba

El worker de compresión lanza `backup_worker.py` con `subprocess.Popen` y luego le
"injerta" una API parecida a `multiprocessing.Process` para compatibilidad con el
código existente:

```python
# ANTES (server_wrapper.py:287-288)
comp_proc.is_alive = lambda: comp_proc.poll() is None
comp_proc.join = lambda timeout=None: comp_proc.wait(timeout=timeout)
```

El problema: **`Popen.wait(timeout=N)` LANZA `subprocess.TimeoutExpired`** al vencer,
mientras que **`Process.join(timeout=N)` devuelve `None`**. Con el shim, la llamada
`comp_proc.join(timeout=WORKER_COMPRESSION_TIMEOUT_SEC)` lanzaba la excepción, que caía
en el `except Exception` genérico del worker: ese handler **no mata el proceso** — solo
resetea estado y pone `active_compress_process = None`, **huerfanando** al proceso vivo.

### Consecuencias

- El huérfano seguía comprimiendo, reteniendo `auto_backup._backup_lock`.
- **Todos los backups posteriores fallaban** silenciosamente hasta que el huérfano
  terminara solo (o nunca, si colgaba por un archivo bloqueado).
- La limpieza de `.tmp` huérfanos de `_force_kill_compress_process` era inalcanzable
  desde todos sus call sites.
- El zip resultante podía quedar inconsistente sin marcarse como corrupto.

### Cuándo se dispara

Solo si la compresión supera los **120 s** (`WORKER_COMPRESSION_TIMEOUT_SEC`): mundos
grandes, disco lento o antivirus escaneando.

### Fix

```python
# AHORA (server_wrapper.py:288-299)
def _join(timeout=None):
    try:
        comp_proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        pass
comp_proc.join = _join
```

Con esto el CASO A vuelve a ser alcanzable: mata el proceso (`_force_kill_compress_process`),
limpia `.tmp`, reemplaza el lock IPC y reanuda escrituras (`save resume`).

## 3. Hallazgo 2 (BAJO): `players_online` sin lock

El hilo del wrapper (`run_wrapper_thread`) hacía `add`/`discard`/`clear` sobre
`manager.players_online` **sin** `manager.lock`, mientras el event loop leía
`list(players_online)` en `update_status()`, `/api/status` y el init del WebSocket.
Iterar un `set` mientras otro hilo lo muta puede lanzar
`RuntimeError: Set changed size during iteration` → 500 intermitentes o desconexión
del WS. Probabilidad baja (ventana de ~microsegundos), pero real.

### Fix

- Mutaciones (`server_gui_server.py:406, 417, 459`) bajo `with manager.lock:`.
- Lecturas (`update_status` :288, `/api/status` :524-525, init WS :1408-1410) copian
  la lista bajo el mismo lock (mismo patrón que ya usaba `log_history`).

## 4. Hallazgo 3 (BAJO): stdin del wrapper sin exclusión mutua

`TextIOWrapper` no es thread-safe. Seis sitios escriben a `wrapper_process.stdin`
desde hilos distintos: `/api/command` (:556), WebSocket (:1435) y las acciones
stop (:732), restart (:745), backup (:861) y update_bds (:891). Escrituras
concurrentes pueden entremezclarse y mandar una línea corrupta al servidor.

### Fix

Nuevo `manager.stdin_lock` (`server_gui_server.py:271`, espejo del `stdin_lock` que el
wrapper ya tenía) y los 6 sitios de escritura envuelven `write`+`flush`. Sin bloqueo
anidado: nunca se adquiere `manager.lock` y `stdin_lock` en orden cruzado.

## 5. Verificación

- Tests de regresión nuevos en `tests/test_review_hallazgos.py` (sección
  "Ronda de revision 2026-08-12"):
  - `test_worker_timeout_compresion_mata_proceso_y_libera_estado` — conductual: Popen
    falso que simula `TimeoutExpired`; verifica que el CASO A mata el proceso, limpia
    el `.tmp` y resetea estado. **Falla con el código anterior** (regresión hacia la corrección).
  - `test_gui_players_online_bajo_manager_lock` y `test_gui_stdin_bajo_stdin_lock` —
    estáticos (patrón de la suite).
- Suite completa: **146 passed, 1 skipped, 2 e2e deselected** (antes: 143 + 1 + 2).

## 6. ¿Es recomendable tocar este código?

**`server_wrapper.py` (sección del worker de compresión, líneas ~255-434): SÍ, con
mucha cautela.** Es el código más crítico del proyecto:

- **Es seguro tocarlo** cuando el cambio es mínimo y tiene test de regresión que
  falle con el comportamiento anterior (como este). El shim `_join` es la solución
  más pequeña posible: solo normaliza la semántica de una API ajena.
- **NO tocar sin test**: cualquier cambio en este flujo que no venga acompañado de
  un test conductual corre el riesgo de volver a romper los backups en caliente
  (el historial del repo tiene 3 regresiones de este estilo: G1/G2/G8/H3).
- Los timeout (120 s compresión / 60 s BDS / 240 s backup final) **no deben bajarse**
  a la ligera: están calibrados contra mundos grandes y discos lentos.

**`server_gui_server.py` (locks de concurrencia): es seguro tocarlo**, son patrones
estándar de `threading.Lock` espejo del wrapper. Reglas:

- Mantener el orden de adquisición simple (nunca `manager.lock` dentro de
  `stdin_lock` ni al revés anidados).
- No quitar los locks "para simplificar": la ventana de carrera es pequeña pero
  producía errores reales.

## 7. Archivos tocados

| Archivo | Cambio |
|---------|--------|
| `server_wrapper.py` | Shim `_join` con `except TimeoutExpired` (líneas 288-299) |
| `server_gui_server.py` | `stdin_lock` + locks en `players_online` y 6 escrituras a stdin |
| `tests/test_review_hallazgos.py` | 3 tests de regresión nuevos |
| `docs/INFORME_REVIEW_R2_2026-08-12.md` | Este informe |
