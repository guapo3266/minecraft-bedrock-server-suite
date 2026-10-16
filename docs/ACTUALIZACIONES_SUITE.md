# Descarga y actualización de la suite

**Actualizar BDS** obtiene Minecraft desde Mojang. **Actualizar la suite**
consulta las Releases estables al abrir la GUI y con el botón manual, con caché
compartida. Instalar siempre requiere confirmación.

## ZIP Windows x64

Extraer `BedrockSuite-Windows-x64.zip` completo y abrir `iniciar_gui.bat`.
Incluye CPython, dependencias y GUI compilada: no requiere Python, Git ni Node
instalados. El wizard descarga BDS desde Mojang. El ZIP no incluye BDS, mundos,
packs ni configuraciones personales. Admite instalaciones previas con scripts.

Se recomienda una ruta corta, por ejemplo `C:\BedrockSuite`. Si Windows rechaza
las rutas largas del staging o del auxiliar, la preparación se cancela antes de
reemplazar el programa; extraer la instalación en una ruta corta permite repetirla.

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
7. Arrancar la GUI con un token de relevo y comprobar API, versión, token y HTML.
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

```powershell
python tools/set_version.py --check
python tools/build_release.py
python tools/release_notes.py --output output/releases/NOTAS.md
```

El build publicable exige un checkout limpio. `--allow-dirty` solo sirve para QA:
ese ZIP queda marcado y el actualizador lo rechaza. `release_python.json` fija
CPython y su hash oficial; `requirements-release.txt` fija las dependencias.
Se conservan sus licencias y se excluyen recursos `.agents` de desarrollo.

El workflow **Release Windows** valida y construye el ZIP. Su ejecución manual
solo crea un artifact. Publicar un tag `vX.Y.Z` coincidente con `version.json`
dispara la Release con ZIP y checksum. Un push solo a main no crea Releases.
No mover tags existentes. Push, publicación y despliegue son operaciones separadas
que requieren el pedido del usuario.
