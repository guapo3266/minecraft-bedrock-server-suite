<div align="right">
  <a href="#español">🇪🇸 Español</a> | <a href="#english">🇬🇧 English</a>
</div>

# Minecraft Bedrock Server Suite

<h2 id="español">🇪🇸 Español</h2>

Wrapper, auto-backups en caliente, y herramientas de administración para Minecraft Bedrock Dedicated Server en Windows. Soporta backups sin desconectar jugadores usando el protocolo nativo `save hold`/`save query`/`save resume`.

Probado en Windows 10/11 con Python 3.10+. Auditado en julio 2026 — 20 bugs corregidos.

### Qué hace

- **Backups en caliente** cada 30 minutos sin echar jugadores
- **Retención automática**: 15 recientes + 1 diario por 7 días
- **Backup inicial** al arrancar y **backup de cierre** al detener
- **Restauración interactiva** estilo Realms desde consola
- **Configuración de firewall** automática para puertos 19132-19133
- **Inyección de APIs experimentales** en `level.dat` (gametest, custom items, etc.)

### Archivos

```
iniciar_servidor.bat          # Arranca el servidor con el wrapper
01_hacer_backup.bat           # Backup manual (Robocopy)
02_restaurar_backup.bat       # Restaurar backup desde menú interactivo
03_regresar_al_anterior.bat   # Volver al último backup en un clic
configurar_firewall.bat       # Abrir puertos UDP/TCP (requiere admin)

server_wrapper.py             # Wrapper principal — gestiona BDS y orquesta backups
auto_backup.py                # Motor de compresión ZIP, retención y validación
restore_backup.py             # Restauración de backups .zip

enable_beta_apis.py           # Inyecta flags experimentales en level.dat (NBT)
enable_beta_apis_v2.py        # Versión con soporte para NBT binario/header

server.properties.example     # Plantilla de configuración
```

### Requisitos

