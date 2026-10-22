# Informe — Inventario y diagnóstico de addons (fase 1: solo lectura)

Fecha del informe: 2026-10-06 · Ámbito: `TESTTEST` (instalación de pruebas)

## 1. Qué hace esta fase y qué NO hace

Permite al administrador **conocer** qué behavior packs (BP) y resource packs
(RP) existen en su instalación, **qué mundos los referencian** y **qué problemas
demuestra** el análisis de sus metadatos (`manifest.json`,
`world_behavior_packs.json`, `world_resource_packs.json` y la disposición de
carpetas).

* **No** instala, actualiza, elimina ni activa addons (queda para otra fase).
* **No** modifica mundos, packs, manifiestos ni configuración: el analizador
  solo abre archivos en modo lectura (hay tests que fotografían el árbol antes y
  después y exigen que sea idéntico, incluido `mtime`).
* **No** arranca BDS ni promete funcionamiento dentro del juego: la
  documentación es explícita en que el estado del experimento "Beta APIs", la
  versión del motor y el orden de apilamiento **no** están en los metadatos
  (tabla G del informe de fuentes). Todo eso queda declarado como **no
  determinado**.

## 2. Fuentes y trazabilidad

Consulta de fuentes oficiales (F1–F5) el **2026-10-06**, con citas literales,
discrepancias y puntos no determinados: **`docs/INVESTIGACION_FUENTES_ADDONS.md`**.

| Fuente | Qué respalda |
|---|---|
| **F1** `packmanifest` (Microsoft Learn) | `format_version`, `header`, `modules`, `dependencies`, UUID, versiones, `min_engine_version` |
| **F2** `bedrockserver/getting-started` | packs compartidos (`behavior_packs/`, `resource_packs/`) frente a packs por mundo (`worlds/<level-name>/…`); un solo mundo activo |
| **F3** `packagingaworldtemplate` (+ su equivalente en inglés `createaworldtemplate`) | `world_behavior_packs.json` / `world_resource_packs.json` (`pack_id`, `version`); "Failed to import" por UUIDs repetidos |
| **F4** `scripting/versioning` | canales de versionado (juego vs API), semántica `^`, `-beta` (exige experimento en el mundo), `-internal` (no soportado) |
| **F5** `microsoft/minecraft-samples` (MIT) | ejemplos oficiales de manifiesto usados como contraste |
| **BDS-howto** (`bedrock_server_how_to.html`, incluido con el binario) | carpetas `behavior_packs`, `resource_packs`, `worlds`, `system_behavior_packs`, `system_resource_packs` y la protección de UUID de los packs de sistema |

Cada diagnóstico del payload incluye `source` (F1…F5 o `BDS-howto`) y `determined`
(`false` = el hecho se comprueba, pero la documentación no fija la consecuencia).

## 3. Mapa de archivos

| Archivo | Responsabilidad |
|---|---|
| `addon_inventory.py` | **Analizador compartido** (sin FastAPI): inventario + diagnósticos + `filter_payload`. Solo lectura y determinista |
| `addon_inventory_cli.py` | CLI: salida legible, `--json` y catálogo de códigos (`--codes`) |
| `gui_backend/services/addons.py` | Delegación fina en el analizador (la GUI no reimplementa validaciones) |
| `gui_backend/routers/addons.py` | `GET /api/addons` (solo lectura, en threadpool) |
| `gui_frontend/src/components/AddonsSidebar.jsx` | Pestaña "Addons": inventario, filtros, detalles y diagnósticos |
| `gui_frontend/src/addonsLogic.js` | Espejo en JS del filtro de vista (`filter_payload`) + conteos |
| `tests/test_addon_inventory.py` | Analizador sobre instalaciones temporales, con regresiones de esquema, filtros y dependencias por mundo |
| `tests/test_addon_inventory_pbt.py` | Propiedades (Hypothesis): JSON tolerante, robustez, determinismo |
| `tests/test_addon_inventory_cli.py` | CLI real (subproceso), códigos de salida y solo-lectura |
| `tests/test_addon_router.py` | Endpoint + equivalencia CLI/GUI |
| `tests/test_addon_inventory_fuentes.py` | Anti-drift catálogo ↔ esta tabla + higiene i18n |

## 4. Formatos y ubicaciones soportadas (declaración explícita)

**Analizado en esta fase**

* `manifest.json` con `format_version` **2** (resource, behavior y world
  templates según F1/A1–A2), en:
  * `behavior_packs/<pack>/manifest.json` y `resource_packs/<pack>/manifest.json` (**compartidos**, F2/E1–E2);
  * `system_behavior_packs/<pack>/` y `system_resource_packs/<pack>/` (**de sistema**, BDS-howto: se aplican a todos los mundos y sus UUID están protegidos);
  * `worlds/<level-name>/behavior_packs/<pack>/` y `worlds/<level-name>/resource_packs/<pack>/` (**propios del mundo**, F2/E3).
* `world_behavior_packs.json` y `world_resource_packs.json` de cada mundo
  (array de objetos con `pack_id` y `version`, F3/F-1).
* Manifiestos **no estrictos** con comentarios `//`, `/* */` o comas finales:
  Mojang distribuye así sus propios packs vanilla
  (`behavior_packs/chemistry/manifest.json`), de modo que el análisis estricto
  daría un falso positivo sobre el propio servidor. Se analizan en modo
  tolerante y se reporta `MANIFEST_JSON_TOLERANT` (info).
* Campos adicionales desconocidos (`metadata`, `subpacks`, `capabilities`,
  campos propios): **no invalidan** el manifiesto.

**No analizado (se reporta con su motivo, nunca como corrupto)**

