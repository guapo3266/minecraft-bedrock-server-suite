# Minecraft Bedrock Server Suite

Wrapper, auto-backups en caliente, y herramientas de administración para Minecraft Bedrock Dedicated Server en Windows. Soporta backups sin desconectar jugadores usando el protocolo nativo `save hold`/`save query`/`save resume`.

Probado en Windows 10/11 con Python 3.10+. Auditado en julio 2026 — 20 bugs corregidos.

## Qué hace

- **Backups en caliente** cada 30 minutos sin echar jugadores
- **Retención automática**: 15 recientes + 1 diario por 7 días
- **Backup inicial** al arrancar y **backup de cierre** al detener
- **Restauración interactiva** estilo Realms desde consola
- **Configuración de firewall** automática para puertos 19132-19133
- **Inyección de APIs experimentales** en `level.dat` (gametest, custom items, etc.)
- **Registro de componentes personalizados** para behavior packs con Scripting API

## Archivos

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

## Requisitos

- Windows 10/11 o Windows Server
- Python 3.10 o superior
- [Minecraft Bedrock Dedicated Server](https://www.minecraft.net/download/server/bedrock) (`bedrock_server.exe` en la raíz)
- `amulet-nbt` (solo para `enable_beta_apis*.py`): `pip install amulet-nbt`

## Instalación

```cmd
git clone https://github.com/guapo3266/minecraft-bedrock-server-suite.git
cd minecraft-bedrock-server-suite

# Configurar el servidor
copy server.properties.example server.properties

# Descargar BDS y colocar bedrock_server.exe + DLLs en la raíz

# Abrir puertos (como Administrador)
configurar_firewall.bat
```

## Uso

```cmd
# Iniciar
iniciar_servidor.bat

# Detener (escribe en la consola del servidor)
stop
```

El wrapper hace un backup inicial al arrancar y un backup final al apagar. Los backups en caliente se disparan automáticamente cada 30 minutos mientras haya jugadores conectados.

Los backups se guardan en `../../Backups_Minecraft/auto_backups/` relativo a la carpeta del servidor.

## Backups manuales

- `01_hacer_backup.bat` — copia la carpeta del mundo con Robocopy (funciona con servidor encendido o apagado)
- `02_restaurar_backup.bat` — menú interactivo de restauración
- `03_regresar_al_anterior.bat` — revierte al backup más reciente (hace copia de seguridad del estado actual antes)

## Cómo funciona el backup en caliente

1. El wrapper envía `save hold` al servidor — el mundo se congela en disco
2. Cada 3 segundos envía `save query` — BDS responde con la lista de archivos y sus tamaños exactos
3. Cuando dejan de llegar archivos nuevos (5s de silencio), se lanza un proceso hijo que comprime los archivos
4. Se valida que cada archivo tenga exactamente los bytes reportados — si no coincide, el backup se aborta
5. Se valida que el snapshot cubra al menos el 70% de los archivos en `worlds/<mundo>/db/`
6. Al terminar, se envía `save resume` y el servidor sigue normalmente

Si algo falla (timeout de 120s en compresión, archivo corrupto, snapshot incompleto), el backup se descarta y el servidor reanuda escrituras. No se generan backups silenciosamente corruptos.

## Límites conocidos

- Las detecciones de jugadores dependen de strings en inglés en el log de BDS. Si cambia el formato en futuras versiones, el wrapper no detectará jugadores y no hará backups en caliente (solo el de inicio y cierre).
- `rotate_backups()` corre dentro del lock de backup. Si el directorio de backups tiene miles de archivos y el disco es lento, puede retrasar la liberación del lock.
- Los scripts `enable_beta_apis*.py` requieren `amulet-nbt`. Si no está instalado, fallan con error claro.

## Auditoría

Julio 2026 — 20 bugs encontrados y corregidos. Ver [`INFORME_AUDITORIA.md`](INFORME_AUDITORIA.md) para detalle de cada bug, y [`REGISTRO_TESTS.md`](REGISTRO_TESTS.md) para el registro completo de tests.

## Licencia

MIT. Ver [`LICENSE`](LICENSE).

Minecraft es marca registrada de Mojang/Microsoft. Este proyecto no está afiliado.

---

**Nota de desarrollo:** Este repositorio fue desarrollado, refactorizado y documentado con asistencia de herramientas de Inteligencia Artificial (IA), acompañado de pruebas y auditorías en entornos de prueba locales.