- Windows 10/11 o Windows Server
- Python 3.10 o superior
- [Minecraft Bedrock Dedicated Server](https://www.minecraft.net/download/server/bedrock) (`bedrock_server.exe` en la raíz)
- `amulet-nbt` (solo para `enable_beta_apis*.py`): `pip install amulet-nbt`

### Instalación

```cmd
git clone https://github.com/guapo3266/minecraft-bedrock-server-suite.git
cd minecraft-bedrock-server-suite

# Configurar el servidor
copy server.properties.example server.properties

# Descargar BDS y colocar bedrock_server.exe + DLLs en la raíz

# Abrir puertos (como Administrador)
configurar_firewall.bat
```

### Uso

```cmd
# Iniciar
iniciar_servidor.bat

# Detener (escribe en la consola del servidor)
stop
```

El wrapper hace un backup inicial al arrancar y un backup final al apagar. Los backups en caliente se disparan automáticamente cada 30 minutos mientras haya jugadores conectados.

Los backups se guardan en `../../Backups_Minecraft/auto_backups/` relativo a la carpeta del servidor.

### Backups manuales

- `01_hacer_backup.bat` — copia la carpeta del mundo con Robocopy (funciona con servidor encendido o apagado)
- `02_restaurar_backup.bat` — menú interactivo de restauración
- `03_regresar_al_anterior.bat` — revierte al backup más reciente (hace copia de seguridad del estado actual antes)

### Cómo funciona el backup en caliente

1. El wrapper envía `save hold` al servidor — el mundo se congela en disco
2. Cada 3 segundos envía `save query` — BDS responde con la lista de archivos y sus tamaños exactos
3. Cuando dejan de llegar archivos nuevos (5s de silencio), se lanza un proceso hijo que comprime los archivos
4. Se valida que cada archivo tenga exactamente los bytes reportados — si no coincide, el backup se aborta
5. Se valida que el snapshot cubra al menos el 70% de los archivos en `worlds/<mundo>/db/`
6. Al terminar, se envía `save resume` y el servidor sigue normalmente

Si algo falla (timeout de 120s en compresión, archivo corrupto, snapshot incompleto), el backup se descarta y el servidor reanuda escrituras. No se generan backups silenciosamente corruptos.

### Límites conocidos

- Las detecciones de jugadores dependen de strings en inglés en el log de BDS. Si cambia el formato en futuras versiones, el wrapper no detectará jugadores y no hará backups en caliente (solo el de inicio y cierre).
- `rotate_backups()` corre dentro del lock de backup. Si el directorio de backups tiene miles de archivos y el disco es lento, puede retrasar la liberación del lock.
- Los scripts `enable_beta_apis*.py` requieren `amulet-nbt`. Si no está instalado, fallan con error claro.

### Auditoría

Julio 2026 — 20 bugs encontrados y corregidos. Ver [`INFORME_AUDITORIA.md`](INFORME_AUDITORIA.md) para detalle de cada bug, y [`REGISTRO_TESTS.md`](REGISTRO_TESTS.md) para el registro completo de tests.

### Licencia

MIT. Ver [`LICENSE`](LICENSE).

Minecraft es marca registrada de Mojang/Microsoft. Este proyecto no está afiliado.

---

<h2 id="english">🇬🇧 English</h2>

Wrapper, hot auto-backups, and administration tools for Minecraft Bedrock Dedicated Server on Windows. Supports zero-downtime backups (without kicking players) using the native `save hold`/`save query`/`save resume` protocol.

Tested on Windows 10/11 with Python 3.10+. Audited in July 2026 — 20 bugs fixed.

### Features

- **Hot auto-backups** every 30 minutes without kicking players
- **Automated retention**: 15 recent + 1 daily for 7 days
- **Startup backup** upon booting and **shutdown backup** on stop
- **Interactive restoration** console (Realms-style)
- **Automated firewall setup** for ports 19132-19133
- **Experimental APIs injection** into `level.dat` (gametest, custom items, etc.)

### Files

```
iniciar_servidor.bat          # Starts the server with the wrapper
01_hacer_backup.bat           # Manual backup (Robocopy)
02_restaurar_backup.bat       # Restore backup from an interactive menu
03_regresar_al_anterior.bat   # Revert to the latest backup in one click
configurar_firewall.bat       # Open UDP/TCP ports (requires admin)

server_wrapper.py             # Main wrapper — manages BDS and orchestrates backups
auto_backup.py                # ZIP compression, retention, and validation engine
restore_backup.py             # .zip backups restoration script

enable_beta_apis.py           # Injects experimental flags into level.dat (NBT)
enable_beta_apis_v2.py        # Version with support for binary NBT/header

server.properties.example     # Configuration template
```

### Requirements

- Windows 10/11 or Windows Server
- Python 3.10 or higher
- [Minecraft Bedrock Dedicated Server](https://www.minecraft.net/download/server/bedrock) (`bedrock_server.exe` in the root folder)
- `amulet-nbt` (only for `enable_beta_apis*.py`): `pip install amulet-nbt`

### Installation

```cmd
git clone https://github.com/guapo3266/minecraft-bedrock-server-suite.git
cd minecraft-bedrock-server-suite

# Configure the server
copy server.properties.example server.properties

# Download BDS and place bedrock_server.exe + DLLs in the root folder

# Open ports (as Administrator)
configurar_firewall.bat
```

### Usage

```cmd
# Start
iniciar_servidor.bat

# Stop (type in the server console)
stop
```

The wrapper performs an initial backup on startup and a final backup on shutdown. Hot backups trigger automatically every 30 minutes as long as there are players online.

Backups are saved to `../../Backups_Minecraft/auto_backups/` relative to the server folder.

### Manual Backups

- `01_hacer_backup.bat` — copies the world folder using Robocopy (works whether the server is running or stopped)
- `02_restaurar_backup.bat` — interactive restoration menu
- `03_regresar_al_anterior.bat` — reverts to the most recent backup (creates a safety backup of the current state first)

### How Hot Backups Work

1. The wrapper sends `save hold` to the server — the world is frozen on disk
2. Every 3 seconds, it sends `save query` — BDS responds with the list of files and their exact sizes
3. When no new files arrive (5s of silence), a child process is launched to compress the files
4. It validates that each file has exactly the reported bytes — if it doesn't match, the backup is aborted
5. It validates that the snapshot covers at least 70% of the files in `worlds/<world>/db/`
6. Upon completion, `save resume` is sent and the server continues normally

If anything fails (120s compression timeout, corrupted file, incomplete snapshot), the backup is discarded and the server resumes writes. No silently corrupted backups are generated.

### Known Limitations

- Player detection relies on English strings in the BDS log. If the format changes in future versions, the wrapper won't detect players and won't make hot backups (only startup and shutdown backups).
- `rotate_backups()` runs inside the backup lock. If the backup directory has thousands of files and the disk is slow, it might delay releasing the lock.
- The `enable_beta_apis*.py` scripts require `amulet-nbt`. If not installed, they fail with a clear error.

### Auditing

July 2026 — 20 bugs found and fixed. See [`INFORME_AUDITORIA.md`](INFORME_AUDITORIA.md) for details on each bug, and [`REGISTRO_TESTS.md`](REGISTRO_TESTS.md) for the complete test log (available in Spanish).

### License

MIT. See [`LICENSE`](LICENSE).

Minecraft is a registered trademark of Mojang/Microsoft. This project is not affiliated.

---

**Nota de desarrollo / Development note:** Este repositorio fue desarrollado, refactorizado y documentado con asistencia de herramientas de Inteligencia Artificial (IA), acompañado de pruebas y auditorías en entornos de prueba locales. / This repository was developed, refactored, and documented with the assistance of Artificial Intelligence (AI) tools, accompanied by testing and auditing in local test environments.