* `format_version` **1** (skin packs, F1/A1) y **3** (preview 1.21.110+, F1/A3/N12).
* Representaciones empaquetadas presentes en las carpetas de packs
  (`.mcpack`, `.mcaddon`, `.zip`, `.mcworld`, `.mctemplate`).
* Manifiestos que no están en la raíz de la carpeta del pack (layout anidado).
* `development_behavior_packs/`, `development_resource_packs/` y
  `world_templates/` quedan fuera del alcance de esta fase (F2 y el how-to de
  BDS no los definen como ubicaciones de packs del servidor).
* `modules[].entry`: **no está documentado en ninguna fuente consultada** (N1);
  se muestra si existe, pero no se valida.

## 5. Códigos de diagnóstico

`Gravedad` — `error`: incumple una regla documentada con consecuencia funcional
(identidad, estructura o referencia irresoluble) · `aviso`: la documentación lo
pide/recomienda, o la evidencia es parcial, sin consecuencia funcional
demostrable · `info`: informativo o **no determinado**.

`Parcial` — el hallazgo implica que **algo que debía poder analizarse no se pudo
analizar** (el inventario se marca `complete: false` y lista `partial_reasons`).
Un formato declarado no soportado **no** hace parcial el inventario.

`Determinado` — `no` significa que la documentación no fija la regla o la
consecuencia: el hecho se reporta, pero el resultado queda como no determinado.

