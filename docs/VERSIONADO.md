# Versionado de Minecraft Bedrock Server Suite

`version.json` es la fuente de la versión del producto en cada repositorio.
TESTTEST y `minecraft-bedrock-server-suite` comparten el número de versión,
aunque sus commits y sus archivos específicos pueden ser distintos. La versión
del servidor BDS sigue siendo independiente.

- Python la lee mediante `suite_version.VERSION`, desde una ruta relativa a
  `__file__`. `gui_backend.__version__` conserva el acceso compatible.
- FastAPI la publica en OpenAPI y en `suite_version` del estado HTTP/WS.
- React importa el mismo JSON y lo incorpora al build de Acerca de. No necesita
  Git, Node ni una consulta de red para mostrarla en runtime.
- `package.json` y las dos versiones raíz de `package-lock.json` son copias
  sincronizadas por la herramienta. El build falla si no coinciden.
- `CHANGELOG.md` documenta 2.0.0 y las siguientes entregas. El historial anterior
  permanece en Git y en los informes; no se le asignan versiones retrospectivas.

## Elegir el siguiente número

Se usan versiones estables `MAYOR.MENOR.PARCHE`:

- PARCHE: correcciones compatibles, por ejemplo `2.1.1`.
- MENOR: funciones nuevas compatibles, por ejemplo `2.2.0`.
- MAYOR: cambios que rompan un contrato público o requieran migración, por ejemplo `3.0.0`.

El número se cambia al preparar una entrega, no por cada commit. La primera
versión común fue 2.0.0 y conservó el número previamente declarado por el backend.
La entrega 2.1.0 añadió el ZIP con Python incluido y el actualizador de la suite; la 2.1.1 es su primera corrección.
La 2.2.0 añade la carpeta de backups configurable, por eso sube el número MENOR.
La 2.2.1 corrige los 31 hallazgos de la revisión del 21 de octubre de 2026.
Ver [descarga, seguridad y recuperación](ACTUALIZACIONES_SUITE.md).

La [Release pública v2.1.0](https://github.com/guapo3266/minecraft-bedrock-server-suite/releases/tag/v2.1.0)
se publicó el 16 de octubre de 2026. Su etiqueta pública identifica `0632a58`;
la etiqueta local de TESTTEST identifica `41cc161`. La
[Release v2.1.1](https://github.com/guapo3266/minecraft-bedrock-server-suite/releases/tag/v2.1.1)
se publicó el 20 de octubre de 2026: su etiqueta pública identifica `39cd5bb`
y la local de TESTTEST `53f1a9f`. La
[Release v2.2.0](https://github.com/guapo3266/minecraft-bedrock-server-suite/releases/tag/v2.2.0)
se publicó el 21 de octubre de 2026: su etiqueta pública identifica `0905c4b`
y la local de TESTTEST `b83d172`. La
[Release v2.2.1](https://github.com/guapo3266/minecraft-bedrock-server-suite/releases/tag/v2.2.1)
se publicó el 22 de octubre de 2026: su etiqueta pública identifica `95cbb9b`
y la local de TESTTEST `cc9846a`. No mover ninguna etiqueta publicada para
incluir commits posteriores de documentación o CI. Estos commits pueden
conservar la versión 2.2.1 mientras no se prepare otro paquete; la siguiente
corrección distribuible partiría de 2.2.2.

## Preparar una entrega local

En la raíz de **cada** repositorio, con el mismo número elegido:

```powershell
python tools/set_version.py 2.2.1
```

Mover los cambios de `[Sin publicar]` a una sección como
`## [2.2.1] - AAAA-MM-DD` en `CHANGELOG.md`, con la fecha real de preparación.
Documentar solo los cambios incluidos en ese árbol. Comprobar los manifiestos:

```powershell
python tools/set_version.py --check
python -m ruff check .
python -m pytest tests -m "not e2e" -q
npm --prefix gui_frontend run lint
npm --prefix gui_frontend test
npm --prefix gui_frontend run build
```

Revisar el diff y el build antes de crear el commit. La etiqueta se crea en el
commit aprobado de cada repositorio, con el árbol limpio:

```powershell
git diff --check
git status --short
git commit -m "chore: preparar versión 2.2.1"
git tag -a v2.2.1 -m "Versión 2.2.1 de Minecraft Bedrock Server Suite"
```

Seleccionar explícitamente los archivos que se incluirán antes del commit.
No mover una etiqueta existente para reutilizar un número: una corrección de
una entrega ya identificada que vaya a distribuirse recibe una nueva versión.

Commit, etiqueta, push y despliegue son operaciones separadas. La herramienta
no hace commits, no crea etiquetas, no publica ni sincroniza instalaciones.
Para una futura instalación, distribuir también `suite_version.py` y
`version.json` junto al código y el `dist/` reconstruido.

Los workflows de tests y Release son **solo manuales**. Ni push ni PR los
ejecutan; no reactivar esos disparadores al sincronizar repositorios. La
publicación del código, la Release con sus assets y el despliegue en una
instalación son tres operaciones independientes. Una Release pública no
autoriza a sincronizar ni actualizar el servidor real.

Las notas de la Release salen de la sección de la versión en `CHANGELOG.md`
(`tools/release_notes.py`, que convierte los enlaces relativos en enlaces al
repositorio). La publicación con GitHub CLI (borrador, digests verificados y
recién entonces Latest) está en
[Publicar con GitHub CLI](ACTUALIZACIONES_SUITE.md#publicar-con-github-cli).
