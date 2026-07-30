# Notas de diseno del wrapper y sistema de backups

Este documento detalla los problemas de concurrencia, cuelgues I/O y errores lógicos descubiertos en las versiones anteriores del `server_wrapper.py`, así como los cambios aplicados para resolverlos.

---

## 1. Migración de `threading` a `multiprocessing` (Inmunidad a bloqueos de I/O)

### El Problema
Anteriormente, el proceso de copia y compresión ZIP se ejecutaba en un hilo secundario (`threading.Thread`). En Python, debido a la arquitectura del intérprete, si un hilo se bloquea en una operación de Entrada/Salida a nivel del sistema operativo (por ejemplo, un disco duro lento, una red caída o un antivirus bloqueando el archivo), **es imposible interrumpirlo o matarlo forzosamente**. El evento cooperativo `cancel_event` fallaba porque el hilo nunca llegaba a leerlo, provocando que todo el servidor y el script de cierre se quedaran colgados eternamente esperando a que terminara.

### La Solución
Se aisló el núcleo de compresión usando la librería `multiprocessing`. Ahora, el backup se lanza en un proceso del sistema operativo completamente independiente.
- Si el proceso se excede del tiempo máximo asignado (`WORKER_COMPRESSION_TIMEOUT_SEC = 120s`), el wrapper principal ejecuta un `process.kill()` (el equivalente a `TerminateProcess` en Windows), aniquilando el proceso defectuoso instantáneamente sin importar qué tan profundo estuviera atascado en el disco.

---

## 2. Implementación de un Lock IPC Real y Renovación ante Envenenamiento

### El Problema
Al usar `multiprocessing` en Windows (método `spawn`), el nuevo subproceso arranca un intérprete de Python en blanco e importa el módulo `auto_backup.py` desde cero. Esto provocaba que el `_backup_lock = threading.Lock()` se instanciara dos veces (uno en el padre, uno en el hijo), permitiendo que múltiples backups ocurrieran a la vez sobreescribiendo los archivos, ya que no compartían la exclusión mutua.

Además, si el wrapper aplicaba un `kill()` al proceso mientras éste tenía el lock adquirido, el semáforo del Sistema Operativo se quedaba "envenenado" (tomado), bloqueando el backup de cierre.

### La Solución
- **IPC Lock Inyectado:** Se instanció un `multiprocessing.Lock()` global en el proceso maestro (`backup_ipc_lock`), el cual es transmitido a los subprocesos a través de sus argumentos. Ahora, el sistema operativo garantiza exclusión mutua a lo largo de todos los procesos.
- **Renovación del Lock (Des-envenenamiento):** Si se detecta un proceso atascado y se le aplica `kill()`, el wrapper descarta la referencia al viejo lock envenenado y renueva la variable global creando un `multiprocessing.Lock()` nuevo. Esto garantiza que el siguiente backup pueda ejecutarse inmediatamente.

---

## 3. Desincronización de Carreras Críticas de Apagado (DRY y Timeouts)

### El Problema
El tiempo máximo de espera para un backup atascado era de 120s (`WORKER_COMPRESSION_TIMEOUT_SEC`), y el tiempo máximo que el hilo principal esperaba al cerrar el servidor era también de 120s (`WORKER_JOIN_ON_SHUTDOWN_SEC`). Si ambos ocurrían en simultáneo, dos rutas de código distintas intentaban matar el mismo proceso y renovar el mismo Lock IPC casi en el mismo milisegundo, provocando una peligrosa carrera de datos.

### La Solución
- Se elevó la tolerancia del cierre maestro a `135s` (`WORKER_JOIN_ON_SHUTDOWN_SEC`).
- Esto asegura estadísticamente (y se comprobó con fuzzer tests de 25 iteraciones) que el propio worker siempre procesará su suicidio primero (a los 120s), dejando a la rama de apagado maestro como una red de seguridad que solo actuará en situaciones de colapso extremo de hilos.
- Se centralizó toda la lógica de aniquilación y renovación en una única función Thread-Safe: `_force_kill_compress_process(proc)`.

---

## 4. Parseo Indestructible del Registro (Bug del Log Prefix)

### El Problema
Cuando el protocolo Bedrock nativo reporta una lista de archivos, a veces intercala líneas con corchetes de tiempo (`[2026-07-21 13:00 INFO] Quit correctly`). La lógica original usaba un simple `if not line.startswith("["):` para detectar archivos, lo cual era frágil y causaba la omisión de listas válidas de archivos o la aceptación de texto basura.

### La Solución
Se reemplazó la lógica frágil por una **Expresión Regular (Regex)**: `re.sub(r'^\[.*?\]\s*', '', line)`.
Esta directriz "lava" cualquier prefijo temporal del motor de Bedrock antes de evaluar el resto de la cadena. Si el texto limpio contiene un archivo y un peso (`ruta:bytes`), se guarda; si es texto basura ("Quit correctly"), se descarta de forma segura.

---

## 5. Integridad Transaccional de Banderas Asíncronas

### El Problema
La bandera `expecting_list_names` (usada para capturar quién está en línea tras un comando `list`) era leída por el hilo interceptor de Consola, pero podía ser modificada asíncronamente por el planificador (Scheduler), lo que podía resultar en lecturas inconsistentes (condición de carrera de memoria).

### La Solución
Se protegió la lectura mediante una evaluación de ámbito atómico utilizando el candado principal:
```python
with state_lock:
    is_expecting_list = expecting_list_names
```

---

## 6. Dinamismo de Rutas y Limpieza de Huérfanos

### El Problema
1. La ruta de extracción del archivo ZIP asimilaba por fuerza bruta la existencia de una carpeta llamada `Bedrock level`, lo que colapsaba el sistema si el usuario cambiaba el nombre del mundo.
2. Tras matar un proceso de compresión a la fuerza, los archivos ZIP parciales `.tmp` quedaban atascando el disco.

### La Solución
- **Dinamismo `server.properties`**: `auto_backup.py` ahora implementa un analizador que lee la configuración nativa del servidor (`level-name=...`) y resuelve las rutas dinámicamente.
- **Barredora Segura de TMP**: `create_backup` escanea el disco y elimina archivos `.tmp` incompletos. **Nota de seguridad:** Esta limpieza ocurre estrictamente _después_ de haber adquirido el `backup_ipc_lock`, asegurando matemáticamente que el `.tmp` pertenece a un proceso muerto y no al proceso de un backup legítimo que esté corriendo simultáneamente.

---