| Código | Gravedad | Fuente | Parcial | Determinado | Qué comprueba |
|---|---|---|---|---|---|
| `BASE_DIR_MISSING` | error | F2 | sí | sí | La instalacion indicada no existe o no es una carpeta: {ruta}. |
| `CAPABILITY_UNKNOWN` | aviso | F1 | no | sí | capabilities de {ruta} declara un valor no documentado: {valor} (A8). |
| `DEPENDENCY_NOT_OBJECT` | error | F1 | sí | sí | dependencies[{indice}] de {ruta} no es un objeto JSON: se ignora esa dependencia (D1/D4). |
| `DEPENDENCY_PACK_AMBIGUOUS` | aviso | F1 | no | no | El pack {ruta} depende de {uuid} y hay varios candidatos en su ambito ({candidatos}): la documentacion no define precedencia (F1/N6). |
| `DEPENDENCY_PACK_MISSING` | error | F1 | no | no | El pack {ruta} depende de {uuid}, que no existe en su ambito ({ambito}): la dependencia queda sin satisfacer (F1/N9). |
| `DEPENDENCY_PACK_OTHER_KIND` | info | F1 | no | no | El pack {ruta} ({tipo}) depende de {uuid}, que solo existe como {otro}: F1 no restringe el tipo del pack dependido; no se determina si BDS lo resuelve (D2). |
| `DEPENDENCY_PACK_UUID_INVALID` | error | F1 | no | sí | dependencies[{indice}].uuid de {ruta} no tiene el formato hexadecimal documentado: {valor} (D2). |
| `DEPENDENCY_PACK_VERSION_INVALID` | error | F1 | no | sí | dependencies[{indice}].version de {ruta} no se puede interpretar como version: {valor} (D3). |
| `DEPENDENCY_PACK_VERSION_MISMATCH` | aviso | F1 | no | no | El pack {ruta} depende de {uuid} version {version} y el candidato instalado es {instalada}: F1 dice que la version "should match" (recomendacion) y no define el operador (D3/N5). |
| `DEPENDENCY_PACK_VERSION_MISSING` | info | F1 | no | no | dependencies[{indice}] de {ruta} no declara version: F1 recomienda que coincida con la del pack dependido, asi que no se puede comprobar (D3/N5). |
| `DEPENDENCY_WITHOUT_KEY` | error | F1 | sí | sí | dependencies[{indice}] de {ruta} no declara ni uuid (pack) ni module_name (modulo de scripting): no se puede interpretar (D1/D4). |
| `GENERATED_WITH_INVALID` | aviso | F1 | no | sí | metadata.generated_with de {ruta} no cumple el formato documentado (herramientas [a-zA-Z0-9_-], maximo 32 caracteres): {valor} (A5). |
| `ITEM_ANALYSIS_ERROR` | error | F2 | sí | sí | Error inesperado al analizar {ruta}: {motivo}. |
| `MANIFEST_ENCODING_NOT_UTF8` | aviso | F1 | no | sí | El manifiesto {ruta} no esta codificado en UTF-8: se leyo como latin-1 para poder analizarlo. |
| `MANIFEST_FORMAT_VERSION_INVALID` | error | F1 | sí | sí | format_version de {ruta} no es un numero: {valor}. |
| `MANIFEST_FORMAT_VERSION_MISSING` | error | F1 | sí | sí | El manifiesto {ruta} no declara format_version: no se puede determinar el formato (F1/A1). |
| `MANIFEST_FORMAT_VERSION_UNSUPPORTED` | info | F1 | no | no | format_version {valor} de {ruta} no se analiza en esta fase: {motivo}. |
| `MANIFEST_HEADER_MISSING` | error | F1 | sí | sí | El manifiesto {ruta} no tiene un objeto header: no se puede identificar el pack (F1/A4). |
| `MANIFEST_JSON_INVALID` | error | F1 | sí | sí | El manifiesto {ruta} no es JSON valido: {motivo}. |
| `MANIFEST_JSON_NOT_OBJECT` | error | F1 | sí | sí | El manifiesto {ruta} no es un objeto JSON sino {tipo}: no se puede leer header ni modules. |
| `MANIFEST_JSON_TOLERANT` | info | F1 | no | sí | El manifiesto {ruta} no es JSON estricto ({motivo}); se analizo en modo tolerante (los packs vanilla de Mojang se distribuyen asi). |
| `MANIFEST_MODULES_MISSING` | error | F1 | sí | sí | El manifiesto {ruta} no tiene una lista modules con al menos un modulo (F1/A4). |
| `MANIFEST_REPARSE` | aviso | F1 | sí | sí | {ruta} es un enlace/junction (reparse point): no se lee el manifiesto. |
| `MANIFEST_UNREADABLE` | error | F1 | sí | sí | No se pudo leer el manifiesto {ruta}: {motivo}. |
| `MIN_ENGINE_VERSION_FORMAT_UNEXPECTED` | aviso | F1 | no | sí | header.min_engine_version de {ruta} no sigue el formato documentado [a, b, c]: {valor} (B8). |
| `MIN_ENGINE_VERSION_INVALID` | error | F1 | no | sí | header.min_engine_version de {ruta} no se puede interpretar: {valor} (B8). |
| `MIN_ENGINE_VERSION_MISSING` | aviso | F1 | no | sí | Falta header.min_engine_version en {ruta}: F1 lo marca obligatorio para packs de comportamiento y recursos; su ausencia no impide identificar el pack (B7). |
| `MODULE_KIND_MISMATCH` | aviso | F1 | no | sí | El pack {ruta} esta en una carpeta de {ubicacion} pero sus modulos son de tipo {tipos}: un pack de comportamiento usa data/script y uno de recursos usa resources (C2). |
| `MODULE_LANGUAGE_UNEXPECTED` | aviso | F1 | no | sí | modules[{indice}] de {ruta} declara language={valor}: F1 solo admite language en modulos script y con el valor "javascript" (C7). |
| `MODULE_NOT_OBJECT` | error | F1 | sí | sí | modules[{indice}] de {ruta} no es un objeto JSON: se ignora ese modulo (C1). |
| `MODULE_TYPE_MISSING` | error | F1 | sí | sí | modules[{indice}] de {ruta} no declara type: el modulo no se puede clasificar (C1). |
| `MODULE_TYPE_UNKNOWN` | aviso | N2 | no | no | modules[{indice}] de {ruta} usa type "{valor}", que no esta en la lista documentada (resources, data, world_template, script): no se valida (C1/N2). |
| `MODULE_UUID_DUPLICATE_IN_PACK` | aviso | F1 | no | sí | modules[{indice}].uuid de {ruta} repite el UUID de otro modulo del mismo manifiesto: F1 pide un UUID distinto por modulo (C4). |
| `MODULE_UUID_DUPLICATE_IN_SCOPE` | aviso | F1 | no | no | El UUID de modulo {uuid} aparece tambien en {otros} del mismo ambito: contenido con UUIDs repetidos da errores de importacion (C4/F-7); no se determina cual carga BDS. |
| `MODULE_UUID_EQUALS_HEADER` | aviso | F1 | no | sí | modules[{indice}].uuid de {ruta} repite header.uuid: F1 pide que sea distinto (C3). |
| `MODULE_UUID_INVALID` | error | F1 | no | sí | modules[{indice}].uuid de {ruta} no tiene el formato hexadecimal documentado: {valor} (B3). |
| `MODULE_UUID_MISSING` | error | F1 | no | sí | modules[{indice}] de {ruta} no declara uuid: cada modulo necesita un UUID propio (C4). |
| `MODULE_VERSION_FORMAT_UNEXPECTED` | aviso | F1 | no | sí | modules[{indice}].version de {ruta} no sigue el formato de 3 componentes documentado: {valor} (C5). |
| `MODULE_VERSION_INVALID` | error | F1 | no | sí | modules[{indice}].version de {ruta} no se puede interpretar como version: {valor} (C5). |
| `MODULE_VERSION_MISSING` | aviso | F1 | no | sí | modules[{indice}] de {ruta} no declara version (formato documentado [major, minor, revision], C5). |
| `PACK_ARCHIVED_REPRESENTATION` | info | F1 | no | no | {ruta} es una representacion empaquetada ({extension}) que esta fase no abre: no se analiza (no se considera corrupta). |
| `PACK_DESCRIPTION_MISSING` | aviso | F1 | no | sí | Falta header.description en {ruta}: F1 lo recomienda (1-2 lineas) pero no lo marca obligatorio (B2, N4). |
| `PACK_FOLDER_WITHOUT_MANIFEST` | aviso | F1 | sí | sí | La carpeta {ruta} esta en una ubicacion de packs pero no contiene {archivo}: no se puede analizar como pack. |
| `PACK_MANIFEST_NESTED` | info | F1 | no | no | En {ruta} hay un {archivo} mas profundo ({encontrado}): la ubicacion documentada es <carpeta-del-pack>/{archivo}; no se analiza. |
| `PACK_NAME_MISSING` | error | F1 | no | sí | Falta header.name en {ruta}: F1 lo marca como campo obligatorio (B1). |
| `PACK_SCOPE_INVALID` | aviso | F1 | no | sí | header.pack_scope de {ruta} no es uno de los valores documentados (world, global, any): {valor} (A7). |
| `PACK_UUID_DUPLICATE` | error | F1 | no | sí | El UUID {uuid} version {version} esta declarado por dos packs del mismo ambito ({ambito}): {otros}. |
| `PACK_UUID_INVALID` | error | F1 | no | sí | header.uuid de {ruta} no tiene el formato hexadecimal documentado (8-4-4-4-12): {valor} (B3). |
| `PACK_UUID_IN_OTHER_SCOPES` | info | F2 | no | no | El UUID {uuid} aparece tambien en otro ambito ({ambitos}): el mismo UUID en ambitos distintos no demuestra por si solo un conflicto (F2/E9, N6). |
| `PACK_UUID_MISSING` | error | F1 | no | sí | Falta header.uuid en {ruta}: sin UUID el pack no se puede identificar ni referenciar desde un mundo (B4). |
| `PACK_UUID_MULTIPLE_VERSIONS` | info | N6 | no | no | El UUID {uuid} aparece en {cuantos} packs del ambito {ambito} con versiones distintas ({versiones}): es el patron de los packs vanilla versionados de BDS; la documentacion no cubre esta colision (B6/N6). |
| `PACK_VERSION_FORMAT_UNEXPECTED` | aviso | F1 | no | sí | header.version de {ruta} no sigue el formato de 3 componentes [major, minor, revision] documentado: {valor} (B5). |
| `PACK_VERSION_INVALID` | error | F1 | no | sí | header.version de {ruta} no se puede interpretar como version: {valor} (B5). |
| `PACK_VERSION_MISSING` | error | F1 | no | sí | Falta header.version en {ruta}: la version forma parte de la identidad que usan las referencias de mundo (B5, F-3). |
| `PRODUCT_TYPE_INVALID` | aviso | F1 | no | sí | metadata.product_type de {ruta} no es "addon", el unico valor documentado: {valor} (A6). |
| `SCOPE_ENTRY_OUTSIDE_ROOT` | error | F2 | sí | sí | {ruta} resuelve fuera de {root} (enlace o redireccion): no se analiza. |
| `SCOPE_ENTRY_REPARSE` | aviso | F2 | sí | sí | {ruta} es un enlace/junction (reparse point): no se sigue ni se analiza. |
| `SCOPE_ENTRY_UNREADABLE` | error | F2 | sí | sí | No se pudieron leer los datos de {ruta}: {motivo}. |
| `SCOPE_ROOT_MISSING` | info | F2 | no | sí | La ubicacion documentada {root} no existe en esta instalacion. |
| `SCOPE_ROOT_REPARSE` | aviso | F2 | sí | sí | La ubicacion {root} es un enlace/junction (reparse point): no se explora para no salir del ambito autorizado. |
| `SCOPE_ROOT_UNREADABLE` | error | F2 | sí | sí | No se pudo listar la ubicacion {root}: {motivo}. |
| `SCRIPT_DEP_BETA` | aviso | F4 | no | no | El pack {ruta} depende de {modulo} {version} (beta): F4 exige el experimento "Beta APIs" EN EL MUNDO y las APIs beta pueden romperse en cada release mayor; el estado del experimento no esta en los metadatos (D6/D7/G1). |
| `SCRIPT_DEP_INTERNAL` | error | F4 | no | sí | El pack {ruta} depende de {modulo} {version} (internal): F4 dice que las APIs internas no son funcionales ni soportadas en packs personalizados (D8). |
| `SCRIPT_DEP_MODULE_NAME_INVALID` | aviso | F1 | no | sí | dependencies[{indice}].module_name de {ruta} no parece un modulo integrado (se espera un nombre con prefijo @, como @minecraft/server): {valor} (D4). |
| `SCRIPT_DEP_VERSION_INVALID` | error | F4 | no | sí | dependencies[{indice}] de {ruta} declara la version "{valor}" de {modulo}, que no es semver ni "beta" (D5). |
| `SCRIPT_DEP_VERSION_MISSING` | aviso | F4 | no | sí | dependencies[{indice}] de {ruta} depende de {valor} sin version: F4 pide basar las dependencias de API en la version mas alta soportada (D10). |
| `SERVER_PROPERTIES_REPARSE` | info | F2 | no | sí | {ruta} es un enlace/junction: no se lee para determinar el mundo activo (level-name). |
| `SYSTEM_PACK_UUID_PROTECTED` | error | BDS-howto | no | sí | El pack de usuario {ruta} usa el UUID {uuid}, reservado por un pack de sistema ({sistema}): el how-to de BDS avisa de que los packs de usuario fallan al cargar si repiten el ID de un pack de sistema. |
| `WORLD_ENTRY_REPARSE` | aviso | F2 | sí | sí | {ruta} es un enlace/junction (reparse point) dentro de worlds/: no se analiza como mundo. |
| `WORLD_REFS_ENTRY_INVALID` | error | F3 | sí | sí | {ruta}[{indice}] no es un objeto JSON con pack_id y version: se ignora esa referencia (F-1). |
| `WORLD_REFS_JSON_INVALID` | error | F3 | sí | sí | {ruta} no es JSON valido: {motivo}. |
| `WORLD_REFS_NOT_ARRAY` | error | F3 | sí | sí | {ruta} no es una lista JSON sino {tipo}: F3 documenta un array de objetos con pack_id y version (F-1). |
| `WORLD_REFS_REPARSE` | aviso | F3 | sí | sí | {ruta} es un enlace/junction (reparse point): no se lee. |
| `WORLD_REFS_UNREADABLE` | error | F3 | sí | sí | No se pudo leer {ruta}: {motivo} Los packs referenciados por el mundo {mundo} no se pudieron relacionar. |
| `WORLD_REF_AMBIGUOUS` | aviso | F3 | no | no | El mundo {mundo} referencia {uuid} version {version} y hay {cuantos} candidatos con esa misma identidad en su ambito ({ambito}): {candidatos}. |
| `WORLD_REF_KIND_MISMATCH` | aviso | F3 | no | sí | El mundo {mundo} referencia {uuid} en {archivo}, pero el pack resuelto ({pack}) es de tipo {tipo}: cada archivo deberia listar solo packs de su tipo (F-4). |
| `WORLD_REF_PACK_ID_INVALID` | error | F3 | sí | sí | {ruta}[{indice}].pack_id no tiene el formato hexadecimal documentado: {valor} (F-2/B3). |
| `WORLD_REF_PACK_ID_MISSING` | error | F3 | sí | sí | {ruta}[{indice}] no declara pack_id: la referencia no se puede relacionar con ningun pack (F-2). |
| `WORLD_REF_UNRESOLVED` | error | F3 | no | sí | El mundo {mundo} referencia {uuid} version {version} y no hay ningun pack con ese UUID en su ambito ({ambito}){extra} (F2/F-2). |
| `WORLD_REF_VERSION_FORMAT_UNEXPECTED` | aviso | F3 | no | sí | {ruta}[{indice}].version no sigue el formato de 3 componentes documentado: {valor} (F-3/B5). |
| `WORLD_REF_VERSION_INVALID` | error | F3 | sí | sí | {ruta}[{indice}].version no se puede interpretar como version: {valor} (F-3). |
| `WORLD_REF_VERSION_MISSING` | aviso | F3 | sí | no | {ruta}[{indice}] declara pack_id {valor} sin version: F3 documenta la version definida en el manifiesto del pack, asi que la referencia queda sin contrastar (F-3). |
| `WORLD_REF_VERSION_UNAVAILABLE` | aviso | F3 | no | no | El mundo {mundo} referencia {uuid} version {version}, pero en su ambito ({ambito}) solo estan instaladas las versiones {versiones}: F3 documenta la version del manifiesto y no define sustitucion (F-3/N5). |
| `WORLD_WITHOUT_LEVEL_DAT` | aviso | F2 | sí | sí | La carpeta {ruta} esta en worlds/ pero no tiene level.dat: no parece un mundo valido (F2/E6). |


