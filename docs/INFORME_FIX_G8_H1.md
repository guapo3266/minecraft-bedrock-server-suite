# Informe de Fixes — G8 (apagado coordinado GUI/wrapper) y H1 (fiabilidad de backups)

**Fecha:** 2026-08-11
**Alcance:** `server_wrapper.py`, `server_gui_server.py`, `auto_backup.py`, `tests/test_review_hallazgos.py`, `tests/test_pbt_properties.py`
**Estado:** aplicados y verificados — suite completa: **115 passed, 1 skipped** (un fallo aislado fue un flake de timing de Hypothesis, `DeadlineExceeded`, confirmado en re-ejecución).

Este informe documenta cada fix: **qué** se arregló, **por qué**, **cómo** y **si es recomendable modificarlo** (qué valores son tunables y bajo qué condiciones). Los IDs G8/H1 no colisionan con la serie histórica (B01-B12, N1-N6, D1-D8, F1-F5, G1-G5, S1-S3).

---

## G8 — La GUI separa "BDS murió" de "wrapper terminó"

### Qué
`restart` y `update_bds` de la GUI esperaban `wrapper_exit_event` con un timeout único de **30s**, pero ese evento solo se marca cuando el **proceso del wrapper termina del todo** — y el wrapper no termina hasta completar el backup final de cierre (tope interno de 240s).

### Por qué (bug)
Con un mundo cuya compresión de cierre tarda >30s, el reinicio/actualización se abortaba **siempre** aunque el servidor ya se hubiera detenido correctamente. El mensaje de error ("El servidor no se detuvo en 30s") era además engañoso: el servidor sí se había detenido; lo que no había terminado era el backup final del wrapper.

### Cómo
- **`server_wrapper.py`** — el `finally` del arranque imprime el marcador `[Wrapper] BDS detenido. Iniciando limpieza final de cierre...` en el momento exacto en que BDS muere, **antes** del backup final.
- **`server_gui_server.py`**:
  - Nuevo evento `manager.server_stopped_event` (independiente de `wrapper_exit_event`): se limpia al spawnear/arrancar el wrapper, se marca al ver la línea del marcador y como respaldo en el `finally` del hilo.
  - `restart` y `update_bds` esperan ahora **dos fases**:
    - Fase 1: `server_stopped_event` con `SERVER_STOP_TIMEOUT_SEC` (BDS muerto, mundo quieto).
    - Fase 2: `wrapper_exit_event` con `WRAPPER_EXIT_TIMEOUT_SEC` (wrapper completo, backup final incluido). Necesaria para no lanzar un segundo wrapper/actualización mientras el anterior comprime el mismo mundo.
  - Mensajes de aborto honestos en cada fase.

### Tests
`tests/test_review_hallazgos.py` (sección G8): fase 1 aborta si BDS no muere; fase 2 espera al backup final y luego arranca; fase 2 aborta si el wrapper queda colgado; `update_bds` aborta sin tocar instalación si el wrapper sigue vivo.

### ¿Es recomendable modificarla?
**Sí, los timeouts son tunables** (constantes en `server_gui_server.py`):

| Constante | Valor | Cuándo tocarla |
|---|---|---|
| `SERVER_STOP_TIMEOUT_SEC` | 75 | Debe ser **mayor** que `BDS_STOP_TIMEOUT_SEC` del wrapper (60): el wrapper fuerza el kill y la GUI solo observa. Si tu mundo tarda mucho en guardar al cerrar, súbela; nunca la bajes por debajo del valor del wrapper |
| `WRAPPER_EXIT_TIMEOUT_SEC` | 450 | Presupuesto: 75 (BDS) + 135 (join del worker caliente) + 240 (backup final) + margen. Si cambias esos topes en el wrapper, recalcula esta |

La mecánica de dos eventos en sí (marcador + respaldo en `finally`) no debería tocarse: es lo que hace que el reinicio no dependa del tamaño del mundo.

