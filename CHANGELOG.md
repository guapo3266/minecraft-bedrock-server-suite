# Historial de cambios

La versión de **Minecraft Bedrock Server Suite** se define en `version.json` y
es independiente de la versión de Minecraft Bedrock Dedicated Server (BDS).
Este historial empieza en 2.0.0; el desarrollo anterior se conserva en Git y en
los informes de `docs/`, sin asignarle versiones retrospectivas.

## [2.2.2] - 2026-10-22

Actualización de seguridad sobre 2.2.1 por el
[incidente de los certificados de eMudhra/emSign](https://discuss.python.org/t/information-for-python-users-regarding-emudhra-emsign-ca-certificate-security-incident/109576).
Solo cambia el almacén de certificados con el que la suite valida HTTPS; el
código es el de 2.2.1. Se instala desde **Más acciones → Actualizar la suite**
(siempre con confirmación) o con el ZIP de la Release. Mundos, propiedades,
packs, backups y configuración quedan fuera del reemplazo.

### Seguridad

- El ZIP lleva `certifi` 2026.10.19. Hasta 2.2.1 llevaba 2026.7.22, que aún
  confiaba en la raíz `emSign ECC Root CA - G3`. Con las claves comprometidas de
  sus intermedias, alguien con control de la red (MITM) podía hacerse pasar por
  GitHub o por Mojang ante la suite: la comprobación y descarga de
  actualizaciones de la suite y la descarga de BDS. No se encontró evidencia de
  explotación.
- `requirements.txt` exige `certifi>=2026.10.19`: en una instalación desde
  código, el lanzador refresca el `.venv` la próxima vez que se abre.

**Si actualizas desde 2.2.1 o anterior**: la descarga de 2.2.2 la hace todavía
la versión instalada, con el certifi antiguo. Si sospechas de tu red, descarga
el ZIP con un navegador actualizado y compara su SHA-256
(`Get-FileHash BedrockSuite-Windows-x64.zip`) con el de la página de la Release.

**Instalación desde código (`.venv`)**: ese refresco lo descarga el pip del
propio `.venv`. Si es anterior a 26.2.2 (Python 3.11 crea los entornos con pip
24.0), actualízalo antes de abrir el lanzador, con el comando del aviso de
Python (el wheel va fijado por hash):

```powershell
.venv\Scripts\python.exe -m pip install "pip @ https://files.pythonhosted.org/packages/3f/06/3e4420302363fbb71be3c7f35ce042f54bfca330e3e66b3a2e3c4cca579f/pip-26.2.2-py3-none-any.whl#sha256=fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70"
```

Lo mismo al recrear un `.venv`: créalo con `python -m venv .venv`, aplica ese
comando y solo después abre el lanzador. Si lo crea el lanzador, descarga las
dependencias con el pip antiguo.

### Documentación y mantenimiento

- Tests: `test_restart_fase2_espera_backup_final_y_arranca` fallaba de forma
  intermitente en la suite completa. Armaba sus temporizadores de reloj antes
  de abrir el cliente: un parón de más de 0,3 s los dejaba vencidos y el
  reinicio veía el wrapper ya terminado, no enviaba `stop` y relanzaba directo.
  Ahora los plazos se cuentan desde que el `stop` llega al wrapper. El código
  de producción no cambia.
- Registro de la publicación de 2.2.1 (hash, procedencia y evidencia), con la
  prueba de actualización real desde el ZIP publicado de 2.2.0.

## [2.2.1] - 2026-10-21

[Publicada el 22 de octubre de 2026](https://github.com/guapo3266/minecraft-bedrock-server-suite/releases/tag/v2.2.1)
con ZIP Windows x64 y checksum. Procedencia, hash y alcance de la validación
en [ACTUALIZACIONES_SUITE.md](docs/ACTUALIZACIONES_SUITE.md).

Correcciones sobre 2.2.0: los 31 hallazgos de la revisión del 21 de octubre de
2026 (detalle en [INFORME_FIXES_2026-10-21.md](docs/INFORME_FIXES_2026-10-21.md)).
Se instala desde **Más acciones → Actualizar la suite** (siempre con
confirmación) o con el ZIP de la Release. Mundos, propiedades, packs, backups y
configuración quedan fuera del reemplazo.

**Si actualizas desde 2.2.0**: si la GUI se abrió sola al terminar la
actualización anterior, ciérrala y ábrela con `iniciar_gui.bat` antes de
actualizar; si no, la actualización se detiene al prepararse (sin tocar
Minecraft). La actualización a 2.2.1 la hace todavía el auxiliar de 2.2.0: las
correcciones del actualizador (proxy, reanudar Minecraft, `gui.log`) rigen a
partir de la siguiente. Ver
[qué corrección rige en cada actualización](docs/ACTUALIZACIONES_SUITE.md#qué-corrección-rige-en-cada-actualización).

### Corregido

- Backups
  - Una carpeta de backups o una instalación con corchetes en la ruta (por
    ejemplo `D:\Respaldos [HDD]`) ya no deja la lista vacía en la GUI y en la
    consola ni impide rotar los backups (el disco se llenaba) o recuperar una
    actualización de BDS interrumpida.
  - Dos instalaciones con el mismo nombre de carpeta (`...\Survival\Suite` y
    `...\Creative\Suite`) ya no comparten la carpeta de backups: la primera que
    hace un backup se la queda y la otra usa `<nombre>-<id>`. Mover la
    instalación conserva su carpeta; una copia recibe una propia.
  - El backup en frío se rechaza si un servidor de esta instalación está en
    marcha fuera de la GUI (copiaba el mundo mientras se escribía).
  - Si la GUI se cierra a la fuerza con Minecraft encendido, el servidor sigue
    haciendo sus backups, sale de `save hold` y hace el backup de cierre.
  - Un archivo con fecha anterior a 1980 ya no hace fallar todos los backups.
  - Una carpeta del mundo que no se puede leer (permisos, OneDrive sin
    conexión) hace fallar el backup en vez de publicar uno incompleto que la
    restauración aceptaba.
  - El backup en caliente ya no incluye el contenido de una junction en
    `behavior_packs` o `resource_packs` del mundo.
  - Verificar un backup con datos comprimidos dañados lo marca como corrupto:
    la GUI daba error 500 y `tools/verify_backups.py` se detenía sin marcarlo ni
    revisar los siguientes. Un ZIP que no se puede leer (bloqueado) ya no se
    marca: la herramienta lo avisa y sale con código 2.
  - La pestaña **Backups** se actualiza sola cuando termina un backup, se rota,
    se borra o cambia la carpeta.
  - Restaurar un backup ya no cambia la hora del «último backup».
- Actualizaciones
  - Actualizar o revertir BDS conserva la configuración que editaste
    (`config/default/permissions.json`, `packetlimitconfig.json`,
    `profanity_filter.wlist`); la versión de fábrica nueva queda en
    `data/bds_config_defaults/` para comparar.
  - La ventana de actualizar BDS ya no queda en «Actualizando BDS…» si se
    cerraba y se volvía a abrir durante la actualización.
  - La segunda actualización de la suite ya no falla porque la GUI relanzada
    tiene abierto su log; ese log pasa a `data/suite_updates/gui.log`.
  - Mover o copiar la carpeta de la suite después de actualizarla ya no impide
    abrir la GUI ni el servidor. Si una recuperación falla de verdad, el
    lanzador deja el mensaje a la vista.
  - La actualización de la suite funciona con un proxy configurado en Windows
    (antes se revertía siempre). Al terminar, reanudar Minecraft espera el
    backup inicial y tolera errores sueltos (antes informaba «Minecraft no se
    reinició» a los 75 s). Ver en la guía [qué corrección rige en cada
    actualización](docs/ACTUALIZACIONES_SUITE.md#qué-corrección-rige-en-cada-actualización).
- GUI y servidor
  - Una GUI sin permisos de administrador ya no deja lanzar otro servidor
    mientras el wrapper corre como administrador.
  - La GUI ya no se cierra sin aviso si otra aplicación toma su puerto justo al
    arrancar.
  - En modo LAN la GUI ya no cambia de puerto en silencio: si está ocupado lo
    avisa (la regla del firewall y la URL del móvil son de ese puerto).
  - El historial cierra las sesiones de los jugadores que seguían conectados
    cuando el servidor se detuvo o cayó.
  - Expulsar, banear y las demás acciones de jugador ya no dicen «enviado»
    cuando el servidor rechazó el comando.
  - La tarjeta **Cómo invitar** muestra el puerto nuevo tras cambiarlo y
    reiniciar.
  - El asistente inicial no deja saltar al final sin guardar la configuración e
    instalar BDS, y sus errores se ven.
  - La pestaña **Addons** filtrada por tipo muestra el aviso de una referencia
    de tipo cruzado junto a esa referencia.
  - La API responde 400 (no 500) a un cuerpo JSON que no es un objeto, y
    `POST /api/schedule` ya no guarda `[]` como un objeto vacío.
- Lanzadores y herramientas
  - Los lanzadores ya no dejan variables en la ventana de cmd: un
    `iniciar_gui.bat` abierto después de `iniciar_gui_lan.bat` en la misma
    ventana abría la GUI a la red local.
  - `iniciar_gui.bat` (ZIP con Python incluido) deja a la vista el error si la
    GUI no arranca.
  - `configurar_antivirus.bat` ya no muestra caracteres rotos (`aÃ±ade`) ni
    anuncia «[OK]» si Windows Defender no está activo.
  - `tools/enable_beta_apis_v2.py` ya no borra el respaldo que acaba de crear.
  - `tools/update_items.py` pasa a ser un alias de `update_items_v2.py`: bajaba
    los packs de 1.0.6 a 1.0.5 y sobrescribía sin respaldo. `update_items_v2.py`
    respalda `main.js` y avisa si falta el addon.

### Documentación y mantenimiento

- Registro de la publicación de 2.2.0 (hash, procedencia y evidencia), con la
  prueba de actualización real desde el ZIP publicado de 2.1.1.
- Guía de actualizaciones: qué corrección rige en cada actualización y la salida
  de los dos casos que la propia 2.2.0 no resuelve.
- Tests: dos tests escribían en los datos de la instalación en la que se
  ejecutaban (registro de jugadores y versión anterior de BDS);
  `tests/conftest.py` los aísla.

## [2.2.0] - 2026-10-21

[Publicada el 21 de octubre de 2026](https://github.com/guapo3266/minecraft-bedrock-server-suite/releases/tag/v2.2.0)
con ZIP Windows x64 y checksum. Procedencia, hash y alcance de la validación
en [ACTUALIZACIONES_SUITE.md](docs/ACTUALIZACIONES_SUITE.md).

Nueva función y correcciones sobre 2.1.1. Se instala desde **Más acciones →
Actualizar la suite** (siempre con confirmación) o con el ZIP de la Release.
Mundos, propiedades, packs, backups y configuración quedan fuera del reemplazo.

### Añadido

- La pestaña **Backups** muestra la carpeta donde se guardan y permite
  cambiarla. Los backups van a `<carpeta elegida>\<nombre del servidor>`, así
  dos servidores no mezclan su rotación. Dentro de la carpeta del servidor
  solo se admite `backups\`, que viaja con la instalación si se copia a otro
  disco o a un USB. Sin cambiarla todo sigue igual
  (`..\..\Backups_Minecraft\auto_backups\<servidor>`); los backups existentes
  no se mueven y `configurar_antivirus.bat` excluye la carpeta nueva.

### Corregido

- Restaurar un backup ya no devuelve los packs que distribuye BDS (vanilla,
  chemistry, editor, experimental, librerías de scripts): tras actualizar BDS,
  restaurar un backup anterior dejaba el ejecutable nuevo con los packs
  vanilla viejos. Los addons se siguen restaurando. Cada instalación de BDS
  desde la suite anota sus carpetas en `data/bds_shipped_packs.json`.
- El reinicio diario ya no reinicia un servidor recién arrancado cuando a la
  hora programada estaba apagado, y el backup diario en frío no repite el que
  el wrapper ya hizo en caliente (bloqueaba **Iniciar** tras el primer
  **Detener** del día).
- Reiniciar, actualizar BDS o la suite durante el backup inicial del wrapper
  ya no se cancela a los 75 s para después apagar el servidor igualmente.
- La ventana de actualización de la suite ya no queda «en curso» para siempre
  si su aviso de progreso quedó atrasado (GUI cerrada a mitad, auxiliar que no
  arrancó, último aviso sin guardar): muestra el resultado que registra el
  diario de la actualización y permite reintentar. Una pestaña que recordaba una
  actualización en curso también deja de esperarla si el servidor ya no tiene
  ninguna registrada.
- Si no se puede guardar la versión anterior de BDS, la actualización ya no se
  revierte en silencio en el siguiente arranque.
- Los backups en caliente funcionan con mundos cuyo nombre lleva comas.
- Guardar `server.properties` desde la GUI ya no falla con acentos guardados en
  ANSI ni duplica claves escritas con otras mayúsculas o espacios.
- La restauración por consola no actúa mientras el wrapper hace su backup
  inicial o final, aunque BDS no esté en ejecución.
- Tras actualizar la suite, la GUI nueva se desbloquea sola aunque falle la
  confirmación del auxiliar.
- La lista de backups ya no falla si la rotación borra un ZIP en ese momento.
- `iniciar_servidor.bat` vuelve a arrancar el servidor: desde agosto se
  cerraba con «No se esperaba . en este momento.» justo después de comprobar
  BDS. Con el Python incluido en el ZIP, además, ahora ofrece descargar BDS si
  falta en lugar de intentar lanzar un ejecutable inexistente.
- `iniciar_gui_lan.bat` ya no muestra el aviso de fallo del firewall cuando la
  regla sí se creó.
- Abrir una segunda GUI, el wrapper o la restauración por consola mientras otra
  ventana restaura un backup o actualiza BDS ya no deshace esa operación a mitad
  creyéndola interrumpida: las operaciones que reescriben archivos de la
  instalación se excluyen entre procesos.
- La restauración por consola vuelve a comprobar que el servidor esté apagado
  después de escribir `SI`, y mientras restaura nadie puede arrancarlo.
- Si se cortaba una vuelta a la versión anterior de BDS, la recuperación dejaba
  esa copia incompleta y un segundo intento mezclaba versiones. Ahora la copia
  queda entera.
- Reiniciar o actualizar justo después de arrancar ya no se cancela a los 75 s
  si el backup inicial empieza en ese momento.
- Los packs cuya carpeta es un enlace o junction ya no se restauran fuera de la
  instalación ni se incluyen en los backups.
- Los backups en caliente funcionan con archivos de más de 2 GiB.
- Guardar solo algunos ajustes de programación por la API conserva los demás.

### Documentación y mantenimiento

- El README empieza con capturas de la GUI y un resumen de lo que hace la suite.
- Un test comprueba que el ZIP lleve todos los módulos que importa el programa
  y que una instalación 2.1.x pueda instalarlo.
- Registro de la publicación de 2.1.1 (hash, procedencia y evidencia) en la
  guía de versionado.
- Guía de actualizaciones: alcance real de la QA de 2.1.1 (no ejercitó el
  auxiliar de 2.1.0), problema conocido al actualizar desde 2.1.0 y cómo
  salir de él, conteo exacto de archivos del ZIP y publicación paso a paso con
  GitHub CLI.
- Las notas de cada Release convierten los enlaces relativos del CHANGELOG en
  enlaces al repositorio (`tools/release_notes.py`): copiados tal cual daban 404.
- README, arquitectura y contrato de API al día con los cambios de restauración,
  programación diaria y actualización de esta versión.

## [2.1.1] - 2026-10-20

[Publicada el 20 de octubre de 2026](https://github.com/guapo3266/minecraft-bedrock-server-suite/releases/tag/v2.1.1)
con ZIP Windows x64 y checksum. Procedencia, hash y alcance de la validación
en [ACTUALIZACIONES_SUITE.md](docs/ACTUALIZACIONES_SUITE.md).

Corrección distribuible de 2.1.0. Se instala desde **Más acciones → Actualizar
la suite** (siempre con confirmación) o con el ZIP de la Release. Mundos,
propiedades, packs, backups y configuración quedan fuera del reemplazo.

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
  archivos de packs el empaquetado baja de ~114 s a ~11 s. Además, PNG/OGG/MP3
  se guardan sin recomprimir (`ZIP_STORED`) y los nombres de entrada de los
  packs se calculan por directorio: ~16 % menos de CPU por backup, con un ZIP
  ~1 % mayor.
- El actualizador de la suite podía terminar en error con «Acceso denegado»
  si la GUI o el antivirus leían su archivo de progreso justo cuando se
  reemplazaba. Ahora reintenta el reemplazo durante unos segundos. Como el
  auxiliar se copia de la instalación actual, la mejora protege las
  actualizaciones que parten de 2.1.1; la de 2.1.0 a 2.1.1 aún usa el
  auxiliar de 2.1.0. Si ese paso mostrara «Acceso denegado», se puede
  reintentar; si quedó interrumpido, `iniciar_gui.bat` o `Recuperar_suite.bat`
  restauran antes la versión anterior.

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