## 6. Lo que NO se puede verificar con metadatos locales

| # | Cuestión | Por qué no es verificable |
|---|---|---|
| G1 | Experimento "Beta APIs" activo en el mundo | El estado vive en el **mundo**, no en el pack (F4) |
| G2 | Versión de `@minecraft/server` que **tiene** el motor | No está en los metadatos; requiere interrogar al motor |
| G3 | Si una dependencia de API está realmente satisfecha | Depende de la versión del motor y de la semántica `^` (F4) |
| G4 | Orden de apilamiento de resource packs | Configuración del mundo, no de los manifiestos |
| G5 | Si un pack reemplazará o será ignorado al importar | Comportamiento de importación (F1/B6) |
| G6 | Si `min_engine_version` es compatible con el motor instalado | Falta la versión del motor |
| G7 | Qué APIs expone una versión de módulo | Depende de las definiciones de npm (F4) |
| G8 | Efectos de `world_*_pack_history.json` | F3 lo nombra, pero **no documenta su esquema** (N8) |

Además, esta fase **no impone** a mundos existentes los requisitos de una
plantilla publicable (nombre de carpeta ≤ 10 caracteres, `world_icon.jpeg`
800×450, `texts/en_US.lang`, `languages.json`, `lock_template_options`): F3 los
exige **solo** para plantillas (F-6/F-8).

