# Informe — esperas de cierre vs. timeouts de backup escalados (2026-10-19)

## Origen

La ronda 2026-09-25 (H1) hizo que el timeout del worker de compresión y el del
backup final escalaran con el tamaño del mundo
(`wrapper_state.scaled_backup_timeout_sec`: piso histórico + 120 s por GB sin
comprimir, tope 3600 s). Al documentar la arquitectura (2026-10-19) quedaron
dos esperas que seguían calculadas con los valores antiguos. La revisión leyó el
flujo real y **confirmó ambas**.

## Diagnóstico

### 1. Join de cierre del worker caliente (`WORKER_JOIN_ON_SHUTDOWN_SEC = 135`)

- Quién espera: el `finally` de `server_wrapper.py` (`current_worker.join(...)`),
  tras la muerte de BDS y antes del backup final.
- Intención original (`DOCUMENTACION_ARQUITECTURA_V5.md` §3): 135 = 120 s del
  worker + 15 s de margen, para que **el worker se mate a sí mismo primero**
  (CASO A de `execute_backup_worker`) y el cierre maestro quede como red de
  seguridad. Si ambos actuaban a la vez, dos rutas mataban el mismo proceso y
  renovaban el mismo lock.
- Con el timeout escalado esa garantía se rompía a partir de 128 MiB de
  snapshot: p. ej. 1 GB → el worker tenía 240 s pero el cierre lo mataba a los
  135 s (kill, cancelación del backup y `save resume`), descartando una
  compresión legítima.
- Efecto: no hay pérdida de datos (el backup final corre después sobre el mundo
  quieto), pero se rompe el invariante de diseño y se desperdicia el trabajo.

### 2. Fase 2 de la GUI (`WRAPPER_EXIT_TIMEOUT_SEC = 450`)

- Quién espera: `lifecycle.restart_wrapper` (reinicio) y `lifecycle.stop_and_wait`,
  usado por la actualización/rollback de BDS (`routers/actions.py`) y por el
  actualizador de la suite (`services/suite_update.py`). Espera
  `manager.wrapper_exit_event`, que solo llega cuando el wrapper termina, es
  decir, **después del backup final de cierre**.
- Presupuesto original: 135 (join) + 240 (backup final) + 75 de holgura. El
  backup final usa `scaled_backup_timeout_sec(estimate_backup_total_bytes(), 240)`
  y puede llegar a 3600 s.
- Al vencer: no mata nada. `restart_wrapper` registra «El wrapper no terminó en
  450s … Reinicio cancelado; inicia el servidor manualmente» y no relanza;
  `stop_and_wait` devuelve `False` y el llamador **no toca la instalación**
  (la actualización de BDS/rollback/suite se cancela sin haber modificado
  archivos). El wrapper sigue vivo terminando su backup, el `op_lock` se libera
  y un `start` inmediato devuelve `already_running`. El actualizador de suite
  lanza «No se pudo detener Minecraft y su wrapper» (sin llegar a
  `final_backup_finished`, que solo se comprueba después).
- Es, por tanto, un **fallo seguro pero espurio**: la operación se cancela con
  el wrapper todavía dentro de sus propios plazos, y el usuario queda con el
  servidor detenido y una operación rechazada justo en los mundos grandes para
  los que se introdujo la escala.

### Escenarios (peor caso del wrapper tras la muerte de BDS)

`join` = timeout escalado del worker + 15 s (nuevo; antes fijo 135 s);
`final` = backup final escalado; «GUI nueva» = 450 + `shutdown_extra_sec`.

| Mundo | Worker caliente | Join nuevo | Backup final | Peor caso antes (135+final) | Peor caso ahora (join+final) | GUI antes | GUI ahora |
|---|---|---|---|---|---|---|---|
| 0,1 GB | 131 s | 146 s | 251 s | 386 s | 397 s | 450 s | 472 s |
| 0,5 GB | 180 s | 195 s | 300 s | 435 s | 495 s | 450 s | 570 s |
| 1 GB | 240 s | 255 s | 360 s | 495 s | 615 s | 450 s | 690 s |
| 2 GB | 360 s | 375 s | 480 s | 615 s | 855 s | 450 s | 930 s |
| 4 GB | 600 s | 615 s | 720 s | 855 s | 1335 s | 450 s | 1410 s |
| 30 GB | 3600 s | 3615 s | 3600 s | 3735 s | 7215 s | 450 s | 7290 s |

