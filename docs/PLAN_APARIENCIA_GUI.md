# Plan de adaptación visual de la GUI — 2026-10-12

## Objetivo y alcance

Adaptar el sistema visual de Nokia WiFi Manager a la GUI React de Minecraft
Bedrock Server Suite: estructura flotante, materiales de vidrio, tipografía,
temas, fondos y controles de apariencia. No portar contenidos ni servicios de
administración de routers. El proyecto de referencia se consulta en solo lectura.

Este plan se redactó **antes de implementar**, después de leer las instrucciones
de ambos proyectos, los componentes funcionales del frontend destino, los módulos
de apariencia/renderizado del origen y su verificación de UX. Se inspeccionaron
visualmente la cabecera, la navegación y el diálogo de apariencia del origen,
sirviendo únicamente su frontend estático (sin conectar a un router).

**Actualización 2026-10-19:** el asistente IA experimental que mencionan los
invariantes, el drawer, la matriz de QA y las evidencias (`ai.png`) se retiró
(ver `CHANGELOG.md`). Esas menciones quedan como registro de la ronda del
2026-10-12 y no son requisitos vigentes; el resto del plan no cambia.

## Invariantes

- No modificar backend, API, WebSocket, locks, wrapper, mundos ni archivos de
  instalación. No arrancar BDS, restaurar mundos ni instalar actualizaciones
  durante el QA visual.
- Conservar consola, búsqueda, filtros, historial de comandos, autoscroll,
  comandos rápidos, métricas 1/6/24 h, conectividad, controles, jugadores,
  backups, addons, configuración, programación, actualizador y wizard.
- La IA sigue proponiendo; solo el usuario puede ejecutar un comando.
- Conservar los cambios preexistentes, especialmente la integración de Addons
  en `SidebarTabs.jsx` y sus traducciones. No resetear el repositorio.
- No sincronizar a producción, commitear ni publicar sin otro pedido.

## Diseño y navegación

1. Cabecera flotante equivalente al origen: marca de Minecraft, estado,
   selector ES/EN, cambio rápido de tema, Apariencia y menú de acciones existente.
2. Navegación inferior de vidrio: Servidor, Jugadores, Backups y Addons. El
   contenido conserva las responsabilidades actuales; no se duplican peticiones
   de estado ni sesiones WebSocket para crear vistas nuevas.
3. Contenido central con scroll independiente, márgenes seguros para cabecera y
   dock, encabezado de sección y superficies redondeadas con reflejos neutrales.
4. Consola y estado permanecen montados al cambiar de sección para conservar
   historial y entrada. La consola ocupa el área principal, con conectividad al
   costado en escritorio (debajo en móvil). Las vistas de gestión reutilizan los
   componentes actuales.
5. Material uniforme en métricas, listas, formularios, menús en portal, diálogos,
   drawer de IA y wizard. Sustituir neón, tilt y texto cifrado por el lenguaje
   sobrio del origen; no mantener dos estilos contradictorios.

## Personalización y almacenamiento

- Temas oscuro/claro y efectos completos/reducidos.
- Fondos JPEG, PNG y WebP de hasta 10 MiB; leer dimensiones antes de decodificar,
  rechazar más de 64 megapíxeles y normalizar a un lado máximo de 2560 píxeles.
- Imagen completa/llenar pantalla; zoom 25–180 %, encuadre X/Y 0–100 %,
  oscurecimiento independiente por tema 0–70 %, integrado/libre.
- Transparencia del material 0–100 % **sin modificar la opacidad del texto**.
- Lectura protegida con muestreo de píxeles decorativos y velos por superficie.
- Restablecer fondo elimina la imagen y reinicia el encuadre sin borrar el idioma
  ni modificar opciones funcionales del servidor.
- Preferencias en `localStorage` e imagen en IndexedDB con claves propias de esta
  aplicación, separadas del proyecto de origen. No subir imágenes ni usar URLs remotas.
- Ante cuota, modo privado o almacenamiento bloqueado, aplicar lo posible durante
  la sesión y mostrar un aviso; no afirmar que se guardó si no se confirmó.

## Arquitectura de implementación

- `src/appearance/`: configuración validada, dimensiones/normalización de imagen,
  composición de fondo, muestreo/contraste y worker. Mantener la procedencia.