## 7. CLI

```text
python addon_inventory_cli.py [--root DIR] [--json] [--compact]
                              [--world NOMBRE] [--kind behavior|resource]
                              [--severity error|aviso|info|todos] [--detalle]
                              [--lang es|en] [--no-color] [--codes]
```

* `--root` apunta a otra instalación (por defecto, la carpeta del script).
* `--json` imprime el payload completo; `--compact` lo deja en una línea.
  Con `--json`, `--severity` no aplica (se avisa por stderr) porque el payload
  debe poder consumirse íntegro.
* `--world` acota la vista al ámbito de ese mundo (packs propios + compartidos +
  de sistema, que son los que pueden resolver sus referencias) y `--kind` al
  tipo. Ambos se aplican con `addon_inventory.filter_payload`.
  El resumen legible y el JSON cuentan la misma vista; las referencias, sus
  archivos y los diagnósticos también respetan el tipo. Un diagnóstico de
  referencia es del tipo de su archivo de referencias (`world_*_packs.json`):
  `WORLD_REF_KIND_MISMATCH` aparece con el filtro de ese archivo aunque su
  `pack` sea del otro tipo, junto a la referencia `kind_mismatch` (2026-10-21:
  antes desaparecía mientras la referencia seguía a la vista). El código de
  salida sigue calculándose sobre la instalación completa.
* `--codes` imprime el catálogo de códigos (código, gravedad, fuente, parcial y
  mensaje en el idioma activo).
* Cada pack se imprime con su **nombre y su descripción** (`header.description`
  cuando existe), la ruta, el UUID, la versión, el formato, los mundos que lo
  referencian y sus diagnósticos; `--detalle` añade módulos, dependencias de
  packs y de scripting y el estado de resolución.
  La resolución conserva `world_resolutions` (resultado por mundo, también para
  dependencias transitivas). Si los estados difieren, el agregado es
  `context_dependent`; `--world` selecciona su resultado. Un contexto no evaluado
  se presenta como `unchecked`, sin reutilizar el estado de otro mundo.
* Idioma: `--lang` o, si no, `WRAPPER_LANG` (misma regla que `console_lang.L`:
  por defecto inglés). Los mensajes de la CLI se traducen con `L(es, en)` y los
  de los diagnósticos llegan ya redactados desde el catálogo
  (`message_es` / `message_en`), que es una fuente única para CLI y GUI.

**Códigos de salida** (también en `--help` y en el pie de la salida legible):

| Código | Significado |
|---|---|
| `0` | Análisis completado, inventario **completo** y sin diagnósticos `error` |
| `1` | Análisis completado con al menos un diagnóstico `error` |
| `2` | Inventario **parcial**: algo que debía poder analizarse no se pudo analizar |
| `3` | Error de uso (raíz inexistente, argumentos inválidos) |
| `4` | Fallo interno inesperado del analizador |

Si coinciden varios, gana el más alto. El código se calcula **siempre** sobre la
instalación completa, aunque se filtren la vista o los diagnósticos (uso en CI).

## 8. GUI

