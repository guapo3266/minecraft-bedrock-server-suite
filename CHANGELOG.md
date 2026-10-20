# Historial de cambios

La versión de **Minecraft Bedrock Server Suite** se define en `version.json` y
es independiente de la versión de Minecraft Bedrock Dedicated Server (BDS).
Este historial empieza en 2.0.0; el desarrollo anterior se conserva en Git y en
los informes de `docs/`, sin asignarle versiones retrospectivas.

## [Sin publicar]

### Eliminado

- Asistente IA experimental de la GUI (LM Studio/FunctionGemma): los endpoints
  `POST /api/ai/propose` y `GET /api/ai/status`, el panel flotante y sus textos
  ES/EN, el servicio de traducción a comandos Bedrock, sus utilidades de
  auditoría y la variable `LMSTUDIO_MODEL` de los lanzadores de la GUI. Los
  comandos se siguen enviando solo desde la consola (`POST /api/command`).

### Corregido

- Esperas de cierre incoherentes con los timeouts de backup escalados por
  tamaño: el join de cierre del worker caliente usa ahora su propio timeout
  escalado (+15 s, piso 135 s) y la GUI deriva la espera de fase 2 de
  reinicio/actualización de BDS/rollback/actualizador de suite de la misma
  escala (piso 450 s). Antes abortaban con el backup final aún en curso en
  mundos desde ~1,75 GB (~0,63 GB con un backup caliente activo). Detalle en
  `docs/INFORME_TIMEOUTS_CIERRE_2026-10-19.md`.
- Backups mucho más lentos de lo necesario con packs grandes: cada archivo se
  leía con `read(8 MiB)`, que en Windows reserva el búfer entero en cada
  llamada. Las lecturas se acotan ahora al tamaño del archivo; con ~12.000
  archivos de packs el empaquetado baja de ~114 s a ~11 s.

### Documentación y mantenimiento

- Enlaces de descarga del ZIP/checksum y registro de la publicación de 2.1.0,
  instrucciones de validación, recuperación y arquitectura del actualizador.
- Workflows de tests y Release solo manuales; push de ramas/tags y PR no
  inician jobs. Estas instrucciones se conservan al sincronizar repositorios.
- Guía del frontend y plan de apariencia sin referencias vigentes al asistente
  IA retirado (el plan conserva su registro histórico con una nota).
- Notas de diseño del worker de backups actualizadas: IPC en JSON UTF-8 (no
  `pickle`), timeouts escalados por tamaño y parsers vigentes.
- Suite de tests más rápida y estable: dos tests de `create_backup` ya no
  empaquetan los packs reales de la instalación, Hypothesis usa un perfil
  global sin deadline y el e2e del backup caliente ya no confunde el
  `.zip.tmp` en curso con un ZIP publicado.

Estos cambios posteriores a la Release no modifican el ZIP ni la etiqueta
2.1.0 ya publicados.

## [2.1.0] - 2026-10-15

Preparada el 15 de octubre y [publicada el 16 de octubre de 2026](https://github.com/guapo3266/minecraft-bedrock-server-suite/releases/tag/v2.1.0)
con ZIP Windows x64 y checksum. Procedencia, hash y alcance de la validación
en [ACTUALIZACIONES_SUITE.md](docs/ACTUALIZACIONES_SUITE.md).

### Añadido

- ZIP Windows x64 con CPython y dependencias incluidos, sin Git/Node/Python
  instalados y sin redistribuir BDS ni datos de ninguna instalación.
- Actualizador de la suite separado de BDS: comprueba Releases estables al
  abrir la GUI y mediante un botón manual, y exige confirmación para instalar.
- Descarga verificada con el SHA-256 de GitHub, manifiesto por archivo, lista
  positiva de rutas y rechazo de ZIPs inesperados, enlaces y alias NTFS.
- Reemplazo solo de archivos del programa que cambian, diario persistido,
  resguardo del código anterior y rollback ante fallo de copia o arranque.
- Cierre coordinado de Minecraft con comprobación del backup final por NDJSON,
  relevo a un auxiliar con Python independiente y reinicio del servidor si
  estaba encendido. Un fallo de reinicio se informa por separado.
- Recuperación mediante los lanzadores o `Recuperar_suite.bat` tras una
  interrupción. Los resguardos se conservan si la recuperación no completa.

### Alcance

- Compatible con instalaciones nuevas y con instalaciones previas de scripts.
  En checkouts Git se permite comprobar y descargar; no reemplazar el código.
- La Release pública no implica un despliegue en el servidor real; sincronizar
  o actualizar esa instalación requiere un pedido propio.

## [2.0.0] - 2026-10-15

Primera versión unificada de la suite. Esta entrada establece el punto de
partida de la numeración común; las funciones siguientes ya formaban parte
del producto y no se presentan como incorporaciones de este cambio.

### Versionado

- Fuente común `version.json` para backend, metadatos de API y la versión
  visible en **Más acciones → Acerca de**, tanto en español como en inglés.
- Campo `suite_version` en el estado HTTP/WebSocket; `installed_version`
  conserva su significado de versión del servidor BDS.
- Herramienta `tools/set_version.py` para actualizar los manifiestos npm y
  comprobar su coherencia con este historial. El build rechaza desajustes.
- Etiqueta Git local `v2.0.0` en cada repositorio para identificar su código.

### Funciones incluidas en este punto de partida

- Wrapper de consola y GUI web con consola en vivo, controles del servidor,
  métricas, conectividad y gestión de jugadores.
- Backups en caliente, programación, retención, validación y restauración
  compartida entre GUI y CLI, con staging y rollback.
- Actualización oficial de BDS con recuperación y vuelta a la versión anterior.
- Inventario de addons de solo lectura y asistente de comandos IA que requiere
  la aprobación del operador para ejecutar una propuesta.
- Interfaz ES/EN con apariencia personalizable y consola expandible.

### Estado al preparar 2.0.0

Se preparó e identificó localmente antes de publicar 2.1.0. Esa preparación no
incluyó sincronizar el servidor de producción.
