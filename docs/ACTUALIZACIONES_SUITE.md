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
   Solo después confirmar la entrega y volver a habilitar operaciones.
8. Reiniciar Minecraft si antes estaba encendido. Un fallo de este reinicio se
   informa por separado; no se presenta como éxito completo.

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

Los resguardos anteriores quedan en `data/suite_updates/previous_*`. No se borran
automáticamente. Guardan código/runtime; no duplican los mundos. El backup final
conserva su ubicación y sus reglas de retención habituales.

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

El build publicable exige un checkout limpio. `--allow-dirty` solo sirve para QA:
ese ZIP queda marcado y el actualizador lo rechaza. `release_python.json` fija
CPython y su hash oficial; `requirements-release.txt` fija las dependencias.
Se conservan sus licencias y se excluyen tests, cachés y recursos `.agents`
de desarrollo incluidos en los wheels.

Los workflows **tests** y **Release Windows** se ejecutan solo manualmente desde
Actions. Los pushes de ramas/tags y las PR no los activan. **Release Windows**
valida y construye el ZIP: ejecutarlo sobre una rama crea un artifact; sobre un
tag `vX.Y.Z` coincidente con `version.json` también publica la Release con ZIP y
checksum. El ZIP ya validado puede publicarse directamente mediante la API de
GitHub. No mover tags existentes. Push, publicación y despliegue son operaciones
separadas que requieren el pedido del usuario.

Para publicar directamente, usar el **checkout público** y una etiqueta ya
creada en el commit aprobado. Crear una Release en borrador para esa etiqueta,
adjuntar el ZIP validado y su `.sha256`, comprobar sus hashes y publicarla como
estable/Latest. Descargar ambos assets y comprobar de nuevo los bytes y
[la última Release en la API](https://api.github.com/repos/guapo3266/minecraft-bedrock-server-suite/releases/latest). No sustituir silenciosamente los assets de una versión
ya publicada; una corrección distribuible recibe un nuevo número.

## Validar sin ejecutar BDS

Además de los checks de [versionado](VERSIONADO.md), el verificador opt-in
ejercita actualización, migración desde scripts y rollback de un fallo de
arranque. Usar una carpeta de salida **nueva y corta**, fuera de una instalación
real:

```powershell
python tools/verify_release.py output/releases/BedrockSuite-Windows-x64.zip --output C:\SuiteQA\2.1.0
```

Genera `VERIFICACION.json` y logs por escenario. Descarga un Python anterior
verificado y sustituye realmente el runtime; la GUI y Python son reales,
GitHub y el wrapper se simulan. No ejecuta ni incluye `bedrock_server.exe`.
Conserva seis testigos de configuración/datos y comprueba que los archivos
idénticos mantienen su fecha. Las copias con fallos inyectados son solo de QA.

En la validación local del 16 de octubre de 2026 pasaron los tres escenarios,
1051 tests Python del perfil público (2 omitidos, 2 e2e excluidos), 96 tests
frontend y lint/build. El lanzador del ZIP arrancó con solo `C:\Windows\System32`
en el PATH, desde otro directorio y con espacios/acentos en la ruta. Esto
acredita el paquete y su recuperación; no una prueba E2E de Minecraft ni una
ejecución de CI en GitHub. Nunca interpretar un job que no arrancó como un test
aprobado.
