# Actualización de la suite — 2026-10-15

## Alcance

La suite pública incluye el wrapper Python, la GUI web FastAPI/React, el
inventario de addons y el asistente de comandos con aprobación humana.
Conserva las mejoras de recuperación de BDS, rutas de mundos, backups y
seguridad descritas en `INFORME_ADDONS.md`, `INFORME_FIXES_2026-10-03.md`,
`ARCHITECTURE.md` y `API_CONTRACT.md`.

La consola aprovecha la altura disponible y conserva filtros, historial,
borrador y lectura pausada al expandir/reducir. Personalizar está visible en la
cabecera; el consejo de primer uso no interrumpe el wizard ni abre el panel
automáticamente. El aviso de producto está en Más acciones → Acerca de.
El área interna de contenido también se limita al ancho móvil.

## Ejecución y rutas

`iniciar_gui.bat` abre la GUI web en el navegador y `iniciar_servidor.bat`
ejecuta el wrapper de consola. Ambos usan Python y los módulos de esta
instalación. Los procesos hijos usan el mismo intérprete, `server_wrapper.py`
y `backup_worker.py`, con sus canales de consola y eventos NDJSON.

Las rutas parten de los módulos, no del directorio de trabajo del usuario.
Los backups mantienen el destino por instalación:
`../../Backups_Minecraft/auto_backups/<carpeta>`.
El frontend se sirve desde `gui_frontend/dist/`; Node solo se necesita para
reconstruirlo durante el desarrollo. La IA permanece disponible en la GUI
web y requiere aprobación humana para ejecutar cualquier propuesta.

## Identidad y documentación

README ES/EN, guía del frontend, arquitectura y contrato API describen el
perfil público. Cada carpeta mantiene su propio `AGENTS.md`; las
instrucciones locales de los destinos no se fuerzan al Git público.

Los comentarios activos y avisos identifican Minecraft Bedrock Server Suite.
Los nombres de los proyectos de origen quedan en la procedencia histórica y
sus copyrights. Se conservan los textos MIT/OFL y la huella del motor vendor.

## Limpieza y validación

El código retirado y los artefactos de desarrollo se resguardan fuera del
repositorio. Mundos, packs, datos de instalación y binarios Mojang permanecen
excluidos. Esta revisión no cambia la instalación de producción.

Las comprobaciones de esta revisión se ejecutan sobre el árbol público:
Ruff, pytest con `-m "not e2e"`, lint y pruebas del frontend, build Vite y QA
con API/WS simulados. No se ejecuta BDS para comprobar estos cambios.

Resultados de esta revisión:

- Ruff: aprobado.
- `pytest tests -m "not e2e" -q`: **1018 aprobadas, 2 omitidas y 2 excluidas**.
  Las omitidas requieren un mundo real con `db/` o los archivos de una
  instalación BDS; no se reemplaza esa evidencia con datos ficticios.
- Frontend: lint y **88 pruebas Vitest** aprobados; build Vite reconstruido.
- QA del `dist/` en Chrome: vidrio `ready`, navegación, consola, temas,
  fondos, wizard, i18n, IA con aprobación humana, efectos reducidos y fallback
  sin WebGL aprobados. Sin errores JavaScript. API y WebSocket simulados:
  no acredita operaciones reales de Minecraft.


## Sincronización de la reversión

Se alinearon el asistente inicial y el cierre WebSocket con la reversión
validada en TESTTEST. Se conservaron las adaptaciones propias de rutas,
subprocesos Python, documentación y pruebas de este repositorio. Los assets
obsoletos se resguardaron fuera del árbol y `dist/` se reconstruyó aquí; sus
12 archivos coinciden por SHA-256 con el build validado de TESTTEST.

Nueva validación sobre este árbol: **1014 pruebas Python aprobadas, 2 omitidas
por requerir archivos de una instalación real y 2 e2e excluidas**. Ruff, lint,
**88 pruebas del frontend** y build aprobados. La sincronización es local,
sin push, release ni publicación de binarios.
