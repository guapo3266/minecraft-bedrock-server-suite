# Actualización y sincronización local — 2026-10-15

## Alcance

Integración de los cambios pendientes de TESTTEST: inventario de addons,
endurecimiento de recuperación de BDS y rutas de mundos, asistente de comandos,
GUI de vidrio con fondos locales y fuentes incluidas, y fuentes del portable.
Los detalles previos permanecen en `INFORME_ADDONS.md`,
`INFORME_FIXES_2026-10-03.md` y `PLAN_APARIENCIA_GUI.md`.

La consola aprovecha la altura disponible y conserva filtros, historial,
borrador y lectura pausada al expandir/reducir. Personalizar es visible en la
cabecera; el consejo no modal de primer uso no interrumpe el wizard ni abre el
panel automáticamente. El aviso de producto está en Más acciones → Acerca de.
El área interna de contenido también se limita al ancho móvil.

README ES/EN, guía del frontend, arquitectura, contrato API e instrucciones de
empaquetado reflejan el código vigente. Cada carpeta conserva su propio
`AGENTS.md`; estos archivos no se copian entre instalaciones ni se publican.

## Limpieza

Las demos de referencia y sus imágenes, capturas de QA, diff temporal, PDF y
su material de render, y el proyecto auxiliar de vídeo se resguardan fuera de
los repositorios. No se eliminan estos trabajos personales ni se incorporan
sus medios al repo público. El código activo usa el módulo vendor local y
fuentes MIT/OFL con sus avisos; no depende de las demos apartadas.

Los datos de instalación y binarios Mojang siguen excluidos. El portable ya
generado y los entornos/builds locales también quedan fuera de Git. Esta
sincronización actualiza fuentes y `dist/`, no recompila un EXE existente.

## Validación

- `python -m ruff check .`: aprobado.
- `python -m pytest tests -m "not e2e" -q`: **1038 aprobadas, 2 excluidas**,
  con pytest, Hypothesis y httpx disponibles. Sin e2e contra BDS.
- Frontend: lint y **88 pruebas Vitest** aprobados; build Vite reconstruido.
- QA de navegador del `dist/`: vidrio real `ready`, cero errores JS,
  subida/recarga/reset de fondos, temas, teclado, menús, wizard, conexión WS,
  aprobación humana de IA, efectos reducidos y fallback sin WebGL aprobados.
  API y WS simulados: no acredita operaciones reales de Minecraft.
- Comprobaciones adicionales del primer uso a 1366×768, 1280×600, 1024×768,
  900×700, 720×800, 640×400, 390×844 y 320×720: acceso y consejo dentro de la
  ventana, sin desbordamiento horizontal interno, persistencia de tema y
  consejo, foco al cerrar y descarte con almacenamiento bloqueado.
  En ventanas muy cortas se permite scroll vertical de la página.

## Sincronización solicitada

- TESTTEST: commit de fuentes, tests, documentación y frontend compilado.
- Repo público local: misma instantánea de proyecto, con su `AGENTS.md`
  independiente excluido de Git. Commit local; **sin push**.
- Servidor personal: solo runtime y recursos, sin node_modules, tests, docs,
  tooling de build/QA, binarios Mojang ni datos de instalación.
- La verificación final del sync compara hashes del código, conserva el estado
  de arranque de producción y comprueba que los datos privados no cambien.

Verificación de copia completada: **301 archivos de proyecto** en el repo
público local y **165 archivos de runtime** en producción coinciden por SHA-256
con TESTTEST. Se resguardaron 8 archivos obsoletos del repo público, 4 bundles
anteriores de producción, `gui_frontend/node_modules/` y `tools/test_gui_e2e.py`.
Los directorios raíz `tests/` y `docs/` ya no estaban presentes en producción.

Los **15 459 archivos privados** inventariados mantienen tamaño/mtime; además
se compararon hashes de propiedades/JSON raíz y `level.dat`. Producción estaba
apagada y se conserva apagada: no hubo reinicio necesario ni ejecución BDS para
validar la copia. `origin/main` permanece en la referencia local anterior.
El resguardo externo conserva el código reemplazado, artefactos apartados,
manifiestos y resultados del sync; no se incorpora a Git.

## Corrección de identidad e instrucciones de los destinos

Se retiraron las etiquetas operativas heredadas de otra aplicación en el motor,
preferencias, tokens CSS y SpotlightCard. La guía del frontend y los avisos
identifican el producto como Minecraft Bedrock Server Suite. Los nombres del
proyecto de origen quedan en la procedencia histórica y en su copyright MIT;
el texto de las licencias se conserva. El aviso del motor registra además la
huella SHA-256 del módulo vigente.

El `AGENTS.md` local del repositorio público se revisó completo: reemplaza los
comandos y contratos antiguos, define su papel como destino de TESTTEST y
documenta frontend, IA, addons y portable. No se limita a un apéndice nuevo.
TESTTEST y producción mantienen instrucciones propias; los archivos locales
de los destinos se resguardan por separado y no se fuerzan al Git público.

Esta corrección cambia comentarios y documentación. Los resultados completos
de Python indicados arriba corresponden a la integración previa; para esta
corrección aprobaron lint, las 88 pruebas y el build del frontend. Los 12
archivos compilados resultaron idénticos por SHA-256 a los anteriores: la
limpieza de comentarios no cambió el JavaScript/CSS servido. Las licencias
se compararon con la revisión previa y se conservan sin cambios.
