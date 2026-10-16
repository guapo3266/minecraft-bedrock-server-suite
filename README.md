# Minecraft Bedrock Server Suite

<div align="right">
  <a href="#español">🇪🇸 Español</a> | <a href="#english">🇬🇧 English</a>
</div>

<h2 id="español">🇪🇸 Español</h2>

Suite de scripts en Python para manejar mi servidor de **Minecraft Bedrock** en Windows. La hice porque estaba cansado de tener que echar a mis amigos del servidor cada vez que quería hacer una copia de seguridad.

Usa los comandos nativos de Minecraft (`save hold`, `save query`, `save resume`) para hacer **backups en caliente** en segundo plano, sin apagar el servidor ni molestar a los jugadores.

> 💡 **Nota**: todo este proyecto fue hecho con ayuda de herramientas de IA generativa, usadas como copiloto para el código, los tests y la documentación.

### Versión de la suite

La versión común de backend e interfaz se define en `version.json` y aparece en
**Más acciones → Acerca de**. Es independiente de la versión de BDS que muestra
el dashboard. Cambios por versión: [CHANGELOG.md](CHANGELOG.md).
Para preparar la siguiente entrega: [guía de versionado](docs/VERSIONADO.md).

### Dos formas de usarlo

**ZIP para Windows x64:** la entrega `BedrockSuite-Windows-x64.zip` incluye
Python y dependencias. Extráela completa y abre `iniciar_gui.bat`; no requiere
Python, Git ni Node instalados. Las Releases se publican por separado de los
commits. En la GUI, **Más acciones → Actualizar la suite** comprueba versiones
y pide confirmación antes de instalar. Conserva mundos y configuración, espera
el backup final y recupera el código anterior si falla la instalación o el panel.
En carpetas con Git permite comprobar y descargar, pero no reemplazar el código.
[Detalles del actualizador y recuperación](docs/ACTUALIZACIONES_SUITE.md).

**1. Con GUI (dashboard web)** — la forma recomendada:

```
iniciar_gui.bat     ← doble clic en Windows (crea un entorno virtual .venv aislado e instala dependencias solo la primera vez)
```

Te abre `http://127.0.0.1:8000` en el navegador con un panel completo: consola en vivo, botones de iniciar/detener/reiniciar, backups, jugadores online (con permisos, allowlist y kick/ban), medidores de RAM/CPU/disco con gráficas de las últimas 24 horas, la versión instalada de BDS, programación de backups y watchdog, actualizador oficial de Mojang con vuelta atrás a la versión anterior y una tarjeta con tu IP para invitar amigos. Interfaz de vidrio con cabecera flotante y navegación inferior: Servidor, Jugadores, Backups y Addons.

El botón **Personalizar** de la cabecera abre Apariencia: tema claro/oscuro, transparencia, efectos completos/reducidos y un fondo propio (JPEG/PNG/WebP, hasta 10 MB), con zoom, encuadre, oscurecimiento y modos integrado/libre. La primera visita al panel muestra un consejo descartable para descubrirlo; no abre el diálogo automáticamente. **Lectura protegida** adapta el material para mantener legible el texto. La imagen y las preferencias se guardan solo en ese navegador, no se suben al servidor; otro navegador o puerto tiene sus propias preferencias. Si WebGL no está disponible, se usa vidrio suave. No necesita internet para fuentes ni efectos.

La consola aprovecha la altura disponible y permite **Expandir/Reducir** sin perder filtros, historial ni el comando escrito; **Esc** vuelve a la vista normal. En escritorio, recursos y conectividad tienen scroll propio. El aviso del producto y «Administración local» están en **Más acciones → Acerca de**.

- **No necesita Node.js**: el frontend viaja compilado en `gui_frontend/dist/`.
- **Desde código fuente:** requiere **Python 3.10+**. El `.bat` crea un entorno virtual `.venv` aislado del Python de tu máquina e instala `requirements.txt` ahí la primera vez (nada se instala en el Python global). Si no se puede crear el `.venv`, usa el Python global.
- Solo Windows: esta suite solo soporta Windows (el BDS oficial de Mojang existe para Windows y Linux, pero aquí solo se prueba/soporta Windows).
- El servidor web escucha solo en `127.0.0.1` y rechaza conexiones no locales (HTTP 403 / WebSocket 1008). Modo LAN opt-in solo con `iniciar_gui_lan.bat` (`GUI_ALLOW_LAN=1`, sin autenticación: solo para red doméstica de confianza). Además de la IP de origen, se valida el header `Host` (anti DNS-rebinding) y el `Origin` debe coincidir con el host de la propia GUI (anti CSRF entre dispositivos de la LAN). Si accedés por nombre de host (no por IP), definí `GUI_ALLOWED_HOSTS=tu-nombre` antes de arrancar.

