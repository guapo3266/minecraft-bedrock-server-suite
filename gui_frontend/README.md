# gui_frontend — React + Vite (dashboard de la suite)

Fuente del panel web servido por `server_gui_server.py`. El `dist/` compilado
viaja commiteado y se sirve tal cual (no hace falta Node en runtime).

## Desarrollo

```bash
cd gui_frontend
npm ci        # instalación reproducible (usa package-lock.json)
npm run dev   # entorno local
npm run lint  # oxlint
npm test      # Vitest: apariencia, i18n, addons y canary de seguridad
```

## Build / sincronización de `dist/`

```bash
cd gui_frontend
npm run build   # regenera dist/
```

`dist/` debe reconstruirse siempre que cambie el frontend antes de
sincronizar a `..\Servidor de Guapo` o al repo público
(`..\minecraft-bedrock-server-suite`). No commitear mundos, packs ni
configs del servidor (ver `.gitignore`).

## Apariencia y estructura

El sistema visual de Minecraft Bedrock Server Suite reúne consola, recursos,
fondos locales y navegación de la instalación. Diseño e implementación:
[`docs/PLAN_APARIENCIA_GUI.md`](../docs/PLAN_APARIENCIA_GUI.md). La procedencia de
los componentes adaptados y sus licencias está en los archivos `NOTICE.md`.

- `src/appearance/`: preferencias validadas, límites/cabeceras de imágenes,
  composición del fondo y protección de lectura con worker.
- `src/hooks/useAppearance.js`: `localStorage` (`bedrock-appearance`), IndexedDB
  (base `bedrock-appearance`, store `images`) y URLs Blob con revocación.
- `ServerStatus.jsx`: diferencia conexión de la GUI de estado de BDS. Cabecera
  y título de pestaña muestran Conectando/Reconectando hasta recibir un `init`
  con estado o un mensaje `status` de la sesión actual; ocultan uptime/latencia
  obsoletos sin alterar el estado del servidor ni enviar acciones.
- `src/hooks/useActionMenu.js`: foco y cierre compartidos por los menús de
  cabecera, comandos rápidos y backups, incluidas opciones deshabilitadas.
- `AboutModal.jsx`: muestra la versión común de `../version.json`, incorporada
  al build; no confundirla con la versión de Minecraft en el dashboard.
- `src/hooks/useSuiteUpdate.js`/`SuiteUpdateModal.jsx`: consulta al abrir,
  comprobación manual, confirmación de instalación y progreso/reconexión tras
  cerrar la GUI. `sessionStorage` (`bedrock-suite-updating`) conserva el flujo
  durante el relevo. `src/suiteUpdateLogic.js` define fases activas y terminales;
  los resultados de rollback o fallo de reinicio siguen visibles.
- `GlassStage.jsx`: canvas decorativo, cabecera/dock vacíos para el motor local;
  **no captura el DOM de consola, formularios ni IA**. WebGL se importa bajo
  demanda y cae a CSS ante fallos. Pausa en segundo plano.
- `Appearance.jsx`/`GlassSelect.jsx`: diálogo y controles accesibles; el botón del
  selector mantiene el foco y soporta flechas, Home/End, Escape y búsqueda al teclear.
- `Navbar.jsx`/`AppearanceTip.jsx`: acceso visible **Personalizar** (Fondo en la
  ventana más estrecha) y consejo no modal al entrar por primera vez al panel.
  La clave `bedrock-appearance-tip-seen` registra que ya se mostró; se descarta
  con la cruz, al abrir Apariencia o al interactuar fuera. Si el almacenamiento
  está bloqueado, el descarte funciona durante la sesión. El wizard no lo muestra.
- `Dock.jsx`: las cuatro vistas; la consola permanece montada al navegar. Addons
  se importa al visitarlo y conserva sus filtros mientras dura la sesión.
- `index.css`: tokens por tema, material y puente visual para los componentes
  funcionales. Inter y JetBrains Mono están en `src/assets/fonts/`; Vite los
  publica con hash bajo `/assets`, compatible con el backend sin nuevas rutas.
- Licencias: `src/appearance/NOTICE.md`, `src/vendor/NOTICE.md` y
  `public/assets/fonts/OFL.txt` (también incluido en `dist/`).

