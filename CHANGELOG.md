# Historial de cambios

La versión de **Minecraft Bedrock Server Suite** se define en `version.json` y
es independiente de la versión de Minecraft Bedrock Dedicated Server (BDS).
Este historial empieza en 2.0.0; el desarrollo anterior se conserva en Git y en
los informes de `docs/`, sin asignarle versiones retrospectivas.

## [Sin publicar]

Los próximos cambios se documentarán aquí antes de preparar otra versión.

## [2.1.0] - 2026-10-15

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
- Preparación y pruebas locales. Publicación y despliegue requieren pedido expreso.

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

### Estado de publicación

Preparada e identificada localmente. Esta versión no implica un push a GitHub
ni una sincronización con el servidor de producción.