**2. Sin GUI (solo consola)** — el wrapper clásico:

```
iniciar_servidor.bat     ← doble clic y el servidor arranca con la consola
```

Es el modo original: el wrapper lee la consola del servidor, detecta jugadores, hace backups automáticos cada 30 minutos por defecto (configurable desde la GUI; más uno al arrancar y otro al apagar) y mantiene los últimos 15 backups. Para forzar un backup caliente al instante, escribí `backup` en la consola del wrapper. Si falta `bedrock_server.exe`, el `.bat` pregunta y lo descarga solo desde Mojang.

Ambos modos usan el mismo wrapper y la misma carpeta: podés arrancar con la GUI y seguir usando los scripts de respaldo de siempre.

### ¿Qué hace?

- Backups automáticos en caliente sin molestar a los jugadores (por defecto cada 30 minutos).
- Programación desde la GUI: cada cuánto, solo cuando hay alguien jugando, o a una hora fija todos los días (aunque el servidor esté apagado).
- Watchdog opcional: si el servidor se cae solo, se re-levanta; también puede reiniciarse a una hora fija cada día.
- Gestión de jugadores: permisos (operator/member/visitor), allowlist y kick/ban desde la GUI, con registro de quién jugó y cuánto.
- Historial persistente: gráficas de RAM/CPU/disco de las últimas 24 h, logs que sobreviven al reinicio de la GUI (marcados con un separador de sesión) y tiempo de juego por jugador.
- Borra automáticamente los backups viejos (guarda los últimos 15 y 1 diario por una semana).
- Backup al arrancar el servidor y otro al apagarlo.
- Actualizador de BDS con marcha atrás: guardo la versión anterior en cada update y si la nueva rompe algo, volvés con un clic.
- Restauración fácil: desde la GUI (restaurar/verificar/borrar) o con la CLI interactiva `python restore_backup.py`. Los accesos directos `.bat` de esta instalación viven en la carpeta local `backups/` y no se distribuyen con el repo.
- Script para abrir los puertos del firewall (`configurar_firewall.bat`; ejecútalo como administrador: sin permisos avisa y aborta en vez de fingir éxito).
- Desde la GUI: consola de comandos en vivo, métricas, forzar backup, restaurar/verificar/borrar backups y una tarjeta con tu IP local/pública para invitar amigos.
- **Asistente de comandos IA con aprobación humana**: traduce peticiones en lenguaje natural en español (ej. "teletransporta a steva a juan", "haz de día", "dame 64 diamantes") a comandos Bedrock mediante LM Studio local (`http://127.0.0.1:1234/v1`). La IA **solo propone** el comando; requiere aprobación explícita del operador con el botón [Ejecutar].
- **Inventario y diagnóstico de addons (solo lectura)**: la pestaña *Addons* de la GUI y la CLI `python addon_inventory_cli.py` (con `--json` y códigos de salida documentados) listan los behavior packs y resource packs de la instalación y de cada mundo, sus módulos, dependencias de packs y de scripting, la versión mínima del motor y los mundos que los referencian, junto con los problemas que demuestran sus metadatos (JSON inválido, UUID duplicados, dependencias ausentes, referencias de mundo sin candidato o ambiguas…). No instala, activa ni modifica nada; detalle en `docs/INFORME_ADDONS.md`.

### Archivos

