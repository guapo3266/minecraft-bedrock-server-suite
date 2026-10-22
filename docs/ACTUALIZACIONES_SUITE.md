# Descarga y actualización de la suite

**Actualizar BDS** obtiene Minecraft desde Mojang. **Actualizar la suite**
consulta las Releases estables al abrir la GUI y con el botón manual, con caché
compartida. Instalar siempre requiere confirmación.

## ZIP Windows x64

[Descargar el ZIP más reciente](https://github.com/guapo3266/minecraft-bedrock-server-suite/releases/latest/download/BedrockSuite-Windows-x64.zip)
· [Checksum SHA-256](https://github.com/guapo3266/minecraft-bedrock-server-suite/releases/latest/download/BedrockSuite-Windows-x64.zip.sha256)
· [Releases](https://github.com/guapo3266/minecraft-bedrock-server-suite/releases).

Extraer `BedrockSuite-Windows-x64.zip` completo y abrir `iniciar_gui.bat`.
Incluye CPython, dependencias y GUI compilada: no requiere Python, Git ni Node
instalados. El wizard descarga BDS desde Mojang. El ZIP no incluye BDS, mundos,
packs ni configuraciones personales. Admite instalaciones previas con scripts.

Se recomienda una ruta corta, por ejemplo `C:\BedrockSuite`. Si Windows rechaza
las rutas largas del staging o del auxiliar, la preparación se cancela antes de
reemplazar el programa; extraer la instalación en una ruta corta permite repetirla.

## Entrega 2.2.0 publicada

La [Release v2.2.0](https://github.com/guapo3266/minecraft-bedrock-server-suite/releases/tag/v2.2.0)
se publicó el **21 de octubre de 2026** como estable y Latest. El ZIP incluye
CPython **3.13.16**, ocupa **16 510 231 bytes** y contiene 759 archivos: los 758
que inventaría su manifiesto más el propio `suite_release_manifest.json`. El
manifiesto identifica el commit público `0905c4b5b549c3824977588feaafc87266d69c8e`
(etiqueta `v2.2.0`; en TESTTEST apunta a `b83d172`). Su SHA-256 es:

```text
5e73b6d898facc6d4a55235f3a4102bb40a5fe169d6729141a0835363f632b7a
```

Evidencia del 21 de octubre:

- Un primer ZIP salió sin `backup_location.py` y no se publicó (ver
  [Qué puede reemplazar](#qué-puede-reemplazar)). El publicado se construyó
  desde un checkout limpio, después de mover el módulo a `gui_backend/`.
- Pasó `tools/verify_release.py` en una carpeta nueva: actualización, migración
  desde scripts y rollback, con los seis testigos intactos. Igual que en 2.1.1,
  esos escenarios ejercitan el auxiliar de la propia 2.2.0.
- Esta vez también se probó la ruta real desde 2.1.1, con un script de QA que
  no está en el repo: una instalación extraída del ZIP publicado de 2.1.1, con
  su GUI y su auxiliar, recibió el ZIP 2.2.0 sin reempaquetar (GitHub simulado,
  sin BDS ni Minecraft encendido). Terminó en `complete`; la GUI nueva respondió
  2.2.0 y `GET /api/backups/location`; el árbol coincidió con el manifiesto; el
  wrapper y la CLI importaron con el Python incluido, y los seis testigos
  quedaron intactos. La ruta desde 2.1.0 no se probó (ver el problema conocido).
- Tests sin e2e: 1177 en TESTTEST y 1175 en el perfil público (2 omitidos);
  108 tests frontend, lint y build.
- Los assets publicados se descargaron de GitHub y sus bytes coincidieron con
  los del ZIP probado y con el digest de la API. El actualizador de una 2.1.1,
  contra la API real, detectó 2.2.0 con su URL, tamaño y SHA-256. No se
  instaló en el servidor real.

## Entrega 2.1.1 publicada

La [Release v2.1.1](https://github.com/guapo3266/minecraft-bedrock-server-suite/releases/tag/v2.1.1)
se publicó el **20 de octubre de 2026** como estable y Latest. El ZIP incluye
CPython **3.13.16**, ocupa **16 484 670 bytes** y contiene 757 archivos: los 756
que inventaría su manifiesto más el propio `suite_release_manifest.json`. El
manifiesto identifica el commit público `39cd5bb177ca8c74b6a0e50458626afd02162797`
(etiqueta `v2.1.1`; en TESTTEST apunta a `53f1a9f`). Su SHA-256 es:

```text
495aebbcb5f66943842fcc6459b32ec979a5bd19e826e51f97819d38746c5e27
```

Evidencia del 20 de octubre:

- Se construyó desde un checkout limpio y pasó `tools/verify_release.py` en una
  carpeta nueva: actualización, migración desde scripts y rollback ante un
  fallo de arranque inyectado, con los seis testigos de datos intactos. GUI y
  Python fueron reales; GitHub y el wrapper, simulados; no se ejecutó BDS.
- Esa QA no recorre la ruta que siguen los usuarios: el verificador arma la
  instalación «anterior» con el propio paquete y solo cambia su número de
  versión, así que ejercitó el auxiliar de 2.1.1. La actualización real
  2.1.0 → 2.1.1 usa el auxiliar de 2.1.0 y no se probó de extremo a extremo
  (ver el problema conocido de abajo).
- Un intento previo con otro ZIP falló en el escenario de actualización por un
  `PermissionError` en `os.replace` de `progress.json`; se corrigió con
  `suite_release._replace` y el ZIP publicado se construyó después de esa
  corrección. El auxiliar se copia de la instalación actual: la mejora rige
  para actualizaciones que parten de 2.1.1.
- Los assets publicados se descargaron de GitHub y sus bytes coincidieron con
  los del ZIP probado y con el digest de la API. El actualizador, ejecutado
  contra la API real, detectó la Release con su URL y SHA-256. La ofrece a toda
  instalación con una versión anterior que tenga actualizador (en la práctica,
  2.1.0) y no a una 2.1.1. No se instaló en el servidor real: esa instalación
  se sincronizó por separado desde TESTTEST.

### Problema conocido al actualizar desde 2.1.0

El auxiliar que aplica la actualización se copia de la versión instalada:
desde 2.1.0, a 2.1.1 o a cualquier versión posterior, se usa el de 2.1.0, que
reemplaza sus archivos de estado sin reintentar. Si la GUI o el antivirus los están leyendo en ese instante, Windows
responde «Acceso denegado» («Access is denied»). Mundos, propiedades, packs,
backups y configuración no se tocan en ningún caso. Según el momento:

- **La ventana indica que se recuperó la versión anterior**, con ese error en
  el detalle: la instalación quedó como estaba y se puede volver a intentar.
- **La GUI no vuelve a abrirse**: abrir `iniciar_gui.bat` (o `Recuperar_suite.bat`).
  Si el reemplazo quedó a medias, recupera la versión anterior antes de arrancar.
- **La ventana queda en una fase que no avanza**, por ejemplo «Comprobando el
  arranque del panel actualizado…»: solo quedó atrasado el aviso de progreso.
  Si **Más acciones → Acerca de** muestra la versión nueva, la actualización
  terminó; si muestra 2.1.0, sigue instalada la versión anterior y se puede
  reintentar. En ambos casos,
  cerrar la pestaña de la GUI, borrar `data\suite_updates\recovery\progress.json`
  (solo guarda ese aviso; la recuperación usa `journal.json`) y volver a abrirla.

## Entrega 2.1.0 publicada

La [Release v2.1.0](https://github.com/guapo3266/minecraft-bedrock-server-suite/releases/tag/v2.1.0)
se publicó el **16 de octubre de 2026**, después de su preparación del día 15.
El ZIP incluye CPython **3.13.16**, ocupa **16 510 153 bytes** y su manifiesto
identifica el commit público `0632a5808095bf12b4a28907509eb80d0762777e`.
Su SHA-256 es:

```text
cefd52fc47b0ecd30402e5d39bc090411bb0974976d7a849d94b7c9de2ab7caf
```

Para comprobar una descarga en PowerShell:

```powershell
Get-FileHash .\BedrockSuite-Windows-x64.zip -Algorithm SHA256
```

El ZIP y el checksum publicados se descargaron de GitHub y coincidieron con
los archivos probados localmente. El actualizador también detectó esta Release
contra la API real simulando una versión instalada 2.0.0, sin instalarla en el
servidor real. Los commits posteriores de documentación o CI no cambian este
ZIP ni mueven la etiqueta.

## Qué puede reemplazar

Descarga el ZIP completo, pero solo reemplaza archivos del programa cuyo hash
cambió. Los archivos idénticos conservan su fecha. Solo retira archivos obsoletos
que figuraban en el manifiesto anterior y no fueron modificados localmente.

La lista positiva `suite_release.managed_path` se comparte entre empaquetador,
extractor, instalador y rollback. Rechaza propiedades, permisos, allowlist,
mundos, packs, backups, data, config y binarios BDS, incluso dentro de un manifiesto.
`server.properties.example` sí es una plantilla distribuible. Es independiente
de `.gitignore`. En checkouts Git permite consultar/descargar, pero no instalar.

La instalación valida el ZIP nuevo con **su** lista, no con la del paquete. Si
una versión trae un archivo raíz o de `tools/` que la instalada no conoce, la
actualización se rechaza entera. Por eso las listas siguen siendo las de 2.1.0
y el código nuevo va en `gui_backend/` (como `gui_backend/backup_location.py`).
`tests/test_paquete_release.py` lo comprueba y exige que el ZIP lleve todo
módulo que importe el programa: el empaquetador descarta en silencio lo que la
lista no acepta.

Rechaza enlaces/junctions, rutas que escapen, ADS, dispositivos NTFS y nombres
duplicados por mayúsculas. Límites: 512 MiB descargados; 1 GiB / 15 000 archivos
sin comprimir. Comprueba espacio para staging, auxiliar y resguardo.

## Secuencia

1. Consultar la última Release estable de `guapo3266/minecraft-bedrock-server-suite`.
   Validar tag, nombre del asset, URL, tamaño y SHA-256 de la API de GitHub.
2. Descargar por HTTPS, validando cada redirección antes de contactarla. Solo
   admite GitHub y sus hosts de assets. Verificar ZIP e inventario exacto.
3. Comprobar tamaños/hashes por archivo antes de detener Minecraft. Preparar un
   auxiliar con Python independiente y tomar exclusión entre operaciones/GUIs.
4. Si Minecraft está encendido, esperar su cierre, la salida del wrapper y el
   evento NDJSON `final_backup_finished` exitoso con ZIP existente. Un mensaje
   de consola o el fin de otro backup no acreditan este resultado.
5. Cerrar la GUI de forma coordinada. El auxiliar espera su salida y rechaza
   procesos residuales de esa instalación; no mata procesos ajenos.
6. Persistir el diario antes de cada reemplazo, resguardar/verificar originales,
   reemplazar atómicamente por archivo y comprobar el árbol instalado.
7. Arrancar la GUI con un token de relevo y comprobar API, versión, token, HTML
   y hashes de los assets JS/CSS servidos frente al manifiesto.
   Solo después confirmar la entrega y volver a habilitar operaciones. Las
   llamadas del auxiliar a la GUI (`127.0.0.1`) no usan el proxy del sistema ni
   del entorno: con un proxy configurado, cada comprobación fallaba y la
   actualización terminaba en rollback.
8. Reiniciar Minecraft si antes estaba encendido. El plazo de arranque (180 s)
   no corre mientras el wrapper hace su backup inicial
   (`initial_backup_in_progress` en `/api/status`); se toleran hasta 10 fallos
   seguidos de la API y el reinicio se da por fallido en cuanto el wrapper
   termina. Tope total: 3780 s (el máximo de un backup, 3600 s, más el
   arranque). Un fallo de este reinicio se informa por separado; no se presenta
   como éxito completo.

El SHA-256 vincula los bytes con los publicados por el repositorio mediante
HTTPS y el digest de GitHub. No es una firma independiente del autor ni protege
frente a una cuenta de GitHub comprometida.

## Recuperación

El diario, staging, runtime auxiliar y código anterior quedan en
`data/suite_updates/recovery/`. Un fallo de copia o arranque dispara rollback.
Si falta o está alterado un resguardo, se informa y nunca se descarta la evidencia.

Tras una interrupción, los lanzadores ejecutan primero `Recuperar_suite.bat`;
también puede abrirse directamente. Usa el Python auxiliar, fuera del runtime
reemplazado. Si el actualizador sigue activo, no abre otra GUI. Tras recuperar
un apagón, revisar la GUI y arrancar Minecraft manualmente.

Un diario terminado (`complete` o `rolled_back`) no deja nada que recuperar.
`Recuperar_suite.bat` lo comprueba con el Python auxiliar antes de ejecutar el
auxiliar: el de 2.2.0 o anterior validaba primero las rutas guardadas en el
diario y fallaba si la carpeta de la suite se había movido o copiado, y los
lanzadores se cerraban sin abrir nada. Si una recuperación falla de verdad,
`iniciar_gui.bat` e `iniciar_servidor.bat` dejan el mensaje a la vista con una
sola pausa (llaman a `Recuperar_suite.bat --sin-pausa`).

La GUI que relanza el auxiliar escribe su salida en `data/suite_updates/gui.log`
(se rota a `gui.log.1` al pasar de 5 MiB). Hasta 2.2.0 iba a
`recovery/gui.log`, que la GUI mantiene abierto toda su vida: la siguiente
actualización no podía archivar `recovery/` (WinError 32) y dejaba una copia
`previous_*` a medias en cada intento. La GUI archiva ahora `recovery/` entrada
por entrada y copia el log que siga abierto.

`progress.json` solo es el aviso que muestra la ventana; `journal.json` decide la
recuperación. Si el aviso queda en una fase en curso que ya nadie avanza (GUI
cerrada a mitad, auxiliar que no arrancó o un último aviso que no se pudo
guardar), la GUI muestra el resultado que registra el diario: actualización
terminada, versión anterior recuperada, cancelada antes de reemplazar el
programa o pendiente de `Recuperar_suite.bat`. La 2.1.1 publicada aún muestra
esos casos como en curso; ver
[el problema conocido](#problema-conocido-al-actualizar-desde-210).

Los resguardos anteriores quedan en `data/suite_updates/previous_*`. No se borran
automáticamente. Guardan código/runtime; no duplican los mundos. El backup final
conserva su ubicación y sus reglas de retención habituales.

### Qué corrección rige en cada actualización

El auxiliar se copia de la instalación actual al empezar cada actualización.
Sus correcciones del 21 de octubre de 2026 (proxy, reanudar Minecraft y la
ubicación de `gui.log`), incluidas en 2.2.1, rigen en las actualizaciones que
parten de 2.2.1: la de 2.2.0 a 2.2.1 todavía la hace el auxiliar de 2.2.0. Lo
que vive en la GUI (archivar `recovery/` con `gui.log` abierto) y en
`Recuperar_suite.bat` (diario terminado) rige en cuanto 2.2.1 está instalada.

Desde 2.2.0 quedan dos casos que la propia 2.2.0 no resuelve:

- **La actualización falla al prepararse con un error de acceso a
  `gui.log`**: la GUI de 2.2.0 se abrió sola al terminar la actualización
  anterior y retiene `recovery/gui.log`. Cerrar la GUI, abrirla con
  `iniciar_gui.bat` y volver a intentarlo. Minecraft no se detiene antes de ese
  paso.
- **Tras mover o copiar la carpeta de la suite, los lanzadores se cierran sin
  abrir nada**: si `data/suite_updates/recovery/journal.json` dice
  `"phase": "complete"` o `"rolled_back"`, renombrar la carpeta
  `data/suite_updates/recovery` (por ejemplo a `recovery_terminada`) y volver a
  abrir. Con cualquier otra fase, abrir `Recuperar_suite.bat` en la carpeta
  original.

## Preparar una Release

En un entorno de desarrollo con Python y Node, instalar `requirements-dev.txt`,
ejecutar `npm --prefix gui_frontend ci` y reconstruir con
`npm --prefix gui_frontend run build`. El empaquetador recoge también las
licencias de las dependencias frontend instaladas. Revisar y commitear los
cambios de código, versión, changelog y `dist/` antes de construir el ZIP:

```powershell
python tools/set_version.py --check
python tools/build_release.py
python tools/release_notes.py --output output/releases/NOTAS.md
```

`release_notes.py` copia la sección de la versión del `CHANGELOG.md` y convierte
sus enlaces relativos en enlaces a `main` del repositorio público: la página de
la Release no resuelve rutas del repo, y el registro de cada entrega (hash,
procedencia, evidencia) se añade a `docs/` después de etiquetarla.

El build publicable exige un checkout limpio. `--allow-dirty` solo sirve para QA:
ese ZIP queda marcado y el actualizador lo rechaza. `release_python.json` fija
CPython y su hash oficial; `requirements-release.txt` fija las dependencias.
Se conservan sus licencias y se excluyen tests, cachés y recursos `.agents`
de desarrollo incluidos en los wheels.

Los workflows **tests** y **Release Windows** se ejecutan solo manualmente desde
Actions. Los pushes de ramas/tags y las PR no los activan. **Release Windows**
valida y construye el ZIP: ejecutarlo sobre una rama crea un artifact; sobre un
tag `vX.Y.Z` coincidente con `version.json` también publica la Release con ZIP y
checksum. El ZIP ya validado puede publicarse directamente con GitHub CLI (abajo).
No mover tags existentes. Push, publicación y despliegue son operaciones
separadas que requieren el pedido del usuario.

### Publicar con GitHub CLI

2.1.1 se publicó con este procedimiento: borrador, digests verificados y recién
entonces Latest. Requiere `gh` (instalado en `C:\Program Files\GitHub CLI`)
con una sesión que inicia el propio usuario (`gh auth login`). Se publica desde
el **checkout público**, con la etiqueta `vX.Y.Z` ya creada en el commit aprobado
y subida, y con el MISMO ZIP que pasó `tools/verify_release.py`: un ZIP
reconstruido es otro ZIP. Primero, un borrador con sus dos assets:

```powershell
gh release create vX.Y.Z output/releases/BedrockSuite-Windows-x64.zip output/releases/BedrockSuite-Windows-x64.zip.sha256 --draft --verify-tag --title "Bedrock Suite vX.Y.Z" --notes-file output/releases/NOTAS.md
gh api repos/guapo3266/minecraft-bedrock-server-suite/releases --jq '.[0] | .tag_name, .draft, (.assets[] | {name, size, digest})'
Get-FileHash output/releases/BedrockSuite-Windows-x64.zip -Algorithm SHA256
```

El borrador recién creado es el primero de la lista. Solo si el `digest` del ZIP
(`sha256:…`, el valor exacto que verifica el actualizador) coincide con
`Get-FileHash` y con el `.sha256`, publicarlo como estable y Latest:

```powershell
gh release edit vX.Y.Z --draft=false --latest
```

Después, descargar los assets publicados en una carpeta nueva, comprobar otra
vez sus bytes y que la API ya devuelve esta Release como la última:

```powershell
mkdir C:\SuiteQA\descarga-vX.Y.Z
gh release download vX.Y.Z --dir C:\SuiteQA\descarga-vX.Y.Z
Get-FileHash C:\SuiteQA\descarga-vX.Y.Z\BedrockSuite-Windows-x64.zip -Algorithm SHA256
gh api repos/guapo3266/minecraft-bedrock-server-suite/releases/latest --jq '.tag_name, (.assets[] | {name, digest})'
```

Las expresiones `--jq` evitan comillas dobles: Windows PowerShell 5.1 las altera
al pasarlas a programas externos. No sustituir silenciosamente los assets de una
versión ya publicada; una corrección distribuible recibe un nuevo número.

## Validar sin ejecutar BDS

Además de los checks de [versionado](VERSIONADO.md), el verificador opt-in
ejercita actualización, migración desde scripts y rollback de un fallo de
arranque. Usar una carpeta de salida **nueva y corta** en cada intento, fuera de
una instalación real (rechaza una carpeta que ya tenga escenarios):

```powershell
python tools/verify_release.py output/releases/BedrockSuite-Windows-x64.zip --output C:\SuiteQA\2.2.1
```

Genera `VERIFICACION.json` y logs por escenario. Descarga un Python anterior
verificado y sustituye realmente el runtime; la GUI y Python son reales,
GitHub y el wrapper se simulan. No ejecuta ni incluye `bedrock_server.exe`.
Conserva seis testigos de configuración/datos y comprueba que los archivos
idénticos mantienen su fecha. Las copias con fallos inyectados son solo de QA.

La instalación «anterior» de cada escenario se arma con el propio paquete y
solo cambia su número de versión: el auxiliar que se ejercita es siempre el de
la versión verificada. La transición desde la versión publicada anterior, con
su propio auxiliar, no la cubre este verificador.

En la validación de 2.1.0 (16 de octubre de 2026) pasaron los tres escenarios,
1051 tests Python del perfil público (2 omitidos, 2 e2e excluidos), 96 tests
frontend y lint/build. El lanzador del ZIP arrancó con solo `C:\Windows\System32`
en el PATH, desde otro directorio y con espacios/acentos en la ruta. La
evidencia de 2.1.1 está en [Entrega 2.1.1 publicada](#entrega-211-publicada).
Esto acredita el paquete y su recuperación; no una prueba E2E de Minecraft ni
una ejecución de CI en GitHub. Nunca interpretar un job que no arrancó como un
test aprobado.