* `GET /api/addons` (solo `_ensure_local`, lectura) devuelve el mismo payload que
  `addon_inventory_cli.py --json`. Parámetros opcionales `world` y `kind`; un
  `kind` no válido o un mundo desconocido devuelven `400` con el motivo. El
  escaneo corre en el threadpool (`run_in_threadpool`) para no congelar el
  WebSocket ni el bucle de métricas.
* La pestaña **Addons** (`SidebarTabs` → `AddonsSidebar`) muestra: estado del
  inventario (completo/parcial con motivos), contadores por gravedad, filtros por
  mundo y tipo, lista de packs agrupada por ámbito con detalle expandible
  (UUID, formato, motor mínimo, módulos, dependencias de packs con su estado de
  resolución, dependencias de scripting y mundos que los referencian),
  diagnósticos con archivo/campo/fuente y la lista de elementos no analizados.
  El botón **Actualizar análisis** vuelve a consultar el endpoint; un fallo de
  red se presenta con su motivo y botón de reintento (nunca un inventario vacío
  silencioso).
* `dist/` se reconstruye (`npm run build`) porque la pestaña es parte del bundle
  servido.

## 9. Equivalencia CLI ↔ GUI

Ambos consumidores usan `addon_inventory.analyze_addons` (la GUI a través de
`gui_backend/services/addons.py`, sin reimplementar ninguna validación) y el
mismo `filter_payload`. El payload es **determinista** (sin fechas ni
duraciones), de modo que la equivalencia se puede comprobar por igualdad exacta:

* `tests/test_addon_router.py::test_cli_y_gui_producen_el_mismo_payload` compara
  el payload del endpoint, la salida `--json` de la CLI, el servicio y el
  analizador directo sobre la misma instalación temporal.
* `tests/test_addon_router.py::test_cli_y_gui_equivalentes_con_filtros` hace lo
  mismo con `world` + `kind`.
* El filtro de la vista del frontend es un espejo en JS
  (`gui_frontend/src/addonsLogic.js`) y se prueba contra **el mismo fixture**
  que el filtro de Python (`tests/fixtures/addons_payload.json`), de modo que una
  divergencia de semántica rompe uno de los dos tests. El espejo recalcula el
  **resumen de la vista** (`resumenDeVista`, igual que `filter_payload`) y
  conserva el de la instalación en `summary_installation`: sin eso el panel de
  resumen seguía mostrando los totales de la instalación (13 packs, 3 mundos)
  mientras la lista ya estaba filtrada (hallazgo de la revisión en navegador,
  §10.3).
* `tests/test_addon_inventory_fuentes.py::test_estados_de_resolucion_tienen_clave_en_la_gui`
  ata `CLAVES_RESOLUCION` (JS) a los literales de estado que emite el analizador:
  un estado sin clave se pintaría como "pendiente", que es una afirmación falsa
  sobre el enlace (hallazgo §10.3).


## 10. Verificación ejecutada

Los resultados originales de §10.1–§10.4 describen la entrega inicial. La
verificación independiente encontró seis defectos posteriores; correcciones y
resultados actuales en §10.5. El resultado inicial de 994 aprobados no se pudo
reproducir: la propiedad de JSON falló con `null` (993 aprobados, 1 fallo,
2 excluidos).

Fecha: **2026-10-06**. Entorno: `.venv` del proyecto (Python 3.11.8, httpx
0.28.1 — presente, de modo que los tests de TestClient **no** se saltan en
silencio), Node 24.15.0. No se arrancó BDS ni se ejecutó ningún e2e.

| Comando | Resultado |
|---|---|
| `python -m ruff check .` | `All checks passed!` |
| `python -m pytest tests -m "not e2e" -q` | `994 passed, 2 deselected` (221 s) |
| `npm run lint` (`gui_frontend/`) | oxlint: `0 warnings and 0 errors` (43 archivos) |
| `npm test` (`gui_frontend/`) | vitest: `22 passed` (3 archivos) |
| `npm run build` (`gui_frontend/`) | `dist/` reconstruido (`dist/index.html` + `dist/assets/index-<hash>.js` / `.css`) |

### 10.1 Instalaciones temporales (analizador y CLI)

Los tests cubren la matriz completa sobre instalaciones sintéticas: packs
válidos y ausencia de packs, packs compartidos y propios de varios mundos,
dependencias ausentes, versiones coincidentes y discrepantes, dependencias de
scripting (estable, `beta`, `internal`, no semver, sin versión), UUID repetidos
dentro y fuera del mismo ámbito, referencias rotas y ambiguas, JSON inválido,
estructuras inesperadas, campos adicionales, formatos desconocidos, manifiesto
ilegible, junction/reparse y raíz inexistente.

Además se ejercitó la CLI a mano sobre una instalación sintética de
**14 packs / 3 mundos** que reproduce todos esos casos a la vez:

* salida legible (agrupada por ámbito, con mundos y diagnósticos) y `--json`,
  `--compact`, `--world`, `--kind`, `--severity`, `--detalle`, `--codes` y
  `--lang es|en`;
* los cinco **códigos de salida documentados** verificados en vivo:
  `0` (instalación limpia y completa), `1` (completa con 1 error: UUID
  duplicado), `2` (parcial: la sintética, con errores y archivos no
  analizables), `3` (raíz inexistente y argumento inválido) y `4` (fallo interno
  del analizador, ejercitado en proceso en
  `test_fallo_interno_del_analizador_devuelve_4`).

### 10.2 Ejercicio de la pestaña en un navegador (entorno aislado)

* **Entorno**: instalación sintética en `%TEMP%\qa_addons_root` (el código real
  entra por *junctions* —`gui_backend/`, `gui_frontend/`, `web/`, `tools/`— de
  modo que `config.BASE_DIR` se calcula sobre esa carpeta temporal) más
  `%TEMP%\qa_addons_externo` para las junctions de pack y de mundo. La
  instalación real **no** se usó para nada de esto.