| Archivo | Qué hace |
|---|---|
| `iniciar_gui.bat` | Arranca la GUI (crea el `.venv` e instala dependencias de Python si faltan) |
| `iniciar_servidor.bat` | Arranca el servidor con el wrapper clásico (sin GUI; también asegura el `.venv` y las dependencias) |
| `server_gui_server.py` | Backend de la GUI: FastAPI + WebSockets, sirve el frontend |
| `server_wrapper.py` | Script principal: lee la consola, detecta jugadores, maneja los backups |
| `backup_worker.py` | Worker de compresión en proceso separado (subprocess, arranque rápido) |
| `tools/bds_first_run.py` | Primer arranque por consola: descarga BDS si falta (pregunta S/n) |
| `tools/verify_backups.py` | Verifica los backups (CRC + presencia de `level.dat`) y marca los no restaurables con `_CORRUPTO` |
| `auto_backup.py` | Comprime la base de datos a ZIP |
| `restore_backup.py` | Restaura un backup |
| `addon_inventory.py` | Analizador compartido de addons: inventario y diagnósticos de packs (solo lectura) |
| `addon_inventory_cli.py` | CLI del inventario de addons (salida legible o `--json`, códigos de salida documentados) |
| `gui_backend/services/ai_assistant.py` | Servicio de traducción a comandos Bedrock vía LM Studio local con resolución de contexto y saneamiento anti-inyección |
| `gui_backend/routers/ai.py` | Endpoints `/api/ai/propose` y `/api/ai/status` protegidos en loopback |
| `gui_frontend/` | Frontend React (código fuente + `dist/` compilado con pestaña de Asistente IA, listo para usar) |
| `web/` | GUI clásica de respaldo (sin React) |
| `configurar_firewall.bat` | Abre los puertos del firewall (como administrador) |
| `configurar_antivirus.bat` | Añade exclusiones de Windows Defender para los backups |
| `tools/setup_defender_exclusions.ps1` | Script PowerShell de exclusiones (pide administrador la primera vez) |
| `requirements-dev.txt` | Dependencias de desarrollo/tests (pytest, hypothesis, httpx, pytest-cov) |
| `server.properties.example` | Plantilla de configuración (copiar a `server.properties`) |

### Arranque inicial lento y Windows Defender

Si el backup inicial tarda 3+ minutos en vez de los ~6 segundos normales (al arrancar por primera vez, tras clonar el repo o tras actualizar addons con miles de archivos):

- **Causa**: Windows Defender con protección en la nube (MAPS) revisa la primera lectura de cada archivo recién descargado (~15 ms por archivo; con 11.000 archivos son ~3 minutos con 0% de CPU). En la segunda lectura ya son confiables y tarda 0.4 s.
- **Solución**: Doble clic en `configurar_antivirus.bat` (añade las carpetas `worlds`, `resource_packs`, `behavior_packs` y `Backups_Minecraft` a las exclusiones de Defender).
- **O desde PowerShell** (como administrador):
  ```powershell
  powershell -ExecutionPolicy Bypass -File tools\setup_defender_exclusions.ps1
  ```
- **Alternativa manual por GUI**: *Seguridad de Windows → Protección contra virus y amenazas → Administrar la configuración → Exclusiones → Agregar o quitar exclusiones → Carpeta*.
- **Sin permisos de administrador**: añade `backup-inicio=false` en `server.properties` para saltarte el backup inicial y depender solo de los backups en caliente periódicos.

### Solución de problemas

