# Informe: el backup en caliente nunca completaba (worker colgado 50-120 s+)

**Fecha:** 2026-08-02
**Alcance:** `server_wrapper.py`, `backup_worker.py` (nuevo), `server_gui_server.py`, `auto_backup.py` (sin cambios)
**Estado:** RESUELTO y verificado en vivo. Commit `6df6830` (repo `minecraft-bedrock-server-suite`).

---

## 1. Resumen ejecutivo

El **backup en caliente** (hot backup) del wrapper de Minecraft Bedrock — el que
usa los comandos nativos `save hold` / `save query` / `save resume` para no
molestar a los jugadores — **nunca llegaba a comprimir**: el proceso hijo que
hacía la compresión se colgaba entre 50 y 120+ segundos en el arranque
(bootstrap), y el timeout de seguridad de 120 s (`WORKER_COMPRESSION_TIMEOUT_SEC`)
lo abortaba siempre. El backup "caliente" era, en la práctica, un no-op.

La causa: la maquinaria de **`multiprocessing.spawn`** (el pipe de arranque +
duplicación de handles del proceso padre) se colgaba de forma intermitente
cuando el padre era el wrapper con BDS corriendo. La compresión en sí era
rápida (**1.3 s** para un mundo de 50 MB); el problema era el arranque del
proceso hijo, no la compresión.

El fix: reemplazar el spawn por **`subprocess.Popen`** de un script dedicado
(`backup_worker.py`), con señal de cancelación por archivo marcador
(`_FileCancelEvent`). Resultado: el backup caliente manual completo pasa de
"nunca" a **~9 s desde el clic hasta el ZIP publicado** (compresión real: 2 s).

---

## 2. Síntomas

1. Al disparar un backup caliente, el wrapper imprimía
   `[Worker] Iniciando compresión de archivos en proceso separado...` y luego
   **nada durante 50-120 s**.
2. A los 120 s aparecía `[Worker] [WARN] Timeout de compresion (120s).` y el
   backup se abortaba sin producir ZIP.
3. El backup funcionaba a veces (una sola vez llegó a completarse en ~95 s),
   pero la mayoría de las veces fallaba por timeout.
4. Los backups en frío (`inicio` / `cierre`) eran rápidos (~1-3 s) porque
   comprimen **en el proceso del wrapper**, sin spawn.

---

## 3. Contexto: cómo funciona el backup caliente

1. El scheduler del wrapper entra en ciclo (automático cada 30 min con
   jugadores online, o manual con el comando `backup`).
2. Envía `save hold` → BDS congela las escrituras → responde
   `Data saved. Files are now ready to be copied.` + lista de archivos con
   tamaños (snapshot).
3. Tras 5 s de silencio, el wrapper despacha el **worker**:
   `execute_backup_worker(snapshot, cancel_event)`.
4. El worker lanzaba un **hijo de `multiprocessing` (spawn)** que ejecutaba
   `_run_backup_process` → `auto_backup.create_backup(...)` (modo snapshot:
   lee cada archivo hasta el byte exacto del snapshot y comprime a ZIP).
5. El ZIP se publica con `os.replace` y el wrapper envía `save resume`.

---

## 4. La investigación: qué se descartó y con qué evidencia

El colgado era intermitente (50 s, 95 s, 120+ s), lo que obligó a aislarlo
experimento por experimento. Todo esto se hizo sobre **copias de diagnóstico**
(`server_wrapper_diag.py`, minis) — el `server_wrapper.py` de producción no se
tocó hasta tener la causa confirmada.

### 4.1. Descartado: la compresión en sí

| Prueba | Resultado |
|---|---|
| `create_backup` modo tradicional en proceso, mundo real de 50 MB | **1.3 s** |
| `create_backup` modo snapshot en proceso, mundo real | **1.3-1.4 s** |
| Mismo trabajo en un hijo spawn desde un script suelto | **1.4 s** |

La compresión de 50 MB tarda ~1.3 s. El modo snapshot (lectura por archivo +
`writestr`) no era el problema.

### 4.2. Descartado: los argumentos del spawn (snapshot, Event, Lock, Queue)