* **Arranque**: `python -m uvicorn server_gui_server:app --host 127.0.0.1
  --port 18771` con `cwd` en la carpeta temporal (el `__main__` del entrypoint
  solo añade `webbrowser.open`).
* **Navegador**: Chrome 151 headless por CDP (agent-browser 0.36), ventana
  1440×980; no se declara como verificación un test unitario.
* **Comprobado**:
  * **Carga** de la pestaña: 13 packs / 3 mundos, estado PARCIAL con sus 11
    motivos, 14 errores / 20 avisos / 2 informativos y la lista de no
    analizados.
  * **Filtro por mundo** (Beta): 12 packs, 1 mundo, referencias 1/1, 10
    errores / 15 avisos / 2 informativos. **Filtro por tipo** junto con mundo
    (Beta + Recursos): 3 packs, 1 mundo, 1 error / 2 avisos / 1 informativo.
    Ambas cifras coinciden **exactamente** con `filter_payload` en Python sobre
    la misma instalación (comprobado con la CLI y con el endpoint).
  * **Detalle** expandible de un pack: descripción, UUID, formato, motor
    mínimo, módulos (tipo/UUID/versión), dependencias de packs con su estado de
    resolución (`resuelta` / `sin resolver` / `otra versión instalada`),
    dependencias de scripting (incluida la marca `beta`) y mundos que lo
    referencian.
  * **Actualizar análisis**: se añadió un pack en disco y el botón lo detectó
    (13 → 14 packs, con el pack nuevo en la lista): no sirve una caché.
  * **Errores**: con la red de `/api/addons` abortada, la pestaña muestra una
    tarjeta con el motivo (`Failed to fetch`) y el botón **Reintentar**; al
    restablecer la red, «Reintentar» recupera el inventario (nunca un
    inventario vacío silencioso).
  * **Idiomas**: los rótulos nuevos se ven en ES («otra versión instalada») y
    EN («other installed version»).
* Nota de herramienta: `wait --load networkidle` **no** sirve contra esta GUI
  (el WebSocket `/ws` mantiene la red ocupada): usar esperas por texto,
  elemento o `domcontentloaded`.

### 10.3 Hallazgos de la revisión en navegador (corregidos)

Dos defectos reales de la pestaña, que los tests unitarios previos no cubrían
(el espejo JS del filtro no se comparaba campo a campo con el de Python):

1. **Estado de resolución equivocado en las dependencias de packs.**
   El analizador emite **una entrada de resolución por (uuid, version)**, pero
   la GUI buscaba por `uuid` a secas: una dependencia del mismo UUID con **otra**
   versión mostraba `[resuelta]` aunque el diagnóstico dijera lo contrario.
   Corregido con `resolucionDe(pack, dep)` en `addonsLogic.js` (empareja `uuid`
   **y** `version`; sin coincidencia exacta no se pinta estado, nunca un estado
   ajeno) y cubierto en `gui_frontend/tests/addons.test.js`.
2. **El resumen no seguía al filtro.** `filtrarInventario` filtraba packs,
   mundos y diagnósticos, pero dejaba el `summary` intacto: con el filtro Beta
   el panel seguía diciendo «13 packs / 3 mundos» mientras la lista mostraba 12.
   El espejo JS ahora recalcula el resumen (`resumenDeVista`) igual que
   `filter_payload` y conserva el de la instalación en `summary_installation`.
3. **Estado `version_mismatch` sin traducción.** Faltaba en el mapa de la GUI,
   de modo que se habría pintado como «pendiente». Se añadieron
   `addonsRefVersionMismatch` y `addonsRefKindMismatch` (ES/EN) y un test
   anti-drift que ata `CLAVES_RESOLUCION` a los literales de estado del
   analizador (si mañana se añade un estado en Python sin clave, la suite falla).
4. **«Alfa, Alfa» en «mundos que lo referencian».** Un mundo que referencia el
   mismo pack dos veces (o en los dos archivos) lo listaba repetido. La lista se
   presenta como conjunto ordenado; las referencias del mundo y sus diagnósticos
   siguen conservando cada entrada.

### 10.4 Los datos analizados no se modifican

Huella `ruta|tamaño|mtime_ns|sha256` de las raíces analizadas (`behavior_packs`,
`resource_packs`, `system_*`, `worlds` y `server.properties`), tomada **antes y
después** de la CLI (legible, `--json`, filtros), de tres llamadas al endpoint
`GET /api/addons` y del ejercicio completo en el navegador:

| Instalación | Archivos en la huella | Diferencias |
|---|---|---|
| Sintética (`%TEMP%\qa_addons_root`) | 24 | **0** |
| Real del repositorio (`TESTTEST`) | 11 940 | **0** |


### 10.5 Correcciones de la verificación independiente (2026-10-06)

Se corrigieron los seis hallazgos de la entrega inicial:

1. **`metadata.generated_with`** ahora exige el objeto del ejemplo oficial F1:
   claves de herramienta y listas de versiones SemVer. Acepta prerelease/build,
   rechaza listas `tool_name/tool_version`, valores `null`, tipos inesperados y
   ceros iniciales prohibidos por SemVer. F1 no impone cardinalidad mínima.
2. **JSON tolerante** elimina comas finales solo fuera de strings. Conserva
   `Texto, }`, `Ejemplo, ]`, claves con esos caracteres y escapes; los comentarios
   de bloque no fusionan tokens y un bloque sin cerrar se rechaza.
3. **Dependencias por mundo** combinan raíces compartidas/de sistema con los
   packs del mundo consumidor, también a través de dependencias transitivas.
   Una visita por `(pack, mundo)` acota ciclos. `world_resolutions` conserva cada
   resultado y el agregado usa `context_dependent` si los estados difieren.
   Los diagnósticos indican su mundo y no contaminan vistas de otros mundos.
   Sin consumidores conocidos se comprueban únicamente las raíces compartidas/
   de sistema; un mundo que no se evaluó aparece como `unchecked` en su vista.