- **El backup inicial tarda 3+ minutos**: aplicá las exclusiones de Windows Defender (sección anterior) o poné `backup-inicio=false` en `server.properties`.
- **`409 Hay una instancia externa del servidor en ejecución`**: hay un wrapper o BDS de ESTA instalación corriendo por fuera de la GUI. Cerralo y reintentá; la sonda compara la ruta del ejecutable, así que un BDS de otra carpeta no bloquea.
- **El puerto 8000 está ocupado**: la GUI salta sola al siguiente libre y abre el navegador ahí; para fijarlo, ejecutá `set GUI_PORT=8001` antes de arrancar.
- **La GUI no muestra jugadores**: las detecciones leen el log de BDS en inglés (`Player connected: ...`). No cambies el idioma del servidor; si Mojang cambia el formato, se pierden jugadores pero los backups en caliente siguen funcionando.
- **No aparece un backup para restaurar**: los marcados `_CORRUPTO`, `_EXCEDIDO` o `_CRASH` se ocultan a propósito (misma lista en la GUI y en la CLI).
- **La GUI responde `403 Acceso denegado: host no permitido`**: accediste por un nombre de host que la GUI no reconoce (protección anti DNS-rebinding). Usá `127.0.0.1`/`localhost`, o definí `GUI_ALLOWED_HOSTS=tu-nombre` antes de arrancar.
- **¿Dónde quedan los backups?**: fuera del repo, en `..\..\Backups_Minecraft\auto_backups\<nombre-del-servidor>\`. Se conservan 15 recientes + 1 por día durante 7 días (los marcados, 7 días como evidencia).
- **`Debes apagar el servidor antes de reestablecer un backup`**: la restauración exige BDS apagado; usá la GUI o `python restore_backup.py`.
- **`level-name invalido` / `Ruta de mundo insegura`**: `level-name` debe ser un nombre de carpeta dentro de `worlds/` (por ejemplo, `Mi Mundo`), sin rutas, `..`, nombres de dispositivo ni alias de Windows. Los backups y restores rechazan mundos o carpetas `worlds/` redirigidos por enlaces/junctions.
- **Descarga BDS rechazada por host o redirección**: solo se aceptan ZIPs por HTTPS desde `www.minecraft.net` o `minecraft.net`, también en cada redirección. Si Mojang cambia de dominio, será necesario actualizar la suite.
- **Linux**: no soportado (el BDS de Mojang existe para Linux, pero esta suite solo se prueba en Windows).
- **No corras los e2e sobre una instalación real**: `pytest -m e2e` toca `server.properties` y crea/borra `worlds/TestWorld`.

### Backups y restauración (guía rápida)

- **Dónde quedan**: fuera del repo, en `..\..\Backups_Minecraft\auto_backups\<nombre-del-servidor>\`. Se conservan 15 recientes + 1 por día durante 7 días; los marcados (`_CORRUPTO`/`_EXCEDIDO`/`_CRASH`), 7 días como evidencia y nunca se ofrecen para restaurar.
- **Forzar un backup ahora**: botón "Backup" de la GUI o `backup` en la consola del wrapper.
- **Restaurar (GUI)**: pestaña Backups → elegir el punto → [Restaurar]. Exige el servidor apagado; si algo falla a mitad del intercambio, se intenta recuperar el mundo anterior (rollback). Si Windows impide renombrar la carpeta, la recuperación por copia conserva el `.bak` para una recuperación exacta manual: no lo borres hasta revisar el mundo y los packs.
- **Restaurar (CLI)**: `python restore_backup.py` → elegir número → escribir `SI`. Antes de tocar nada recupera restos de restauraciones interrumpidas.
- **Verificar integridad**: `python tools\verify_backups.py` comprueba CRC y que cada ZIP tenga `level.dat` (sin él no es restaurable) y marca los malos automáticamente. Recomendado correrlo de vez en cuando; es lento con backups grandes porque los lee enteros.
- **Ante un apagón a mitad de restauración**: en el próximo arranque (GUI o wrapper) los restos se limpian solos; si ves carpetas `.bak_huerfano_*`, son resguardos conservados a propósito (no se borran solos: revísalos y bórralos cuando confirmes que no los necesitás).
- **Ante una actualización BDS interrumpida**: la GUI intenta recuperar los binarios al arrancar. Si sigue habiendo errores, conserva las carpetas `bds_update_prev_*`: contienen el manifiesto y los originales pendientes de recuperar.

### Para usarlo desde código fuente

1. Necesitas Python 3.10+ instalado.
2. Clonás el repo o descargás el zip.
3. Copiás `server.properties.example` → `server.properties`.
4. Tirás el `bedrock_server.exe` original (y sus DLLs) adentro (no se incluye por licencia de Mojang; también podés bajarlo con la opción "Actualización BDS" del menú de la GUI).
5. **Con GUI**: doble clic en `iniciar_gui.bat`. **Sin GUI**: doble clic en `iniciar_servidor.bat`. Cualquiera de los dos crea `.venv` e instala las dependencias solo la primera vez (y las actualiza si `requirements.txt` cambia).

En una instalación nueva la GUI muestra un **asistente de 3 pasos** (descarga de BDS, creación del mundo y configuración inicial) en vez del dashboard; cuando termina, aparece el panel normal.

### Tests

```bash
pip install -r requirements-dev.txt   # o .venv\Scripts\python -m pip install -r requirements-dev.txt
python -m ruff check .                  # lint estatico (F/E9)
python -m pytest tests -m "not e2e" -q   # excluye e2e (requieren BDS vivo y tocan mundo real)