Transparencia 0–100 % modifica **solo el material**. Lectura protegida agrega el
velo requerido por el fondo; por eso 100 % no obliga a quitar ese velo. El modo
reducido (o la preferencia del SO) evita WebGL y movimiento decorativo. El fondo
no depende de un CDN ni se envía mediante la API.

### Jerarquía de uso

Servidor y acciones comparten una franja compacta. El estado se muestra una sola
vez, en la cabecera. La consola es el área principal; las métricas conservan
valores, alertas, gráficas y rangos 1/6/24 h en un panel compacto a su derecha,
seguido de conectividad. En móvil se apilan después de la consola.

**Configuración** abre directamente `server.properties`; **Personalizar** abre
Apariencia y reemplaza el antiguo acceso de sol/luna. El tema se elige dentro
del diálogo. **Más acciones** agrupa Programación, Actualización BDS,
**Actualizar la suite** y **Acerca de**, donde están la versión del producto,
Administración local y el aviso de independencia de Mojang/Microsoft.
El menú indica si hay una nueva versión; comprobar no instala nada. La
confirmación explica la conservación de datos y, si Minecraft está encendido,
su cierre, backup final y reinicio. Mientras se actualiza, los controles y los
guards HTTP/WS bloquean operaciones incompatibles. Detalles de recuperación:
[`ACTUALIZACIONES_SUITE.md`](../docs/ACTUALIZACIONES_SUITE.md).
Este menú y los
de comandos rápidos/backups permiten flechas y Home/End; Escape restaura el foco
al botón correcto y Tab/Shift+Tab salen hacia sus controles vecinos. Abrir o
navegar no ejecuta nada; las confirmaciones destructivas siguen intactas. Los
menús caben en la ventana y su scroll interno no provoca un cierre. Apariencia
sigue disponible durante el setup y ante
fallos de carga. Iniciar recibe el acento principal solo al estar apagado; los
guards de disponibilidad y las confirmaciones de Detener/Reiniciar no cambian.

La consola ocupa la altura disponible sin el antiguo tope de 680 px. Sus barras
y separación de registros se compactaron sin reducir la fuente de los logs.
**Expandir/Reducir** aprovecha el área central y conserva el mismo componente,
incluidos búsqueda, filtros, historial, borrador y lectura pausada; Escape reduce
la consola después de cerrar cualquier menú o diálogo superior. Al navegar a
otra vista se sale del modo expandido. En escritorio, el panel de recursos/IP
se desplaza por separado; en móvil se apila y permite scroll de página.

## QA de navegador (opt-in, sin BDS)

Después del build, desde la raíz del repositorio:

```powershell
python gui_frontend/tests/appearance-browser-check.py
```

Requiere **Playwright Python y Google Chrome local**; son opcionales y no se
añadieron a las dependencias de runtime ni a CI. El script sirve `dist/` con un
HTTP temporal de loopback e intercepta API/WS en el navegador con fixtures. No
importa el backend ni inicia el wrapper/BDS. Comprueba navegación, consola,
confirmaciones, IA con aprobación humana, preferencias, subida/recarga/reset de
imagen, ES/EN, móvil, teclado, wizard, reducción del SO y fallback sin WebGL.
Comprueba además que logs y entrada de comandos estén dentro del área útil sin
scroll de página a 1440×1000, 1280×800 y 1024×768, y la distinción encendido/apagado.
Prueba pérdida/reconexión de WS con `init` demorado, error, callbacks de una sesión
caducada, reinicio de latencia, menús por teclado, foco tras cancelar, opciones
ocupadas y ausencia de acciones accidentales. Revisa menús a 640×400 con DPR 2
(reflujo equivalente al 200 %) y móvil a 320×440 (menor altura útil). Estas dos
últimas son emulaciones: no sustituyen zoom nativo ni teclado virtual de un
teléfono real.
Escribe capturas/resultados en `%LOCALAPPDATA%\Temp\opencode\bedrock-hierarchy-qa`
(las evidencias de la primera adaptación se conservan en `bedrock-appearance-qa`).
No demuestra operaciones Minecraft reales.