- Hijo spawn con snapshot de 58 tuplas desde un script suelto: **0.1 s**.
- Hijo spawn con `multiprocessing.Lock()` a nivel de módulo: **0.1 s**.
- Hijo spawn con `multiprocessing.Event` pasada como arg: llega **sin marcar**
  y arranca en **0.1 s**.
- Mismo entorno de lanzamiento que el wrapper (stdin=PIPE sin leer,
  stdout=archivo, `-u`): **0.1 s**.
- Mini-wrapper en TESTTEST con un hijo proceso dummy antes del spawn: **0.1 s**.

### 4.3. Evidencia de que el colgado estaba en el bootstrap del hijo

1. **`py-spy dump`** sobre el hijo durante el colgado:
   `python -c "from multiprocessing.spawn import spawn_main; ..."` con el hilo
   principal en espera nativa (sin frames de Python). El hijo **nunca llegó a
   ejecutar el target**.
2. **`WaitReason` de Windows** (`Get-CimInstance Win32_Thread`): 4 hilos en
   `EventPairLow` — espera en primitivas de sincronización (lectura de pipe).
3. **`faulthandler.dump_traceback_later`** registrado a nivel de módulo del
   wrapper (el hijo lo re-importa como `__mp_main__`): el hijo no volcó ningún
   stack — el colgado era **anterior** a la ejecución del código del módulo.
4. **Marcadores en el hijo** (diag): el `start()` del padre tardaba **0.0 s**
   (los datos del spawn SÍ se escribían), pero el target del hijo arrancaba
   **50 s después**. El colgado estaba entre la escritura del padre y el
   `run()` del hijo: dentro de `spawn_main` → `pickle.load` → `prepare`.
5. **Primitivas Win32 medidas dentro del wrapper**: `OpenProcess`,
   `CreatePipe`, `DuplicateHandle`, `WriteFile` → todas **0.000 s**. No era un
   hook lento de las syscalls.

### 4.4. Descartado: el entorno del directorio y el contenido del módulo

- Mini-wrapper de 15 líneas en TESTTEST: **0.1 s** (el directorio no importa).
- El wrapper completo incluso con `import auto_backup` y el
  `multiprocessing.Lock()` de módulo **eliminados**: seguía colgando ~50 s.
  (Nota: dos intentos intermedios dieron falsos "colgados" porque un error mío
  dejó una llamada a una función inexistente — el wrapper crasheaba con
  `NameError` al arrancar, no se colgaba. Se detectó al revisar la secuencia.)

### 4.5. La prueba que lo confirmó

En el wrapper real, sustituir el `ctx.Process(...).start()` por
`subprocess.Popen` del worker:

```
Popen tardo 0.0s
SUBPROC worker start pid=27040        <- 1 s después
SUBPROC create_backup en 1.3s -> True  <- ¡compresión REAL de 50 MB en 1.3 s!
```

**Conclusión:** la maquinaria de `multiprocessing.spawn` (pipe de bootstrap +
`OpenProcess`/`DuplicateHandle` del padre + lectura del pipe en el hijo) se
colgaba de forma intermitente cuando el padre era el wrapper con BDS corriendo.
El mecanismo exacto a nivel de syscall no se pudo observar directamente (el
hijo no ejecuta código nuestro hasta después del colgado), pero quedó
demostrado que **cualquier** hijo spawn del wrapper se colgaba (~50-120 s+),
mientras que **cualquier** hijo `subprocess` arrancaba al instante.

---

## 5. La causa raíz (en una frase)

> El worker de compresión usaba `multiprocessing.spawn`, y el bootstrap de
> spawn se colgaba 50-120 s+ cuando el padre era el wrapper con BDS en marcha
> (hijo bloqueado en la lectura del pipe de arranque de spawn). La compresión
> nunca llegaba a ejecutarse y el timeout de 120 s abortaba el backup.

No era: la compresión, el modo snapshot, los argumentos del spawn, el
directorio, las primitivas Win32, el contenido del módulo, ni un bug del
código de backup. Era el **mecanismo de arranque del proceso hijo**.

---

## 6. El fix

### 6.1. `backup_worker.py` (nuevo)

Script independiente ejecutado con `subprocess.Popen`:

```python
python backup_worker.py <snapshot.pkl> <cancel_marker> <result.pkl>
```