- `src/hooks/useAppearance.js`: persistencia, concurrencia de importación/reset,
  sincronización de tema y gestión del ciclo de vida de URLs Blob.
- `GlassStage.jsx`: canvas decorativo y superficies vacías para cabecera/dock.
  El motor nunca recibe el DOM de consola, formularios ni IA.
- `Appearance.jsx`: diálogo accesible con controles y previsualización.
- `src/vendor/liquidglass.js`: snapshot local del motor del origen, con aviso
  MIT y sin CDN. El clonador de textarea usará `textContent`, no un sumidero HTML:
  conservar el canary de seguridad, no excluir el vendor para hacerlo pasar.
- `index.css`: tokens por tema y estilos compartidos. Adaptar componentes
  existentes en vez de alterar lógica de servicios o duplicar componentes.
- Fuentes locales Inter/JetBrains Mono y sus licencias OFL, sin peticiones externas.

## Rendimiento, accesibilidad y fallos

- Importación diferida del motor; renderizado por invalidación, no bucle continuo.
- DPR máximo 2; pausa con pestaña oculta; cancelar frames, observers, worker y
  listeners al desmontar, también con el doble montaje de StrictMode.
- WebGL fallido/contexto perdido/timeout: vidrio CSS suave y funcionalidad intacta.
- Efectos reducidos y preferencia del SO: no activar vidrio WebGL ni animaciones
  decorativas. El fondo personalizado sigue visible.
- Foco visible, etiquetas reales en todos los sliders, cierre Escape, foco
  restaurado, trampa de Tab y navegación del dock por flechas/Home/End.
- En móvil: cabecera refluida, dock sin desbordamiento, controles táctiles y
  diálogos con scroll interno y acciones siempre accesibles.

## Matriz de aceptación y verificación

1. Base antes de cambios: `npm test` → 3 archivos, 27 tests aprobados.
2. Tests puros: límites/defaults/corrupción de preferencias, cabeceras y límites de
   imágenes, geometría contain/cover, extremos de muestreo y contraste.
3. Regresiones: simetría ES/EN, canary sin HTML/ejecución dinámica e inventario de
   addons; lint y build obligatorios. No sustituir canaries por exclusiones.
4. Navegador sobre `dist/` con API/WS simulados: dashboard y las cuatro secciones,
   modales, comandos/filtros, confirmaciones, IA sin autoejecución y wizard.
5. Apariencia: claro/oscuro, transparencia 0/80/100 %, efectos completos/reducidos,
   carga/recarga/restablecimiento de imagen, encuadre, integrado/libre y errores.
6. Escritorio/móvil, teclado, reducción de movimiento y ausencia de errores JS.
7. Registrar evidencias y límites reales de verificación; no declarar operaciones
   de Minecraft verificadas en vivo a partir de una API simulada.

## Resultado de implementación y verificación

Implementado en este repositorio el 2026-10-12. No se modificó lógica de backend,
wrapper, comandos, backups ni aprobación humana de IA. Se conservaron los cambios
preexistentes de Addons. No hubo sincronización a producción ni publicación.

| Comprobación | Resultado observado |
| --- | --- |
| `npm run lint` en `gui_frontend/` | Aprobado, sin avisos |
| `npm test` en `gui_frontend/` | 4 archivos, **70 pruebas aprobadas** |
| `npm run build` en `gui_frontend/` | `dist/` reconstruido, sin aviso de tamaño de chunk; motor y Addons separados |
| `.venv\Scripts\python.exe -m ruff check .` | Aprobado |
| `.venv\Scripts\python.exe -m pytest tests -m "not e2e" -q --tb=short` | **1016 aprobadas, 2 e2e deseleccionadas**, 394.05 s |
| `python gui_frontend/tests/appearance-browser-check.py` | Recorrido completo aprobado; vidrio real `ready`, cero errores JS |
| `git diff --check` del alcance editado | Sin errores de espacios/diff |

El QA de navegador usa el **frontend compilado real** con HTTP estático temporal y
API/WebSocket simulados, sin importar el backend. Comprueba:

- Navegación, filtros de addons conservados al regresar, entrada/historial y
  filtros de consola; cancelación de confirmaciones sin enviar acciones.
- Configuración, programación, actualizador e IA: consultar no ejecuta comandos.
- Oscuro/claro, transparencia 0/80/100 %, zoom/encuadre/oscurecimiento,
  persistencia tras recarga y carga/reset real de una imagen mediante el input.
- Rechazo de SVG y aviso honesto cuando localStorage/IndexedDB están bloqueados:
  la imagen se aplica durante la sesión sin afirmar que se guardó.
- ES/EN, escritorio 1440×1000, móvil 390×844 y ancho mínimo 320 px, dock por
  teclado, Tab/Shift+Tab, Escape y restauración de foco.
- Wizard y fallo de carga con reintento; preferencia del SO de movimiento reducido;
  navegador con WebGL desactivado conserva el panel con vidrio CSS.

Se inspeccionaron las capturas finales y se corrigió el desbordamiento de campos
de configuración. Los selectores de apariencia, propiedades, wizard e inventario
usan el mismo control de vidrio. Las fuentes se sirven por `/assets` existente,
sin ampliar las rutas del backend ni depender de fuentes remotas.

Evidencias locales: `%LOCALAPPDATA%\Temp\opencode\bedrock-appearance-qa\results.json`
y capturas en esa misma carpeta (`desktop-dark.png`, `desktop-light.png`,
`appearance.png`, `mobile-appearance.png`, `custom-wallpaper.png`, `players.png`,
`backups.png`, `addons.png`, `ai.png` y modales). No se incorporan las capturas ni
datos generados a producción.

**Límite:** no se ejecutaron operaciones de Minecraft en vivo ni se arrancó BDS.
Las pruebas visuales no sustituyen comprobar una restauración/actualización real,
ni constituyen una auditoría completa de accesibilidad. El servidor estático de
referencia y los navegadores de QA se cerraron al terminar.

## Segunda ronda: jerarquía y menús (pedido posterior del usuario)

Plan acordado antes de editar: compactar encabezado/acciones, dar prioridad a la
consola y su entrada, reducir el peso de métricas sin quitar datos, mostrar
Configuración directamente y relegar Apariencia a un menú secundario. Conservar
el vidrio, fondos y funciones; no modificar backend ni ejecutar BDS.

Implementado:

- Una sola franja Servidor/acciones; se elimina la duplicación del estado.
- Consola principal, con alto adaptado al viewport y posición sticky en
  escritorio. Recursos compactos y conectividad a la derecha; debajo en móvil.
- Métricas completas: RAM/CPU/disco, disponibilidad/capacidad, aviso de disco bajo,
  versión BDS, sparklines y los tres rangos de historial.
- Configuración directa. Más acciones separa herramientas del servidor de
  Interfaz/Apariencia; soporte de flechas/Home/End/Escape y restauración de foco.
- Iniciar resaltado únicamente cuando está disponible. Detener/Reiniciar
  secundarios, conservando las confirmaciones y los mismos callbacks/guards.

Verificación de esta ronda:

- Frontend: lint sin avisos, **78 tests aprobados** (8 regresiones nuevas de
  disponibilidad/recursos) y `dist/` reconstruido.
- Python: Ruff aprobado y **20 tests dirigidos aprobados** (i18n y contrato de
  addons). No se repitió la suite completa de 1016 en esta ronda solo de frontend.
- Navegador: recorrido completo aprobado, vidrio real `ready`, cero errores JS;
  logs y formulario de comandos visibles sin scroll de página a **1440×1000,
  1280×800 y 1024×768**. Móvil revisado a 390×844 y 320×720; en móvil/ventanas de
  muy poca altura se permite scroll de página, sin ocultar controles.
- Se comprueban configuración directa, menú secundario por teclado, Start
  deshabilitado en marcha/resaltado apagado, cancelación de confirmaciones sin
  enviar acciones y persistencia de todos los ajustes de apariencia.

Evidencias nuevas: `%LOCALAPPDATA%\Temp\opencode\bedrock-hierarchy-qa\results.json`,
`desktop-dark.png`, `desktop-light.png`, `console-1024x768.png`,
`console-1280x800.png`, `server-stopped.png`, `secondary-menu.png` y capturas de
móvil/diálogos. Los datos y WebSocket siguen siendo simulados: no es una prueba
de operaciones reales de Minecraft. No se sincronizó ni publicó.