---

## H1-1 — Un ZIP válido ya publicado ya no puede borrarse a sí mismo

### Qué
En `auto_backup.create_backup`, `success = True` estaba **después** de `os.path.getsize(...)` y del `print(...)` de éxito.

### Por qué (bug)
Si `getsize` o `print` lanzaban (p. ej. antivirus bloqueando el archivo recién escrito), el `finally` ejecutaba `os.remove(zip_filepath)` con `success=False` → se borraba un backup **íntegro ya publicado**. Era el único caso de pérdida de un backup válido (hallazgo 2 del informe `REVISION_WRAPPER_Y_AUTO_BACKUP.md`).

### Cómo
`success = True` se marca **inmediatamente después de `os.replace(tmp, zip)`** y antes de cualquier operación que pueda fallar. El `finally` solo limpia `.tmp` y, si hubo fallo antes de publicar, el zip parcial.

### Tests
`test_backup_publicado_no_se_borra_si_falla_getsize` (inyección de fallo: `getsize` lanza para `.zip`; el zip publicado sobrevive).

### ¿Es recomendable modificarla?
**No.** Es una línea de orden de sentencias; cualquier reordenamiento futuro que vuelva a poner `success = True` después de operaciones falibles reintroduce el bug. Si se añaden operaciones post-publicación, deben ir dentro de su propio `try/except` para que el fallo no derribe la semántica de "publicado".

---

## H1-2 — Rotación de backups marcados corruptos/excedidos

### Qué
`rotate_backups` excluía por completo de la rotación los archivos con marcador `_CORRUPTO`/`_EXCEDIDO`.

### Por qué (bug)
Esos archivos se acumulaban **para siempre** (fuga de disco indefinida): el marcado `_POSIBLEMENTE_CORRUPTO` del wrapper y `_EXCEDIDO` nunca se borraban ni competían por las capas de retención (hallazgo 4 de `REVISION_WRAPPER_Y_AUTO_BACKUP.md`).

### Cómo
Nueva **capa 3** en `rotate_backups`: los marcados no compiten por las capas recientes/diarias (seguían contaminando nada: siguen sin contarse), pero se conservan como evidencia `CORRUPT_BACKUP_RETENTION_DAYS` días y luego se rotan. Las fechas futuras (reloj desviado) se conservan igual que en la capa diaria.

### Tests
`test_rotate_corrupt_markers_politica_retencion` reescrito al nuevo contrato (evidencia reciente sobrevive, vieja rota, con reloj inyectable e idempotencia). **Nota:** el test antiguo documentaba el contrato previo ("nunca se eliminan"); si alguien revierte la política, debe revertir el test.

### ¿Es recomendable modificarla?
**Sí, la ventana es tunable** (`CORRUPT_BACKUP_RETENTION_DAYS = 7` en `auto_backup.py`). Es el único punto de decisión de producto del fix:
- Súbela si quieres más margen de forense ante corrupciones (cuesta disco: cada backup marcado sigue pesando lo mismo).
- Bájala si prefieres no conservar evidencia.
- No se recomienda volver a "nunca rotar": es la fuga de disco que este fix cierra.

---

## H1-3 — La ruta normal de `stop` ya tiene tope en el wrapper

### Qué
El loop principal del wrapper (`while server_process.poll() is None: sleep(0.5)`) esperaba a BDS **sin límite** en la ruta normal de apagado; solo la ruta Ctrl+C forzaba con `wait(15)` + `kill`.

### Por qué (bug)
Si BDS colgaba al recibir `stop`, el wrapper quedaba colgado **para siempre**: proceso filtrado, mundo bloqueado, y sin backup final de cierre (hallazgo 3 de `REVISION_WRAPPER_Y_AUTO_BACKUP.md`).

