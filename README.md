# Minecraft Bedrock Server Suite

<div align="right">
  <a href="#español">🇪🇸 Español</a> | <a href="#english">🇬🇧 English</a>
</div>

<h2 id="español">🇪🇸 Español</h2>

Suite de scripts en Python para manejar mi servidor de **Minecraft Bedrock** en Windows. La hice porque estaba cansado de tener que echar a mis amigos del servidor cada vez que quería hacer una copia de seguridad.

Usa los comandos nativos de Minecraft (`save hold`, `save query`, `save resume`) para hacer **backups en caliente** en segundo plano, sin apagar el servidor ni molestar a los jugadores.

> 💡 **Nota**: todo este proyecto fue hecho con ayuda de herramientas de IA generativa, usadas como copiloto para el código, los tests y la documentación.

### Dos formas de usarlo

**1. Con GUI (dashboard web)** — la forma recomendada:

```
iniciar_gui.bat     ← doble clic en Windows (instala dependencias solo la primera vez)
```

Te abre `http://127.0.0.1:8000` en el navegador con un panel completo: consola en vivo, botones de iniciar/detener/reiniciar, backups, jugadores online, medidores de RAM/CPU y un actualizador oficial de Mojang. Frontend animado con fondo fluido WebGL.

- **No necesita Node.js**: el frontend viaja compilado en `gui_frontend/dist/`.
- Requiere **Python 3.10+** y `pip install -r requirements.txt` (el `.bat` lo hace solo).
- Solo Windows: el servidor BDS oficial de Mojang únicamente existe para Windows.
- El servidor web escucha solo en `127.0.0.1` y rechaza conexiones no locales (HTTP 403 / WebSocket 1008).

**2. Sin GUI (solo consola)** — el wrapper clásico:

```
iniciar_servidor.bat     ← doble clic y el servidor arranca con la consola
```

Es el modo original: el wrapper lee la consola del servidor, detecta jugadores, hace backups automáticos cada 30 minutos (más uno al arrancar y otro al apagar) y mantiene los últimos 15 backups. Para forzar un backup caliente al instante, escribí `backup` en la consola del wrapper.

Ambos modos usan el mismo wrapper y la misma carpeta: podés arrancar con la GUI y seguir usando los scripts de respaldo de siempre.

### ¿Qué hace?

- Backups automáticos cada 30 minutos sin molestar a los jugadores (backups en caliente).
- Borra automáticamente los backups viejos (guarda los últimos 15 y 1 diario por una semana).
- Backup al arrancar el servidor y otro al apagarlo.
- Menú interactivo con `.bat` para restaurar el mundo fácil (`02_restaurar_backup.bat`, `03_regresar_al_anterior.bat`).
- Script para abrir los puertos del firewall (`configurar_firewall.bat`).
- Desde la GUI: consola de comandos en vivo, métricas de RAM/CPU, jugadores online, forzar backup y actualizador de BDS con backup preventivo.

### Archivos

| Archivo | Qué hace |
|---|---|
| `iniciar_gui.bat` | Arranca la GUI (instala dependencias de Python si faltan) |
| `iniciar_servidor.bat` | Arranca el servidor con el wrapper clásico (sin GUI) |
| `server_gui_server.py` | Backend de la GUI: FastAPI + WebSockets, sirve el frontend |
| `server_wrapper.py` | Script principal: lee la consola, detecta jugadores, maneja los backups |
| `backup_worker.py` | Worker de compresión en proceso separado (subprocess, arranque rápido) |
| `auto_backup.py` | Comprime la base de datos a ZIP |
| `restore_backup.py` | Restaura un backup |
| `gui_frontend/` | Frontend React (código fuente + `dist/` compilado, listo para usar) |
| `web/` | GUI clásica de respaldo (sin React) |
| `01_hacer_backup.bat` | Backup manual con robocopy |
| `02_restaurar_backup.bat` | Menú para restaurar un backup |
| `03_regresar_al_anterior.bat` | Vuelve al backup más reciente en un clic |
| `configurar_firewall.bat` | Abre los puertos del firewall |
| `configurar_antivirus.bat` | Configura exclusiones de Windows Defender para backups instantáneos |
| `tools/setup_defender_exclusions.ps1` | Script PowerShell de exclusiones (auto-elevación UAC e idempotente) |
| `server.properties.example` | Plantilla de configuración (copiar a `server.properties`) |

### ⚡ Rendimiento y Windows Defender (Arranque inicial lento)

Si al arrancar el servidor por primera vez (o tras clonar el repo / actualizar addons con miles de archivos) el backup inicial tarda **3+ minutos** en vez de los **~6 segundos normales**:

- **Causa (confirmada por prueba A/B)**: Windows Defender con protección en la nube (MAPS) inspecciona en serie el primer `open()` de cada archivo recién descargado (~15 ms/archivo × 11.000 archivos = ~3 min con 0% de CPU). En la 2ª lectura los archivos ya son confiables y tarda 0.4 s (~340x más rápido).
- **Solución en 1 clic**: Doble clic en `configurar_antivirus.bat` (añade quirúrgicamente las carpetas `worlds`, `resource_packs`, `behavior_packs` y `Backups_Minecraft` a las exclusiones de Defender).
- **One-liner en PowerShell** (como Administrador):
  ```powershell
  powershell -ExecutionPolicy Bypass -File tools\setup_defender_exclusions.ps1
  ```
- **Alternativa manual por GUI**: *Seguridad de Windows → Protección contra virus y amenazas → Administrar la configuración → Exclusiones → Agregar o quitar exclusiones → Carpeta*.
- **Válvula de escape (sin permisos de Admin)**: Puedes añadir `backup-inicio=false` en `server.properties` para omitir el backup en frío al inicio y usar únicamente backups en caliente periódicos.

### Para usarlo

1. Necesitas Python 3.10+ instalado.
2. Clonás el repo o descargás el zip.
3. Copiás `server.properties.example` → `server.properties`.
4. Tirás el `bedrock_server.exe` original (y sus DLLs) adentro (no se incluye por licencia de Mojang; también podés bajarlo con el botón "Actualización BDS" de la GUI).
5. **Con GUI**: doble clic en `iniciar_gui.bat`. **Sin GUI**: doble clic en `iniciar_servidor.bat`.

### Tests

```bash
pip install hypothesis pytest
python -m pytest tests/ -q
```

Incluyen tests property-based (Hypothesis) para el parseo del `save query`, la comparación de versiones, el guard anti zip-slip y el control de acceso local, más suites de inyección de fallos de backups (cancelación, doble backup, snapshot incompleto, ZIP corrupto, rollback) y de la máquina de estados del disparo manual de backup en caliente. Desde la revisión de 2026-08-02 incluyen además regresiones de los fixes (reintento inmediato tras snapshot incompleto, validación de snapshot por `level.dat`, retención con reloj inyectable, filtro de backups corruptos en la GUI, guard TOCTOU del restore) y propiedades adicionales: prefijos de log apilados, idempotencia/normalización de rutas y consenso anti-drift del guard zip-slip entre sus copias.

### Detalles técnicos

Me dio bastantes dolores de cabeza la parte donde la compresión del ZIP se quedaba colgada, así que el worker corre en un proceso separado vía `subprocess` (arranque rápido, sin el pipe de bootstrap de `multiprocessing.spawn`, que se colgaba 50-120 s con el servidor en marcha) con un timeout de seguridad: si tarda más de 2 minutos comprimiendo, el wrapper mata el proceso para que el servidor no quede congelado. La cancelación cooperativa usa un archivo marcador (un hijo subprocess no comparte eventos de memoria). Si el `save query` llega incompleto, el wrapper reintenta el ciclo caliente con backoff exponencial (5-60 s, máximo 10 intentos consecutivos, luego espera el intervalo normal de 30 min); el watchdog de 60 s acota el caso en que el servidor no responde. Espero haber tapado todos los huecos de concurrencia. Si ven algún bug me avisan.

---

<h2 id="english">🇬🇧 English</h2>

A Python suite to manage my **Minecraft Bedrock** server on Windows. I mostly built it because I got annoyed having to kick my friends out of the server every time I wanted to run a backup.

It uses the native Minecraft commands (`save hold`, `save query`, `save resume`) to do **zero-downtime hot backups** in the background, without restarting the server or bothering players.

> 💡 **Note**: this whole project was built with the help of generative AI tools, used as a copilot for the code, the tests and the documentation.

### Two ways to use it

**1. With GUI (web dashboard)** — the recommended way:

```
iniciar_gui.bat     ← double-click on Windows (installs dependencies only once)
```

Opens `http://127.0.0.1:8000` in your browser with a full panel: live console, start/stop/restart buttons, backups, online players, RAM/CPU meters and an official Mojang updater. Animated frontend with a WebGL fluid background.

- **No Node.js needed**: the frontend ships prebuilt in `gui_frontend/dist/`.
- Requires **Python 3.10+** and `pip install -r requirements.txt` (the `.bat` does it for you).
- Windows only: Mojang's official BDS server exists for Windows only.
- The web server listens on `127.0.0.1` only and rejects non-local connections (HTTP 403 / WebSocket 1008).

**2. Without GUI (console only)** — the classic wrapper:

```
iniciar_servidor.bat     ← double-click and the server starts with the console
```

The original mode: the wrapper reads the server console, detects players, runs automatic backups every 30 minutes (plus one on start and one on stop) and keeps the last 15 backups. To force a hot backup on the spot, type `backup` in the wrapper console.

Both modes share the same wrapper and folder — you can start with the GUI and keep using the same backup scripts as always.