## Tercera ronda: conexión y teclado (corrección autorizada)

La revisión posterior encontró dos pendientes: cabecera con el último estado
«En línea» aun tras perder el WebSocket, y menús de comandos rápidos/backups sin
el mismo manejo de teclado que la cabecera. Se reprodujeron en el frontend
compilado con API/WS simulados, antes de corregirlos.

- `App.jsx` conserva el último estado de BDS, pero registra separadamente el
  estado del canal. `ServerStatus.jsx` y el título de la pestaña muestran
  Conectando/Reconectando sin uptime/latencia hasta recibir estado actualizado.
  Abrir el transporte, recibir logs o un pong no confirma el estado de BDS.
- Error/cierre limpian la latencia; los callbacks de sockets caducados se ignoran.
  No se cambia el contrato del canal, el backend, los guards de acciones ni se
  envía un stop por perder la conexión. El aviso live excluye el uptime para
  evitar anuncios nuevos por cada tick.
- `useActionMenu.js` unifica los tres menús: foco inicial, flechas con recorrido
  circular, Home/End, omisión de opciones ocupadas, Escape con retorno de foco,
  Tab/Shift+Tab hacia los controles vecinos y cierre al sacar el foco/clicar fuera.
  Confirmaciones y ejecución de comandos conservan sus callbacks originales.
- Los menús limitan su altura al espacio disponible. La prueba de reflujo halló
  además un cierre inmediato por un evento de scroll pendiente al revelar el
  botón: ahora el scroll externo cierra solo si el ancla realmente se movió;
  el scroll interno y el autoscroll de logs sin movimiento del ancla no cierran.

Verificación: **87 tests Vitest aprobados** (9 nuevos para estado de conexión),
lint sin avisos, Ruff aprobado y `dist/` reconstruido. El recorrido de navegador
completo pasa con cero errores JS. Incluye reconexión demorada, primer estado,
eventos de error/callbacks caducados instrumentados, traducciones, Tab/Shift+Tab,
foco al cancelar la eliminación del segundo backup, navegación que salta una
verificación ocupada y ausencia de acciones accidentales al abrir/navegar/cerrar.

Menús revisados también a **640×400 con DPR 2** (equivalente de reflujo al 200 %)
y **320×440 con interacción táctil emulada** (menor altura útil). No es zoom
nativo del navegador ni una prueba con teclado virtual/lector de pantalla en un
teléfono real; esas comprobaciones siguen pendientes. No se repitió la suite
Python completa porque no se modificó código de backend.

Evidencias en `bedrock-hierarchy-qa`: `connection-initial.png`,
`connection-reconnecting.png`, `quick-menu-keyboard.png`,
`backup-menu-keyboard.png`, `reflow-200-*-menu.png`, `mobile-short-*-menu.png` y
`results.json`. Sin operaciones BDS reales, sincronización, commits ni publicación.

## Actualización 2026-10-15: consola y descubrimiento

- La consola utiliza la altura disponible, con barras y registros más compactos
  y la misma fuente. Expandir/Reducir mantiene el componente y su estado;
  los avisos de producto pasan a Acerca de y los recursos/IP desplazan por separado.
- Personalizar reemplaza el botón de sol/luna en la cabecera. El cambio de tema
  está dentro del panel. Un consejo no modal aparece una vez al llegar al
  dashboard; no interrumpe el wizard, no roba el foco y se puede descartar.
- El consejo usa `bedrock-appearance-tip-seen`; las imágenes y preferencias
  conservan el almacenamiento local anterior. Una recarga no repite el consejo.
- Se comprobó el ancho interno de `.main-content`, además del ancho del documento,
  para detectar y corregir desbordamiento horizontal de la consola en móvil.
- Validación: lint, 88 pruebas Vitest, build y recorrido completo de navegador
  aprobados, sin errores JS. Verificación adicional del primer uso en ocho
  ventanas, con API/WS simulados. La validación Python y el alcance de la
  sincronización posterior están en `INFORME_ACTUALIZACION_2026-10-15.md`.