Con el modelo anterior, la GUI abandonaba desde ~0,63 GB si había un backup
caliente en curso al detener (135 + 240 + 120·GB > 450) y desde ~1,75 GB sin él
(final de 240 + 120·GB > 450). Son esperas que solo se agotan si el wrapper
realmente tarda: con un wrapper sano el evento llega antes y la espera termina
en cuanto llega.

## Interacción con `final_backup_finished` y el actualizador de suite

- `final_backup_finished` lo emite `execute_final_backup` en su `finally`. Si el
  join de `final_timeout` vence, el wrapper sale con el hilo daemon aún vivo y
  **no se emite** el evento (el `.tmp` se limpia solo): el actualizador lo
  detecta (`final_backup_result is None` tras 5 s) y no reemplaza código. Este
  comportamiento no cambia.
- El cambio solo evita que la GUI se rinda *antes* de que el wrapper haya
  terminado o agotado su propio plazo. No sustituye `final_backup_finished`
  por otra señal ni relaja ninguna comprobación del actualizador.

## Arreglo

Mínimo y con una sola fuente de la escala (`wrapper_state.py`):

- `execute_backup_worker` calcula su timeout efectivo **antes del `Popen`** y lo
  publica en `wstate.active_worker_timeout_sec` (bajo `state_lock`); lo limpia
  en su `finally`.
- El cierre del wrapper hace `join(wstate.worker_join_timeout_sec(timeout))` =
  timeout propio + `WORKER_JOIN_MARGIN_SEC` (15 s), con 135 s como piso. Se
  restituye el invariante «el worker se suicida primero» para cualquier tamaño.
- `wstate.shutdown_extra_sec(bytes)` = lo que el tamaño añade, sobre los pisos,
  al join y al backup final. `lifecycle.wrapper_exit_timeout_sec()` suma eso al
  piso `config.WRAPPER_EXIT_TIMEOUT_SEC` (450, intacto) usando
  `auto_backup.estimate_backup_total_bytes()`; `restart_wrapper` y
  `stop_and_wait` la usan y el mensaje de aborto informa el tope real. Si la
  estimación falla se queda el piso.
- No se bajó ningún piso (60/75/120/135/240/450) ni se añadieron límites fijos
  nuevos: la jerarquía BDS 60 < stop GUI 75 < espera del wrapper se conserva y
  la espera del wrapper ahora cubre su peor caso real.

Coste: con un wrapper atascado (no con uno sano) la GUI espera más antes de
rendirse: hasta ~2 h en el peor caso extremo (30 GB o más), que es lo que
el wrapper puede tardar dentro de sus topes. Mientras tanto la operación
(`update_in_progress`, `op_lock`) sigue marcada como en curso, que es lo
correcto porque el wrapper sigue comprimiendo el mismo mundo.

## Tests

`tests/test_timeouts_cierre.py` (23): jerarquía y pisos intactos; escala del
join y de `shutdown_extra_sec` (valores concretos y tope); propiedades
(Hypothesis) «el worker se suicida antes que el cierre maestro» y «la espera de
la GUI cubre el peor caso del wrapper para cualquier tamaño» y monotonía; los
tamaños donde fallaba el tope fijo; `wrapper_exit_timeout_sec`; que
`stop_and_wait` y `restart_wrapper` pasan el tope escalado y lo informan;
publicación y limpieza de `active_worker_timeout_sec` (incluida la ruta de
`Popen` fallido); y anti-drift textual (ninguna espera de fase 2 lee el piso
suelto; el `finally` del wrapper usa el join escalado). `tests/conftest.py`
fija `lifecycle._estimate_world_bytes` en 0 con un fixture de sesión para que los
tests existentes de restart/stop (que bajan el piso a fracciones de segundo) no
midan el `worlds/` real.

## Fuera de alcance / pendiente

- No se probó con BDS real ni con un mundo de GB: la verificación es por tests
  deterministas sobre las funciones de escala y las esperas (sin arrancar BDS).
- La estimación de la GUI (`estimate_backup_total_bytes`) recorre el mundo una
  vez al empezar la fase 2; en mundos con decenas de miles de archivos es una
  caminata de disco puntual, igual que la que ya hace el wrapper.