### Cómo
- Nueva constante `BDS_STOP_TIMEOUT_SEC = 60` y estado `shutdown_requested_at` (fijado bajo `state_lock` en `initiate_shutdown`, solo en la primera invocación).
- El loop principal rompe si `shutting_down` y venció el tope.
- El `finally` del arranque fuerza `kill()` + `wait()` **antes** del marcador G8 y del backup final: el backup de cierre siempre corre sobre un mundo quieto. Idempotente: si BDS ya cerró, `poll()` no es `None` y no se toca nada. La ruta Ctrl+C (15s + kill) sigue igual y ahora converge en el mismo `finally`.

### Tests
`test_stop_normal_tiene_tope_y_fuerza_terminacion` (a nivel fuente, mismo estilo que `test_run_backup_process_eliminado`: verifica que el tope, el estado y el kill en el `finally` existan).

### ¿Es recomendable modificarla?
**Sí, el tope es tunable** (`BDS_STOP_TIMEOUT_SEC = 60` en `server_wrapper.py`):
- Subirlo da más tiempo a BDS para guardar el mundo en apagados lentos (mundos enormes con guardado pesado); bajarlo corta antes servidores colgados.
- **Regla de oro**: debe ser **menor** que `SERVER_STOP_TIMEOUT_SEC` de la GUI (75), para que el wrapper resuelva (kill + marcador) antes de que la GUI abandone la fase 1.
- No se recomienda volver al bucle sin tope: es el cuelgue infinito que este fix cierra.

---

## H1-4 — Cierre de la carrera de doble arranque en `restart`

### Qué
`do_restart` (GUI) spawnaba el wrapper y lanzaba el hilo **sin** marcar `manager.is_running = True` bajo `op_lock`, a diferencia de `start`.

### Por qué (bug)
Dos clics simultáneos de "reiniciar" con el servidor apagado podían ver `is_running == False` en la ventana entre el spawn y el arranque del hilo, lanzando **dos wrappers** que comprimen/escriben el mismo mundo.

### Cómo
`manager.is_running = True` se asigna bajo `op_lock` justo tras `manager.wrapper_process = proc` (misma secuencia que `start`).

### Tests
`test_restart_doble_simultaneo_no_lanza_dos_wrappers` (dos POST concurrentes con `_spawn_wrapper_process` que duerme 50ms para ensanchar la ventana; se lanza exactamente un wrapper).

### ¿Es recomendable modificarla?
**No.** Es la misma convención que ya usaba `start`; quitar la línea reintroduce la carrera. Si algún día `restart` deja de esperar la fase 2, mantener igualmente este marcado bajo el lock.

---

## H1-5 — Mensaje de error honesto en la fase 1 del actualizador

### Qué
El mensaje de aborto de la fase 1 de `update_bds` afirmaba "el servidor quedó detenido" cuando en realidad la fase 1 venció con BDS posiblemente **todavía vivo** (contradicción con "El servidor no se detuvo").

### Cómo
El mensaje ahora dice "si el servidor quedó detenido, reinícialo con ▶ Iniciar" (solo la fase 2 garantiza que BDS ya está detenido).

### ¿Es recomendable modificarla?
**No.** Es texto; si se cambia el flujo, mantener la distinción: fase 1 = estado incierto, fase 2 = BDS detenido.

---

## Notas de verificación

1. **Mecánica G8 intacta**: el marcador se imprime en todas las rutas de cierre (normal, Ctrl+C, crash de BDS) porque vive en el `finally` del arranque del wrapper.
2. **No hay cambios de comportamiento en el camino feliz del wrapper**: BDS cerrando normalmente no alcanza ni el tope de stop ni el kill; el backup final corre igual.
3. **Flake conocido**: `test_rotate_old_survivors_bounded_by_recent_layer` puede fallar con `DeadlineExceeded` bajo carga de la máquina (Hypothesis mide 200ms por ejemplo); en aislamiento pasa. Si reaparece con frecuencia, considerar `@settings(deadline=None)` en ese test.