cd gui_frontend
npm ci && npm run lint && npm test && npm run build   # frontend: lint (oxlint), tests (vitest) y rebuild del dist/
```

La suite Python cubre property-based tests (Hypothesis) del `save query`, versiones, guard anti zip-slip y control de acceso local; inyección de fallos de backups (cancelación, doble backup, snapshot incompleto, ZIP corrupto, rollback, disco lleno); programación + watchdog, jugadores, historial SQLite, rollback de BDS, inventario de addons, canal NDJSON, guards HTTP/WebSocket. Usá siempre el filtro `not e2e` si hay una instalación BDS en la carpeta. El detalle histórico vive en `docs/INFORME_*`; las instrucciones locales `AGENTS.md` no se distribuyen en el repo público.

El QA opcional de navegador se ejecuta con `python gui_frontend/tests/appearance-browser-check.py` y requiere Playwright Python y Chrome. Sirve el `dist/` real con API/WS simulados: comprueba fondos, temas, teclado, navegación y reconexión, sin ejecutar BDS. La guía del frontend está en [gui_frontend/README.md](gui_frontend/README.md).

Validación local del 2026-10-15: **1014 pruebas Python aprobadas, 2 omitidas por requerir una instalación real, 2 e2e excluidas y 88 pruebas frontend aprobadas**, además de lint, build y QA visual con API simulada. Alcance y sincronización: [informe de actualización](docs/INFORME_ACTUALIZACION_2026-10-15.md).

### Licencia y aviso legal

Distribuido bajo licencia MIT. Ver archivo `LICENSE`.

> **NO ES UN PRODUCTO OFICIAL DE MINECRAFT. NO ESTÁ APROBADO POR NI ASOCIADO CON MOJANG O MICROSOFT.**  
> Minecraft y Bedrock Dedicated Server (BDS) son marcas de Mojang Synergies AB / Microsoft Corporation. Este proyecto es una herramienta comunitaria independiente y no redistribuye binarios ni archivos del juego original.

---

<h2 id="english">🇬🇧 English</h2>

A Python suite to manage my **Minecraft Bedrock** server on Windows. I mostly built it because I got annoyed having to kick my friends out of the server every time I wanted to run a backup.

It uses the native Minecraft commands (`save hold`, `save query`, `save resume`) to do **zero-downtime hot backups** in the background, without restarting the server or bothering players.

> 💡 **Note**: this whole project was built with the help of generative AI tools, used as a copilot for the code, the tests and the documentation.

### Suite version

The backend and UI share the version defined in `version.json`, shown under
**More actions → About**. It is independent of the BDS version displayed on the
dashboard. Release history: [CHANGELOG.md](CHANGELOG.md).
Maintenance instructions: [versioning guide](docs/VERSIONADO.md) (Spanish).

### Two ways to use it

**Windows x64 ZIP:** `BedrockSuite-Windows-x64.zip` includes Python and its
dependencies. Extract it fully and open `iniciar_gui.bat`; no Python, Git or Node
installation is needed. Releases are published separately from commits.
**More actions → Update the suite** checks stable releases and requires confirmation
before installation. It preserves worlds and configuration, waits for the final
backup and restores previous code if installation or dashboard startup fails.
Git checkouts allow checks and downloads, but no automatic file replacement.
[Updater and recovery details](docs/ACTUALIZACIONES_SUITE.md) (Spanish).

**1. With GUI (web dashboard)** — the recommended way:

```
iniciar_gui.bat     ← double-click on Windows (creates an isolated .venv virtual environment and installs dependencies only once)
```

Opens `http://127.0.0.1:8000` in your browser with a full panel: live console, start/stop/restart buttons, backups, online players (with permissions, allowlist and kick/ban), RAM/CPU/disk meters with 24-hour charts, the installed BDS version, backup scheduling and watchdog, an official Mojang updater with rollback to the previous version and a card with your IP to invite friends. Glass interface with a floating header and bottom navigation: Server, Players, Backups and Addons.

The visible **Customize** button opens Appearance: light/dark themes, transparency, full/reduced effects and your own background (JPEG/PNG/WebP, up to 10 MB), with zoom, framing, darkening and integrated/free modes. A dismissible tip introduces it on the first dashboard visit without opening the dialog automatically. **Protected readability** adapts the material to keep text legible. Images and preferences stay in that browser, never uploaded to the server; another browser or port has its own preferences. Soft glass is used if WebGL is unavailable. Fonts and effects need no internet connection.

The console uses the available height and supports **Expand/Collapse** without losing filters, command history or draft input; **Esc** restores the normal view. On desktop, resources and connectivity scroll independently. The product disclaimer and local-management notice live under **More actions → About**.