- Lee el snapshot (pickle), ejecuta `auto_backup.create_backup` en modo
  snapshot, escribe el resultado (pickle).
- Cancelación cooperativa: si el archivo marcador existe, `create_backup`
  aborta (misma semántica que el `cancel_event` de multiprocessing).
- No comparte locks con el wrapper: usa el lock interno de `auto_backup`
  (el wrapper garantiza la exclusión con `backup_in_progress` + join antes
  del backup de cierre).

### 6.2. `server_wrapper.py` — `execute_backup_worker`

- `ctx.Process` + `ctx.Queue` → `subprocess.Popen([python, backup_worker.py, ...])`.
- Snapshot → pickle temporal; resultado → pickle temporal (con limpieza en
  todos los caminos: éxito, timeout, excepción).
- Shims `is_alive` / `join` sobre el `Popen` para no tocar
  `_force_kill_compress_process` ni el resto del flujo.

### 6.3. `server_wrapper.py` — `_FileCancelEvent`

```python
class _FileCancelEvent:
    def __init__(self, path): ...
    def is_set(self): return os.path.exists(self.path)
    def set(self): ...      # crea el archivo marcador
    def clear(self): ...
```

API idéntica a `multiprocessing.Event`. Los **3 puntos de cancelación
existentes** (apagado elegante, timeout del worker, apagado forzado) no
cambiaron ni una línea: siguen llamando a `.set()`, que ahora escribe un
archivo que el worker (proceso distinto) puede ver.

---

## 7. Verificación (en vivo, wrapper real)

| Escenario | Antes | Después |
|---|---|---|
| Backup manual → ZIP periodico | Nunca completaba (timeout 120 s) | **ZIP completo en ~9 s** (50.31 MB) |
| Compresión real de 50 MB | No ejecutada (bootstrap colgado) | **1.3-2.0 s** |
| Stop a mitad de compresión | Cancelaba el ciclo sin ZIP | Worker aborta cooperativo por marcador, `.tmp` limpiado, backup de cierre OK, exit 0 |
| BDS matado a mitad de compresión | Worker colgado, backup perdido | **Worker completa el backup (50.31 MB)**, aviso de cierre anómalo, cierre OK, exit 0 |
| Guard anti doble backup | Funcionaba | Sigue funcionando (misma máquina de estados) |

- **51 tests** pasan (incluye 13 nuevos: 9 de inyección de fallos + 4 del
  disparo manual).
- Mundo verificado sano tras los ensayos (level.dat, db/CURRENT, sin
  `.tmp`/LOCK sueltos).

---

## 8. Hallazgos relacionados de la misma sesión

1. **CPU siempre 0 % en la GUI** (`server_gui_server.py`): `cpu_percent(interval=None)`
   sobre un objeto `psutil.Process` recién creado en cada muestra devuelve
   siempre 0 (sin baseline). Fix: caché de objetos por PID. Además las
   métricas ahora suman **todo el árbol**: GUI + wrapper + BDS.
2. **"Forzar Backup" caliente de la GUI era un no-op**: enviaba `save hold`
   pero el wrapper solo iniciaba ciclos calientes por su cuenta (jugadores
   online + intervalo). Fix: comando `backup` por stdin que replica el arranque
   del ciclo del scheduler.
3. **`tests/test_wrapper_logic.py`** es script-style: ejecuta `run_case()` al
   importarse y deja estado sucio (`backup_in_progress=True`). Los tests
   nuevos se endurecieron contra eso; migrarlo a funciones `test_*` queda
   pendiente (cosmético).

---

## 9. Lecciones

- Un backup que "tarda 90 s" en un mundo de 50 MB no es un backup lento: es un
  proceso que **nunca empezó a trabajar**. Medir CPU del hijo (0 %) lo delata
  al instante.
- `multiprocessing.spawn` en Windows es frágil como mecanismo de "proceso
  aislado" dentro de un árbol con procesos de juegos: `subprocess` es más
  simple, predecible y no tiene pipe de bootstrap.
- La señal de cancelación entre procesos no necesita semáforos compartidos:
  un archivo marcador es suficiente y funciona entre cualquier tipo de hijo.
- Instrumentar con marcadores a archivo (no a stdout) es lo único fiable en
  procesos cuyo stderr puede ser inválido.
