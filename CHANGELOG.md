# Historial de cambios

La versión de **Minecraft Bedrock Server Suite** se define en `version.json` y
es independiente de la versión de Minecraft Bedrock Dedicated Server (BDS).
Este historial empieza en 2.0.0; el desarrollo anterior se conserva en Git y en
los informes de `docs/`, sin asignarle versiones retrospectivas.

## [Sin publicar]

Los próximos cambios se documentarán aquí antes de preparar otra versión.

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