- **No Node.js needed**: the frontend ships prebuilt in `gui_frontend/dist/`.
- **When running from source:** requires **Python 3.10+**. The `.bat` creates a `.venv` virtual environment isolated from your machine's Python and installs `requirements.txt` there on first run (nothing goes into the global Python). If `.venv` cannot be created, it falls back to the global Python.
- Windows only: this suite only supports Windows (Mojang's official BDS exists for Windows and Linux, but only Windows is tested/supported here).
- The web server listens on `127.0.0.1` only and rejects non-local connections (HTTP 403 / WebSocket 1008). LAN mode is opt-in via `iniciar_gui_lan.bat` (`GUI_ALLOW_LAN=1`, no authentication: trusted home network only). Besides the source IP, the `Host` header is validated (anti DNS-rebinding) and the `Origin` must match the GUI's own host (anti cross-device CSRF on the LAN). If you browse by hostname (not IP), set `GUI_ALLOWED_HOSTS=your-hostname` before starting.

**2. Without GUI (console only)** — the classic wrapper:

```
iniciar_servidor.bat     ← double-click and the server starts with the console
```

The original mode: the wrapper reads the server console, detects players, runs automatic backups every 30 minutes by default (configurable from the GUI; plus one on start and one on stop) and keeps the last 15 backups. To force a hot backup on the spot, type `backup` in the wrapper console. If `bedrock_server.exe` is missing, the `.bat` asks and downloads it from Mojang.

Both modes share the same wrapper and folder — you can start with the GUI and keep using the same backup scripts as always.

### What it does

- Automatic hot backups without kicking anyone (every 30 minutes by default).
- Scheduling from the GUI: how often, only when someone is playing, or at a fixed daily time (even with the server off).
- Optional watchdog: if the server crashes on its own, it restarts by itself; it can also restart at a fixed time every day.
- Player management: permissions (operator/member/visitor), allowlist and kick/ban from the GUI, with a record of who played and for how long.
- Persistent history: 24-hour RAM/CPU/disk charts, logs that survive GUI restarts (marked with a session separator) and playtime per player.
- Auto-deletes old backups (keeps the last 15 and 1 daily for a week).
- Backup on server start and on server stop.
- BDS updater with rollback: each update keeps the previous version, and if the new one breaks something you go back with one click.
- Easy restore: from the GUI (restore/verify/delete) or with the interactive `python restore_backup.py` CLI. This installation's `.bat` shortcuts live in the local `backups/` folder and are not distributed with the repo.
- Firewall port opener (`configurar_firewall.bat`; run it as administrator: without elevation it reports the failure instead of pretending success).
- From the GUI: live command console, metrics, forced backup, restore/verify/delete backups and a card with your local/public IP to invite friends.
- **AI Command Assistant with human-in-the-loop approval**: translates natural language requests (e.g. "teleport steva to juan", "make it day", "give 64 diamonds") into Bedrock commands via local LM Studio (`http://127.0.0.1:1234/v1`). The AI **only proposes** the command; execution strictly requires the operator to click [Ejecutar / Execute].
- **Addon inventory and diagnostics (read-only)**: the GUI *Addons* tab and the CLI `python addon_inventory_cli.py` (with `--json` and documented exit codes) list the behavior and resource packs of the installation and of every world, their modules, pack and scripting dependencies, the declared minimum engine version and which worlds reference them, together with the problems their metadata proves (invalid JSON, duplicate UUIDs, missing dependencies, world references with no candidate or ambiguous…). It installs, enables or modifies nothing; details in `docs/INFORME_ADDONS.md`.

### Files

| File | What it does |
|---|---|
| `iniciar_gui.bat` | Starts the GUI (creates the `.venv` and installs Python deps if missing) |
| `iniciar_servidor.bat` | Starts the server with the classic wrapper (no GUI; also ensures the `.venv` and dependencies) |
| `server_gui_server.py` | GUI backend: FastAPI + WebSockets, serves the frontend |
| `server_wrapper.py` | Main script: reads the console, detects players, handles backups |
| `backup_worker.py` | Compression worker in a separate process (subprocess, fast startup) |
| `tools/bds_first_run.py` | Console first run: downloads BDS if missing (asks S/n) |
| `tools/verify_backups.py` | CRC-checks every backup (plus the presence of `level.dat`) and marks non-restorable ones as `_CORRUPTO` |
| `auto_backup.py` | Zips the database |
| `restore_backup.py` | Restores a backup |
| `addon_inventory.py` | Shared addon analyzer: pack inventory and diagnostics (read-only) |
| `addon_inventory_cli.py` | Addon inventory CLI (readable output or `--json`, documented exit codes) |
| `gui_backend/services/ai_assistant.py` | Bedrock command translation service via local LM Studio with context resolution and injection sanitation |
| `gui_backend/routers/ai.py` | Loopback-protected endpoints `/api/ai/propose` and `/api/ai/status` |
| `gui_frontend/` | React frontend (source + prebuilt `dist/` with AI Assistant tab, ready to use) |
| `web/` | Classic fallback GUI (no React) |
| `configurar_firewall.bat` | Opens firewall ports (as administrator) |
| `configurar_antivirus.bat` | Adds Windows Defender exclusions for the backups |
| `tools/setup_defender_exclusions.ps1` | PowerShell exclusion script (asks for admin the first time) |
| `requirements-dev.txt` | Development/test dependencies (pytest, hypothesis, httpx, pytest-cov) |
| `server.properties.example` | Config template (copy to `server.properties`) |

### Slow initial startup and Windows Defender

If the initial startup backup takes 3+ minutes instead of the normal ~6 seconds (on a fresh install, after cloning the repo or after syncing thousands of addon files):

- **Cause**: Windows Defender Cloud-delivered Protection (MAPS) scans the first read of every newly downloaded file (~15 ms per file; with 11,000 files that is ~3 minutes at 0% CPU). On the second read the files are trusted and it takes 0.4 s.
- **Fix**: Double-click `configurar_antivirus.bat` (adds `worlds`, `resource_packs`, `behavior_packs`, and `Backups_Minecraft` to Defender exclusions).
- **Or from PowerShell** (as administrator):
  ```powershell
  powershell -ExecutionPolicy Bypass -File tools\setup_defender_exclusions.ps1
  ```
- **Manual GUI alternative**: *Windows Security → Virus & threat protection → Manage settings → Exclusions → Add or remove exclusions → Folder*.
- **Without admin rights**: set `backup-inicio=false` in `server.properties` to skip the startup backup and rely on the periodic hot backups.

### Troubleshooting

- **The initial backup takes 3+ minutes**: apply the Windows Defender exclusions (previous section) or set `backup-inicio=false` in `server.properties`.
- **`409 Hay una instancia externa del servidor en ejecución`**: a wrapper or BDS of THIS installation is running outside the GUI. Close it and retry; the probe compares the executable path, so a BDS from another folder does not block.
- **Port 8000 is taken**: the GUI automatically jumps to the next free port and opens the browser there; to pin it, run `set GUI_PORT=8001` before starting.
- **The GUI shows no players**: detections read the BDS log in English (`Player connected: ...`). Do not change the server language; if Mojang changes the format, players are lost but hot backups keep working.
- **A backup does not show up for restore**: entries marked `_CORRUPTO`, `_EXCEDIDO` or `_CRASH` are hidden on purpose (same list in the GUI and the CLI).
- **The GUI answers `403 Acceso denegado: host no permitido`**: you browsed by a hostname the GUI does not know (anti DNS-rebinding protection). Use `127.0.0.1`/`localhost`, or set `GUI_ALLOWED_HOSTS=your-hostname` before starting.
- **Where are the backups?**: outside the repo, in `..\..\Backups_Minecraft\auto_backups\<server-name>\`. The last 15 plus 1 daily for 7 days are kept (marked ones, 7 days as evidence).
- **`Debes apagar el servidor antes de reestablecer un backup`**: restore requires BDS to be stopped; use the GUI or `python restore_backup.py`.
- **`Invalid level-name` / `Unsafe world path`**: `level-name` must be a folder name inside `worlds/` (for example, `My World`), without paths, `..`, device names or Windows aliases. Backups and restores reject worlds or `worlds/` folders redirected by links/junctions.
- **BDS download rejected due to a host or redirect**: ZIPs are accepted only over HTTPS from `www.minecraft.net` or `minecraft.net`, including every redirect. If Mojang changes domains, the suite will need an update.
- **Linux**: not supported (Mojang's BDS exists for Linux, but this suite is only tested on Windows).
- **Do not run the e2e on a real installation**: `pytest -m e2e` touches `server.properties` and creates/deletes `worlds/TestWorld`.

### Backups and restore (quick guide)

- **Where they live**: outside the repo, in `..\..\Backups_Minecraft\auto_backups\<server-name>\`. The last 15 plus 1 daily for 7 days are kept; marked ones (`_CORRUPTO`/`_EXCEDIDO`/`_CRASH`) stay 7 days as evidence and are never offered for restore.
- **Force a backup now**: the GUI "Backup" button or `backup` in the wrapper console.
- **Restore (GUI)**: Backups tab → pick the point → [Restore]. Requires the server to be off; if the swap fails midway, recovery of the previous world is attempted (rollback). If Windows prevents renaming the folder, recovery by copy keeps the `.bak` for exact manual recovery: keep it until you have checked the world and packs.
- **Restore (CLI)**: `python restore_backup.py` → pick a number → type `SI`. Before touching anything it recovers leftovers from interrupted restores.
- **Verify integrity**: `python tools\verify_backups.py` checks the CRC and that every ZIP contains `level.dat` (without it a backup is not restorable) and quarantines the bad ones. Worth running once in a while; it is slow with large backups because it reads them fully.
- **After a blackout mid-restore**: leftovers are cleaned up on the next start (GUI or wrapper); if you see `.bak_huerfano_*` folders they are preserved safety copies on purpose (never auto-deleted: review them and remove them once you are sure).
- **After an interrupted BDS update**: the GUI attempts to recover the binaries on startup. If errors remain, keep the `bds_update_prev_*` folders: they contain the manifest and originals still awaiting recovery.

### Running from source

1. You need Python 3.10+ installed.
2. Clone the repo or download the zip.
3. Copy `server.properties.example` → `server.properties`.
4. Drop your original `bedrock_server.exe` and DLLs inside (not included due to Mojang's license; you can also fetch it with the "BDS Update" option in the GUI menu).
5. **With GUI**: double-click `iniciar_gui.bat`. **Without GUI**: double-click `iniciar_servidor.bat`. Either one creates the `.venv` and installs dependencies only on the first run (and refreshes them when `requirements.txt` changes).

On a fresh install the GUI shows a **3-step setup wizard** (BDS download, world creation and initial configuration) instead of the dashboard; the normal panel appears once it finishes.

### Tests

```bash
pip install -r requirements-dev.txt   # or .venv\Scripts\python -m pip install -r requirements-dev.txt
python -m ruff check .                  # static lint (F/E9)
python -m pytest tests -m "not e2e" -q   # excludes e2e (need live BDS, touches real world)

cd gui_frontend
npm ci && npm run lint && npm test && npm run build   # frontend: lint (oxlint), tests (vitest), dist rebuild
```

The Python suite covers Hypothesis properties (`save query`, versions, zip-slip and local access), backup fault injection, scheduling/watchdog, players, SQLite history, BDS rollback, addons, NDJSON, HTTP/WebSocket guards. Always use `not e2e` when the directory contains a BDS installation. Historical reports live in `docs/INFORME_*`; local `AGENTS.md` instructions are not distributed in the public repository.

Optional browser QA runs with `python gui_frontend/tests/appearance-browser-check.py` and requires Playwright Python and Chrome. It serves the real `dist/` with mocked API/WS to check backgrounds, themes, keyboard navigation and reconnection without running BDS. See [gui_frontend/README.md](gui_frontend/README.md) (Spanish).

Local validation on 2026-10-15: **1014 Python tests passed, 2 skipped because they require a real installation, 2 e2e deselected and 88 frontend tests passed**, plus lint, build and browser QA with mocked API. Scope and synchronization: [update report](docs/INFORME_ACTUALIZACION_2026-10-15.md) (Spanish).

### License and disclaimer

Distributed under the MIT License. See `LICENSE` for details.

> **NOT AN OFFICIAL MINECRAFT PRODUCT. NOT APPROVED BY OR ASSOCIATED WITH MOJANG OR MICROSOFT.**  
> Minecraft and Bedrock Dedicated Server (BDS) are trademarks of Mojang Synergies AB / Microsoft Corporation. This project is an independent community tool and does not redistribute proprietary game binaries.

### Random technical notes

I had some serious headaches with the ZIP compression getting stuck, so the worker now runs in a separate process via `subprocess` (fast startup, no `multiprocessing.spawn` bootstrap pipe, which hung for 50-120 s while the server was running) with a safety timeout that scales with the world size (a fixed 2-minute cap killed the worker on every cycle for large worlds; the base 120 s/240 s values still apply as a floor), so the server doesn't stay frozen. Cooperative cancellation uses a marker file (a subprocess child can't share in-memory events) and the packer writes in chunks so a cancel on a huge file takes effect immediately. If the `save query` arrives incomplete, the wrapper retries the hot cycle with exponential backoff (5-60 s, at most 10 consecutive attempts, then it waits for the normal 30-minute interval); the 60 s watchdog bounds the case where the server stops responding. Hopefully I covered all the concurrency edge cases. Let me know if you find any bugs.