### What it does

- Automatic hot backups every 30 minutes without kicking anyone.
- Auto-deletes old backups (keeps the last 15 and 1 daily for a week).
- Backup on server start and on server stop.
- Interactive `.bat` menus to restore the world easily (`02_restaurar_backup.bat`, `03_regresar_al_anterior.bat`).
- Firewall port opener (`configurar_firewall.bat`).
- From the GUI: live command console, RAM/CPU metrics, online players, forced backup and a BDS updater with a preventive backup.

### Files

| File | What it does |
|---|---|
| `iniciar_gui.bat` | Starts the GUI (installs Python deps if missing) |
| `iniciar_servidor.bat` | Starts the server with the classic wrapper (no GUI) |
| `server_gui_server.py` | GUI backend: FastAPI + WebSockets, serves the frontend |
| `server_wrapper.py` | Main script: reads the console, detects players, handles backups |
| `backup_worker.py` | Compression worker in a separate process (subprocess, fast startup) |
| `auto_backup.py` | Zips the database |
| `restore_backup.py` | Restores a backup |
| `gui_frontend/` | React frontend (source + prebuilt `dist/`, ready to use) |
| `web/` | Classic fallback GUI (no React) |
| `01_hacer_backup.bat` | Manual backup with robocopy |
| `02_restaurar_backup.bat` | Menu to restore a zip |
| `03_regresar_al_anterior.bat` | Reverts to the latest backup in one click |
| `configurar_firewall.bat` | Opens firewall ports |
| `configurar_antivirus.bat` | Sets up Windows Defender exclusions for instant backups |
| `tools/setup_defender_exclusions.ps1` | PowerShell exclusion script (UAC auto-elevation & idempotent) |
| `server.properties.example` | Config template (copy to `server.properties`) |

### ⚡ Performance & Windows Defender (Slow initial startup)

If the initial startup backup takes **3+ minutes** instead of the normal **~6 seconds** on a fresh install or after syncing thousands of addon files:

- **Root cause (A/B verified)**: Windows Defender Cloud-delivered Protection (MAPS) inspects the first `open()` of every newly downloaded file sequentially (~15 ms/file × 11,000 files = ~3 min at 0% CPU). On the 2nd read, files are trusted and read in 0.4 s (~340x faster).
- **1-Click Fix**: Double-click `configurar_antivirus.bat` (surgically adds `worlds`, `resource_packs`, `behavior_packs`, and `Backups_Minecraft` to Defender exclusions).
- **PowerShell one-liner** (as Administrator):
  ```powershell
  powershell -ExecutionPolicy Bypass -File tools\setup_defender_exclusions.ps1
  ```
- **Manual GUI alternative**: *Windows Security → Virus & threat protection → Manage settings → Exclusions → Add or remove exclusions → Folder*.
- **Escape valve (without Admin rights)**: Set `backup-inicio=false` in `server.properties` to skip cold startup backup and rely solely on periodic hot backups.

### How to use

1. You need Python 3.10+ installed.
2. Clone the repo or download the zip.
3. Copy `server.properties.example` → `server.properties`.
4. Drop your original `bedrock_server.exe` and DLLs inside (not included due to Mojang's license; you can also fetch it with the "BDS Update" button in the GUI).
5. **With GUI**: double-click `iniciar_gui.bat`. **Without GUI**: double-click `iniciar_servidor.bat`.

### Tests

```bash
pip install hypothesis pytest
python -m pytest tests/ -q
```

Includes property-based tests (Hypothesis) for `save query` parsing, version comparison, the zip-slip guard and the local access control, plus backup fault-injection suites (cancellation, double backup, incomplete snapshot, corrupt ZIP, rollback) and the hot-backup manual trigger state machine. Since the 2026-08-02 review it also includes fix regressions (immediate retry after an incomplete snapshot, snapshot validation by `level.dat`, clock-injectable retention, corrupt-backup filtering in the GUI, restore TOCTOU guard) and extra properties: stacked log prefixes, path idempotence/normalization and anti-drift consensus of the zip-slip guard across its copies.

### Random technical notes

I had some serious headaches with the ZIP compression getting stuck, so the worker now runs in a separate process via `subprocess` (fast startup, no `multiprocessing.spawn` bootstrap pipe, which hung for 50-120 s while the server was running) with a safety timeout: if compression takes more than 2 minutes, the wrapper kills the process so the server doesn't stay frozen. Cooperative cancellation uses a marker file (a subprocess child can't share in-memory events). If the `save query` arrives incomplete, the wrapper retries the hot cycle with exponential backoff (5-60 s, at most 10 consecutive attempts, then it waits for the normal 30-minute interval); the 60 s watchdog bounds the case where the server stops responding. Hopefully I covered all the concurrency edge cases. Let me know if you find any bugs.