4. **Filtro por tipo** acota referencias, archivos de referencias y diagnósticos
   en Python y JS. Conserva avisos generales del mundo, incluso si el mundo se
   llama `behavior` o `resource`. El resumen cuenta las referencias filtradas.
5. **Resumen CLI legible** usa la misma vista filtrada que JSON/GUI. El código
   de salida mantiene su contrato sobre la instalación completa.
6. **Propiedad de Hypothesis** distingue el valor `None` del indicador de error:
   `null` es un éxito válido. Se fijaron ejemplos explícitos de `null`, signos de
   puntuación en strings y claves, además de los ejemplos generados.

La GUI y `--detalle` muestran los resultados por mundo; el nuevo estado agregado
tiene traducción ES/EN. El contrato en `docs/API_CONTRACT.md` describe la
ampliación de `dependency_resolution` sin cambiar `schema_version: 1`.

Antes de corregir, la selección de regresiones Python falló en 13 casos y los
tres nuevos casos iniciales de frontend también fallaron. Tras corregir pasan
las pruebas relacionadas, incluidos los casos de ciclos y nombres de mundo.

La verificación de disponibilidad por mundo es una inferencia estática de F2,
no una comprobación de que BDS cargue el pack. Las reglas del objeto generado
se contrastaron de nuevo con [F1](https://learn.microsoft.com/en-us/minecraft/creator/reference/content/addonsreference/packmanifest?view=minecraft-bedrock-stable)
y [SemVer 2.0.0](https://semver.org/).

Verificación de esta corrección:

| Comprobación | Resultado |
|---|---|
| Regresiones relacionadas, guards HTTP y propiedades (`pytest` sobre los seis módulos afectados) | 158 aprobadas |
| Suite completa: `python -m pytest tests -m "not e2e" -q --tb=short` | 1016 aprobadas, 2 excluidas; 356,60 s |
| `python -m ruff check .` | aprobado |
| `npm run lint` / `npm test` | lint aprobado; 27 tests aprobados |
| `npm run build` | `index-CMJycQDE.js` + `index-CHEJ5op0.css` |
| CLI real ↔ API real ↔ espejo JS ejecutado en Node | igualdad exacta en cinco combinaciones de mundo/tipo |
| Navegador aislado, servido por `create_app()` | estados por mundo y ES/EN correctos; JSONC intacto; Alfa + Recursos = 4 packs, 1 mundo, 1/1 referencias, 0 errores/avisos; error de red y reintento recuperados |
| Huella `ruta/tamaño/mtime_ns/SHA256` | 12 archivos sintéticos y 11 940 reales; 0 diferencias tras consultas |

El código de salida de la CLI filtrada continúa reflejando la instalación
completa: en la sintética devolvió `1` por un error fuera de la vista seleccionada,
mientras el resumen filtrado mostraba correctamente cero errores. No se
arrancó BDS, no se ejecutaron e2e ni se sincronizaron/publicaron los cambios.
El navegador y el servidor temporal de QA se cerraron al terminar.

## 11. Límites conocidos

1. Es un análisis **estático de metadatos**: no abre el mundo (`level.dat`) ni
   consulta al motor. "Referenciado por un mundo" **no** significa "cargado
   correctamente por BDS".
2. Los mensajes del catálogo se escriben **sin acentos** (convención de consola
   del proyecto, compatible con `cp1252` en consolas antiguas). La CLI fuerza
   UTF-8 cuando la salida está redirigida y usa `errors="replace"` para no
   fallar con nombres de pack acentuados.
3. Un pack detrás de una junction/reparse point **no** se sigue (se reporta y el
   inventario queda parcial): es una decisión de seguridad de rutas, no un
   defecto del pack.
4. `MANIFEST_REPARSE` (manifiesto que es un enlace) solo se puede provocar con
   privilegios de administrador/modo desarrollador; en la suite se ejercita
   forzando la detección por el módulo dueño (`auto_backup._es_punto_reparse`).
5. La detección de "representación empaquetada" se basa en la extensión del
   archivo dentro de las carpetas de packs; no se abre el archivo.
6. `min_engine_version` se extrae y se valida su formato, pero **no** se
   contrasta con ninguna versión del motor (G6) ni se usa para deducir APIs
   disponibles (N7).
7. Los packs propios de un mundo solo son candidatos para **ese** mundo (E4);
   un UUID que solo existe en otro mundo se reporta como referencia sin
   resolver, indicando dónde existe.

## 12. Límites de la verificación (§10)

1. El ejercicio en navegador fue con **Chrome headless por CDP** contra una
   instalación sintética servida por el mismo `create_app()`; no sustituye a
   abrir la GUI clásica con el servidor real en marcha.
2. No se arrancó BDS ni se ejecutó ningún e2e: **no** se comprobó que BDS cargue
   los packs (fuera del alcance de esta fase, ver G1–G8).
3. «Permisos insuficientes» (`MANIFEST_UNREADABLE`, `SCOPE_ENTRY_UNREADABLE`) se
   cubre con tests unitarios (manifiesto que es una carpeta, `open` mockeado).
   No se forzaron ACLs en el entorno de navegador para no alterar permisos del
   sistema de archivos del usuario.
4. El código de salida `4` solo se ejercita **en proceso** (con el analizador
   monkeypatcheado para fallar): la CLI real no falla a voluntad.
5. Las junctions de pack y de mundo del entorno sintético se crearon con
   `New-Item -ItemType Junction` (sin privilegios); el caso `MANIFEST_REPARSE`
   sigue requiriendo administrador/modo desarrollador (límite 4 de §11).
