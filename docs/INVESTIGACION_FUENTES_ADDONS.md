# Investigación de fuentes oficiales: addons de Minecraft Bedrock

**Base normativa para un analizador de inventario / diagnóstico de behavior packs y resource packs**

- **Fecha de consulta:** 2026-10-06 (ISO 8601)
- **Ámbito:** documentación oficial de Microsoft (Microsoft Learn) + repositorio oficial `microsoft/minecraft-samples`.
- **Naturaleza:** investigación **documental**. No se ejecutó ninguna acción sobre instalaciones de Minecraft, ni se modificó ningún archivo del repositorio salvo este informe.
- **Regla de oro de este informe:** toda afirmación se respalda con una **cita literal** de la fuente. Cuando la documentación **no** dice algo, se marca explícitamente como **NO DETERMINADO** en lugar de inferirlo como si fuera norma.

---

## 1. Fecha de consulta y estado de las fuentes

Todas las consultas se realizaron el **2026-10-06**. Las páginas de Microsoft Learn se solicitaron con el parámetro
`?view=minecraft-bedrock-stable` (canal **stable**, no preview) cuando la fuente lo indicaba.

| ID | URL exacta consultada | Estado | Notas |
| :--- | :--- | :--- | :--- |
| **F1** | `https://learn.microsoft.com/en-us/minecraft/creator/reference/content/addonsreference/packmanifest?view=minecraft-bedrock-stable` | **RESPONDIÓ** (HTTP 200) | Referencia de `manifest.json`. Página marca *Last updated on 2025-08-04*. |
| **F2** | `https://learn.microsoft.com/en-us/minecraft/creator/documents/bedrockserver/getting-started?view=minecraft-bedrock-stable` | **RESPONDIÓ** (HTTP 200) | "Getting Started with Bedrock Dedicated Server". *Last updated on 2025-06-25*. Contiene las secciones `Running the server` y `Shared resource and behavior packs`. |
| **F3** | `https://learn.microsoft.com/es-mx/minecraft/creator/documents/packagingaworldtemplate` | **RESPONDIÓ** (HTTP 200) | "Cómo empaquetar una plantilla de mundo" (es-mx). *Last updated on 2022-04-26*. Contiene las secciones `world_behavior_packs.json y world_resource_packs.json`. |
| **F4** | `https://learn.microsoft.com/en-us/minecraft/creator/documents/scripting/versioning?view=minecraft-bedrock-stable` | **RESPONDIÓ** (HTTP 200) | "Script Module Versioning". *Last updated on 2025-07-17*. |
| **F5** | `https://github.com/microsoft/minecraft-samples` | **RESPONDIÓ** | Leído vía API de GitHub y `raw.githubusercontent.com` (ver §9 para rutas, commit y licencia). |

### 1.1 Sustituciones y fuentes complementarias (documentadas)

No fue necesario sustituir ninguna de las cinco fuentes obligatorias: **las cinco respondieron**. Se añadieron fuentes
complementarias solo para *verificar* o *cerrar huecos*, y se documentan aquí con su motivo:

| Fuente complementaria | URL exacta | Motivo |
| :--- | :--- | :--- |
| **C1** — Fuente cruda de F1 | `https://raw.githubusercontent.com/MicrosoftDocs/minecraft-creator/main/creator/Reference/Content/AddonsReference/PackManifest.md` | Verificar que el render de Learn no hubiera omitido filas de la tabla `modules` (en particular un campo `entry`). **Confirmado: la fuente cruda tampoco documenta `entry`.** |
| **C2** — Fuente cruda de F4 | `https://raw.githubusercontent.com/MicrosoftDocs/minecraft-creator/main/creator/Documents/scripting/versioning.md` | Verificar el texto exacto de F4 y comprobar si menciona `min_engine_version`. **Confirmado: F4 no menciona `min_engine_version` en ninguna línea.** |
| **C3** — Equivalente en inglés de F3 | `https://learn.microsoft.com/en-us/minecraft/creator/documents/packagingaworldtemplate` → **redirige** a `https://learn.microsoft.com/en-us/minecraft/creator/documents/createaworldtemplate?view=minecraft-bedrock-stable` | La URL inglesa `packagingaworldtemplate` **fue renombrada** a `createaworldtemplate`. Se usó como **cruce de F3**: aporta dos frases que la versión es-mx **no** incluye (consecuencia de UUIDs duplicados y estructura de los `world_*_packs.json`). Se cita como **F3-en**. |
| **C4** — Tutorial de resource packs | `https://learn.microsoft.com/en-us/minecraft/creator/documents/resourcepack?view=minecraft-bedrock-stable` | Semántica de UUID y de "Minimum Engine Version" en el flujo de creación de un pack. Se cita como **C4**. |
| **C5** — Tutorial de behavior packs | `https://learn.microsoft.com/en-us/minecraft/creator/documents/behaviorpack?view=minecraft-bedrock-stable` | Confirma el rol de `modules` y `dependencies`. Se cita como **C5**. |
| **C6** — Equivalente de la página de ejemplo de manifest | `https://learn.microsoft.com/en-us/minecraft/creator/reference/content/addonsreference/examples/addonmanifest?view=minecraft-bedrock-stable` | **Redirige a F1** (misma página `PackManifest`). Confirma que F1 es la referencia canónica y que no existe una tabla adicional de campos. |
| **C7** — Scripting V2 Overview | `https://learn.microsoft.com/en-us/minecraft/creator/documents/scripting/v2-overview?view=minecraft-bedrock-stable` | Contexto sobre `2.0.0-beta` y el requisito del experimento "Beta APIs". Se cita como **C7**. |

### 1.2 Consultas que fallaron (y cómo se resolvieron)

| Intento | Resultado | Resolución |
| :--- | :--- | :--- |
| `https://learn.microsoft.com/en-us/minecraft/creator/documents/faq?view=minecraft-bedrock-stable` | **HTTP 404** | No sustituida: no era una fuente obligatoria y su contenido no es necesario. Se documenta el 404. |
| `https://learn.microsoft.com/en-us/minecraft/creator/documents/scripting/scriptingintroduction?view=minecraft-bedrock-stable` | **HTTP 404** | Slug inexistente. No sustituida; el material de scripting se cubrió con F4 y C7. |
| Búsqueda web (`web_search`) | **Error HTTP 404** del endpoint configurado (`https://api.parallel.ai/v1/search/messages`) | **Limitación de herramienta, no de la fuente.** No se pudo usar búsqueda web. Todo el informe se construyó con `web_fetch` directo sobre URLs conocidas de Microsoft Learn y de la API de GitHub. Si en el futuro se necesita cerrar un hueco con búsqueda, hay que configurar el endpoint en *Settings > Plugins > Plugin configuration > Web search*. |

> **Nota de reproducibilidad:** los textos citados de F1 y F4 se cotejaron **byte a byte** contra su fuente cruda
> (C1, C2) para descartar diferencias de renderizado. Las citas de F2, F3, C4, C5, C7 provienen del HTML renderizado.

---

## 2. `manifest.json`: estructura, valores válidos y semántica

### 2.1 Propiedades de primer nivel

> "The manifest file contains all the basic information about the pack that Minecraft needs to identify it. The tables below contain all the components of the manifest, their individual properties, and what they mean." — **F1**

| Propiedad | Cita literal de F1 |
| :--- | :--- |
| `format_version` | "The syntax version used in the manifest file. This may be 1 for skin packs or 2 for resource, behavior, and world templates. Version 3 is a new update of the manifest currently in preview." |
| `header` | "Section containing information regarding the name of the pack, description, and other features that are public facing." |
| `modules` | "Section containing information regarding the type of content that is being brought in." |
| `dependencies` | "Section containing definitions for any other packs that are required in order for this manifest.json file to work." |
| `capabilities` | "Section containing optional features that can be enabled in Minecraft." |
| `metadata` | "Section containing the metadata about the file such as authors and licensing information." |

### 2.2 Semántica de `format_version`: qué significa 1 y qué significa 2

La documentación es explícita y **asocia el número al tipo de pack**, no a una "versión del formato" incremental:

> "This may be **1 for skin packs** or **2 for resource, behavior, and world templates**. Version 3 is a new update of the manifest currently in preview." — **F1**

Reglas derivadas y verificables:

1. `format_version: 1` → **skin packs**.
2. `format_version: 2` → **resource packs, behavior packs y world templates**.
3. `format_version: 3` → **preview** (introducido en Minecraft preview 1.21.110 y superiores). F1 advierte además de un defecto conocido:

> "There is also a current issue with version 3 processing where `<metadata>/<author>` properties are required to be set in a version 3 manifest. We expect to make the author property optional for version 3 in a future update." — **F1**

**Implicación crítica para el analizador:** en `format_version` 3, los campos de versión (`header.version`,
`modules[].version`, `min_engine_version`, `base_game_version`) pasan a ser **strings semver**, no vectores.
F1 lo repite en cada uno de esos campos:

> "In version 3, currently in preview, you must use a string for version." — **F1** (repetido en `version`, `min_engine_version`, `base_game_version` y `modules[].version`)

> "The main differences are the usage of semver-style strings for version signifiers, and additional support for custom pack settings." — **F1**

Por tanto, un validador que **solo** acepte `[a, b, c]` producirá **falsos positivos** en manifiestos v3 legítimos.
El tipo documentado es, literalmente: `Vector [a, b, c] or SemVer String`.

### 2.3 Estructura de `header`

| Campo | Tipo documentado | Cita literal de F1 |
| :--- | :--- | :--- |
| `name` | String | "This is the name of the pack as it appears within Minecraft. **This is a required field.**" |
| `description` | String | "This is a short description of the pack. It will appear in the game below the name of the pack. We recommend keeping it to 1-2 lines." |
| `uuid` | String | "This is a special type of identifier that uniquely identifies this pack from any other pack. UUIDs are written in the format `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` where each x is a hexadecimal value (0-9 or a-f). We recommend using an online service to generate this and guarantee their uniqueness." |
| `version` | Vector `[a, b, c]` o SemVer String | "This is the version of your pack in the format `[majorVersion, minorVersion, revision]`. The version number is used when importing a pack that has been imported before. The new pack will replace the old one if the version is higher, and ignored if it's the same or lower." |
| `min_engine_version` | Vector `[a, b, c]` o SemVer String | "This is the minimum version of the game that this pack was written for. **This is a required field for resource and behavior packs.** This helps the game identify whether any backwards compatibility is needed for your pack. You should always use the highest version currently available when creating packs." |
| `pack_scope` | String | "For resource packs, an optional string that specifies whether this resource pack can be used across the game or at an individual world level. Valid values are `"world"` … `"global"` … and `"any"` … If not specified, this is interpreted as `"any"`." |
| `base_game_version` | Vector o SemVer String | "(world template manifest JSON only). In version 3, currently in preview, you must use a string for version." |
| `allow_random_seed` | Boolean | "(world template manifest JSON only)" |
| `lock_template_options` | Boolean | "This option is required for any world templates. This will lock the player from modifying the options of the world. (world template manifest JSON only)" |

**Precisión importante sobre `min_engine_version` "required":** F1 acota el requisito a
**resource y behavior packs**. F1 **no** declara `min_engine_version` obligatorio para world templates ni para skin packs.
Un analizador no debería exigirlo en un `world_template`.

**Precisión sobre `description`:** F1 dice "This is a short description of the pack" y "We recommend keeping it to 1-2 lines",
pero **no** usa la palabra "required". Solo `name` lleva la marca explícita "This is a required field".
→ *Que `description` sea obligatoria queda* **NO DETERMINADO** *en F1* (ver §11).

### 2.4 Estructura de `modules`

> "Section containing information regarding the type of content that is being brought in." — **F1**

| Campo | Tipo documentado | Cita literal de F1 |
| :--- | :--- | :--- |
| `type` | String | "This is the type of the module. Can be any of the following: `resources`, `data`, `world_template` or `script`." |
| `uuid` | String | "This is a unique identifier for the module in the same format as the pack's UUID in the header. **This should be different from the pack's UUID, and different for every module.**" |
| `version` | Vector `[a, b, c]` o SemVer String | "This is the version of the module in the same format as the pack's version in the header. This can be used to further identify changes in your pack. In version 3, currently in preview, you must use a string for version." |
| `description` | String | "This is a short description of the module. **This is not user-facing at the moment** but is a good place to remind yourself why the module is defined." |
| `language` | String | "**Only present if `type` is `script`.** This indicates the language in which scripts are written in the pack. The only supported value is `javascript`." |

#### `entry` — NO DETERMINADO en F1–F5

El campo `entry` (habitual en módulos `script` de la práctica real) **no aparece en la documentación consultada**:

- F1 **no** lo lista en la tabla de `modules` (verificado también contra la fuente cruda **C1**).
- F2, F3, F4 y F5 **no** lo mencionan.
- El ejemplo de behavior pack de F1 tiene un módulo `script`-like (`"type": "client_data"`) **sin** `entry`.

→ **NO DETERMINADO**: no hay fuente oficial consultada que documente `entry` (nombre exacto, obligatoriedad,
formato de ruta, ni si es relativo a la raíz del pack). **Qué falta:** un ejemplo oficial de módulo `"type": "script"`
completo (con `entry` y `language`) y/o una fila `entry` en la tabla de `modules` de F1.

#### Discrepancia documentada: `client_data` no está en la lista de tipos válidos

El ejemplo oficial de F1 usa un tipo que **su propia tabla no documenta**:

```json
{
    "description": "Example client scripts module",
    "type": "client_data",
    "uuid": "c05a992e-482a-455f-898c-58bbb4975e47",
    "version": [1, 0, 0]
}
```

F1 dice que `type` "Can be any of the following: `resources`, `data`, `world_template` or `script`", pero su ejemplo
emplea `"client_data"`. **Consecuencia normativa para el analizador:** la lista de tipos **no debe tratarse como un
enum cerrado con fallo duro**; un tipo desconocido debe reportarse como *advertencia informativa*, no como error,
porque la propia documentación oficial se sale de su lista. → **Ambigüedad documental registrada** (ver §11).

### 2.5 Estructura de `dependencies`

> "Section containing definitions for any other packs that are required in order for this manifest.json file to work." — **F1**

| Campo | Tipo documentado | Cita literal de F1 |
| :--- | :--- | :--- |
| `uuid` | String | "This is the unique identifier of the pack that this pack depends on. **It needs to be the exact same UUID that the pack has defined in the header section of its manifest file.**" |
| `module_name` | String | "For dependencies on built-in scripting modules, contains the name of the module. (for example, `@minecraft/server`)" |
| `version` | Vector `[a, b, c]` o SemVer String | "This is the specific version of the pack that your pack depends on. **Should match the version the other pack has in its manifest file.**" |

Existen por tanto **dos formas** de dependencia, y se distinguen por la **clave presente**:

1. **Dependencia de pack**: `{ "uuid": …, "version": [a, b, c] }`
2. **Dependencia de módulo de scripting**: `{ "module_name": "@minecraft/server", "version": "1.9.0" }`

C5 (tutorial de behavior packs) confirma el propósito: "**dependencies** - Creates a link between behavior packs and
resource packs to add custom textures and visuals to Minecraft."

### 2.6 `capabilities`, `metadata` y `settings` (contexto)

- `capabilities` (F1): valores documentados `chemistry`, `editorExtension`, `experimental_custom_ui`, `raytraced`, `pbr`.
- `metadata` (F1): `authors` (Array), `license` (String), `url` (String), `product_type` (String; "The only supported value is `"addon"`"),
  y `generated_with` (JSON Object) con una regla de validación concreta y comprobable:
  El ejemplo de F1 representa el objeto como `{"example_tool": ["1.0.0", "1.1.0"]}`:
  cada clave es una herramienta y su valor una lista de versiones. No es una lista
  de objetos `tool_name/tool_version`. F1 no especifica cardinalidad mínima; no
  se rechazan un objeto vacío ni listas vacías. Las versiones no vacías se validan
  según [SemVer 2.0.0](https://semver.org/), incluidos prerelease y metadatos de build.
  > "The tool names are strings that must be `[a-zA-Z0-9_-]` and 32 characters maximum. The tool version number are semver strings for each version that modified the manifest.json file." — **F1**
- `settings` (F1): **solo manifest version 3, experimental/preview**; lista ordenada de `label`, `toggle`, `slider`.
  > "Note that this feature is experimental and subject to change or removal in future builds." — **F1**

---

## 3. Reglas documentadas sobre UUID

### 3.1 Formato esperado

> "UUIDs are written in the format `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` where each x is a hexadecimal value (0-9 or a-f)." — **F1**

Regex derivable y estricta: `^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`

**Ambigüedad de caja:** F1 dice "each x is a hexadecimal value (0-9 or a-f)" — enumera solo **minúsculas**.
La documentación **no** aclara si mayúsculas son válidas. → **NO DETERMINADO**: se recomienda aceptar
mayúsculas con normalización a minúsculas antes de comparar, en lugar de rechazarlas.

### 3.2 Unicidad

Dos niveles, ambos documentados:

1. **Un UUID identifica un pack frente a cualquier otro pack:**
   > "This is a special type of identifier that **uniquely identifies this pack from any other pack**." — **F1**
2. **El UUID de cada módulo debe ser distinto del UUID del header y distinto entre módulos:**
   > "This should be different from the pack's UUID, and different for every module." — **F1** (`modules[].uuid`)

C4 refuerza la intención de diseño y la obligatoriedad práctica de dos UUIDs distintos:

> "For Minecraft, the UUID is used to define a specific pack and **to prevent any duplicate software from causing issues**. For the header and modules, there will need to be **two different UUID numbers** entered in each of the `"uuid"` fields between the quotes." — **C4**

Y en la sección de troubleshooting, C4 lo usa como primera causa a descartar cuando el pack no aparece:

> "Are there two different UUIDs in the **manifest.json** header and modules section?" — **C4**

F3, para world templates, es igualmente explícito:

> "`uuid`: debes generar **dos UUID diferentes** en este sitio" — **F3**

### 3.3 Qué dice la documentación sobre reutilizar / duplicar UUIDs

Esta es la evidencia **más fuerte** encontrada, y está en el equivalente inglés de F3 (**F3-en**,
`createaworldtemplate`), en su sección *Troubleshooting*:

> "You will get **"Failed to import" errors** if you already have content with the same UUIDs loaded into your `com.mojang` folder." — **F3-en**

Y a continuación describe el *workaround* (limpiar las carpetas de mundos/plantillas **en lugar de** generar UUIDs nuevos),
lo que confirma que la colisión de UUID es un fallo real de importación:

> "Instead of creating new UUIDs for each manifest.json file, you can clean out the contents of the MinecraftWorlds and Minecraft Templates folders in your `com.mojang` folder." — **F3-en**

**Alcance real de la comprobación:** la documentación describe el efecto de UUIDs duplicados **cargados en la misma
instalación / importados en el mismo `com.mojang`**. No promete detección global ni advierte de todos los efectos
secundarios. Un analizador **sí** puede detectar colisiones dentro del conjunto de packs que escanea (mismo
`behavior_packs/`, `resource_packs/`, mundo, etc.), pero **no** puede afirmar nada sobre unicidad global.

→ **NO DETERMINADO**: F1–F5 **no** documentan qué ocurre exactamente si dos packs con el mismo `header.uuid` pero
**versiones distintas** conviven en el mismo directorio (si gana el de versión mayor, si se produce error, o si
el comportamiento depende del orden de carga). *Qué falta:* una frase oficial sobre resolución de colisiones
con UUID igual y versión distinta.

---

## 4. Reglas sobre `version` y versiones de dependencias

### 4.1 Formato de `version`: 3 componentes `[major, minor, patch]`

> "This is the version of your pack in the format `[majorVersion, minorVersion, revision]`." — **F1** (`header.version`)

> "This is the version of the module in the same format as the pack's version in the header." — **F1** (`modules[].version`)

F1 introduce el término **`revision`** para el tercer componente (equivalente al *patch* de semver).
El tipo documentado admite **dos representaciones**: `Vector [a, b, c]` **o** `SemVer String` (obligatorio string en v3 preview).

### 4.2 Semántica de la versión del pack en la importación

> "The version number is used when importing a pack that has been imported before. **The new pack will replace the old one if the version is higher, and ignored if it's the same or lower.**" — **F1**

Consecuencia verificable: con **mismo UUID** y versión **igual o inferior**, la importación se **ignora**.
Esto explica el síntoma clásico "actualicé el pack y el juego sigue mostrando el viejo": el analizador puede
diagnosticarlo comparando `header.uuid` + `header.version` entre lo instalado y lo que se pretende instalar.

### 4.3 Dependencia de pack (clave `uuid` + `version`): relación exigida

**Frase exacta de F1** (columna `version` de la tabla `dependencies`):

> "This is the specific version of the pack that your pack depends on. **Should match the version the other pack has in its manifest file.**"

Y la frase exacta sobre el `uuid` de esa misma dependencia:

> "This is the unique identifier of the pack that this pack depends on. **It needs to be the exact same UUID that the pack has defined in the header section of its manifest file.**"

**Lectura normativa, sin inventar:**

| Aspecto | Qué dice la doc | Fuerza |
| :--- | :--- | :--- |
| `uuid` de la dependencia | "needs to be the **exact same** UUID" que el `header.uuid` del pack dependido | Redacción **imperativa** ("needs to be") |
| `version` de la dependencia | "**Should match** the version the other pack has in its manifest file" | Redacción de **recomendación** ("Should match"), no "must match" |

**Conclusión honesta:** la documentación **no** exige literalmente que la versión de la dependencia sea
*igual* (ni *menor o igual*, ni *mayor o igual*) a la del pack dependido: dice que **"debería coincidir"** con
la versión declarada en el manifiesto del otro pack. Por tanto:

- Una **discrepancia exacta de versión** debe reportarse como **advertencia** ("no coincide con la versión declarada por el pack dependido"), no como error fatal, porque la doc usa "Should".
- **NO DETERMINADO:** qué ocurre si la versión de la dependencia es **menor** que la del pack instalado
  (¿se satisface igual?, ¿como el `^` de npm en APIs estables de F4?). F1 no lo dice para dependencias de pack.
  *Qué falta:* una frase que defina el operador de comparación (igualdad exacta vs. rango mínimo).

### 4.4 Dependencia de módulo de scripting (clave `module_name` + `version`)

**Frase exacta de F1** sobre la clave que la identifica:

> "For dependencies on built-in scripting modules, contains the name of the module. (for example, `@minecraft/server`)"

El único ejemplo oficial de F1 es:

```json
{
    "module_name": "@minecraft/server",
    "version": "1.9.0"
}
```

**Nota de tipo muy relevante:** en ese ejemplo, la `version` de la dependencia de scripting es un **string semver**
(`"1.9.0"`), mientras que la dependencia de pack usa un **vector** (`[1, 0, 0]`) en el mismo array `dependencies`.
Un analizador debe aceptar **ambas formas dentro del mismo array** y discriminarlas por la clave presente
(`uuid` vs `module_name`), no por el tipo del valor.

**Reglas de versión de módulos de scripting: F4** (ver §8 para el detalle). Las frases clave son:

> "Semantic versions use a numeric version number of `[major].[minor].[patch]` with an optional suffix." — **F4**

> "a stable track (for example, version `1.1.0`)" / "a beta track (for example, version `1.3.0-beta`)" / "an internal track (for example, version `1.4.0-internal`)" — **F4**

**Qué pasa con las versiones beta (`-beta`) — frase exacta de F4:**

> "API modules in the beta track are labeled with the `-beta` suffix - for example, `1.2.0-beta`. **Beta APIs do not follow the rules of semantic versioning. With beta APIs, no backwards compatibility is implied**, and even minor version increments can include backwards-compatibility breaking changes like the removal of properties or methods. Moreover, with every major release of Minecraft, it is likely that several `-beta` modules will increment their version number (for example, from `1.2.0-beta` to `1.3.0-beta`) **without having an automatic upgrade from the old `-beta` version to the next**. As a consequence, **you may need to update the version number of `manifest.json` dependencies at every major release if you are using `-beta` APIs**." — **F4**

**Y el requisito de experimento — frase exacta de F4:**

> "**In order to use -beta APIs, you must enable the "Beta APIs" experiment within worlds that use these behavior packs.**" — **F4** (bloque `[!IMPORTANT]`)

**Sobre la pista interna (`-internal`):**

> "Internal APIs are not functional or supported for use in custom behavior packs. Their API signatures might change at any time." — **F4**

→ Una dependencia con sufijo `-internal` es, según F4, **no soportada** en packs personalizados: es el único caso
de sufijo que un analizador puede marcar como problema **con respaldo literal** de la documentación.

**Semántica de cumplimiento de versión en el canal estable (crítica para evitar falsos positivos):**

> "For example, if a script module has a dependency on version `1.3.0` of the `@minecraft/server` API, **it may actually have that dependency fulfilled with `1.8.0`** of the `@minecraft/server` - and those script modules should continue to function as expected. For those familiar with NPM semantic versioning, this is similar to the `^` signifier within version dependencies." — **F4**

→ **No se puede reportar como error** que la dependencia declare `1.3.0` y el motor tenga `1.8.0`: la doc dice
explícitamente que eso es correcto y esperado.

> "As you share or publish behavior packs that use stable APIs, please base your dependencies for APIs on **the latest and highest version number that is supported within Minecraft at the time of your release**." — **F4** (bloque `[!IMPORTANT]`)

---

## 5. `min_engine_version`: significado, formato y límites

### 5.1 Significado y formato (cita literal de F1)

> "This is the minimum version of the game that this pack was written for. **This is a required field for resource and behavior packs.** This helps the game identify whether any backwards compatibility is needed for your pack. **You should always use the highest version currently available when creating packs.**" — **F1**

- **Tipo:** `Vector [a, b, c] or SemVer String` — "In version 3, currently in preview, you must use a string for version." (**F1**)
- **Obligatoriedad:** explícitamente para **resource y behavior packs**. No para world templates ni skin packs (F1).
- **Propósito documentado:** identificar **si se necesita compatibilidad hacia atrás**. No se describe como un selector de API.

C4 lo describe en la lista de información del manifiesto:

> "**Minimum Engine Version**: Minimum required version of Minecraft for this pack to work properly." — **C4**

### 5.2 ¿La documentación advierte de que NO determina las APIs disponibles?

**Respuesta: NO de forma literal en F1–F5.** Esta es una comprobación deliberada y su resultado debe registrarse:

1. **F1** describe `min_engine_version` como "the minimum version of the game that this pack was written for" y
   como ayuda para "identify whether any backwards compatibility is needed". **No** contiene ninguna frase que diga
   que no determina las APIs disponibles.
2. **F4 no menciona `min_engine_version` en absoluto.** Verificado contra la fuente cruda del documento (**C2**):
   la cadena `min_engine_version` **no aparece** en el documento de versionado de módulos de scripting.

**Lo que SÍ está documentado, y es la evidencia más cercana** es el **desacoplamiento explícito** entre la
numeración de versiones de los módulos de scripting y la numeración del producto Minecraft:

> "Note that **this version number is not connected to the overall Minecraft version numbering scheme** (for example, `1.19.60`); rather, **these version numbers increment as changes occur to the API surface**." — **F4**

Y la tabla de correspondencia (parcial, hasta 1.21.60) que demuestra que la relación existe pero **no es 1:1 ni
derivable por fórmula**:

| `@minecraft/server` | Minecraft | | `@minecraft/server` | Minecraft |
| :--- | :--- | :--- | :--- | :--- |
| 1.0.0 | 1.19.70 | | 1.10.0 | 1.20.80 |
| 1.1.0 | 1.19.80 | | 1.11.0 | 1.21.0 |
| 1.2.0 | 1.20.0 | | 1.13.0 | 1.21.20 |
| 1.3.0 | 1.20.10 | | 1.14.0 | 1.21.30 |
| 1.4.0 | 1.20.20 | | 1.15.0 | 1.21.40 |
| 1.5.0 | 1.20.30 | | 1.16.0 | 1.21.50 |
| 1.6.0 | 1.20.40 | | 1.17.0 | 1.21.60 |
| 1.7.0 | 1.20.50 | | | |
| 1.8.0 | 1.20.60 | | | |
| 1.9.0 | 1.20.70 | | | |

*(Tabla reproducida íntegra de **F4**. Nótese que **falta `1.12.0`**: salta de 1.11.0 a 1.13.0 — es un hueco de la
propia tabla oficial, no un error de transcripción.)*

**Conclusión normativa honesta:**
- **NO DETERMINADO (literal):** ninguna de las fuentes obligatorias afirma con esas palabras que
  "`min_engine_version` no determina las APIs disponibles".
- **Derivación respaldada por dos citas:** F1 dice que `min_engine_version` sirve para decidir compatibilidad hacia
  atrás (no para seleccionar APIs), y F4 dice que la versión de los módulos de scripting "is not connected to the
  overall Minecraft version numbering scheme". Por tanto, **es incorrecto** que un analizador deduzca las APIs
  disponibles a partir de `min_engine_version`.
- **Qué falta para cerrarlo:** una frase oficial del tipo "min_engine_version does not control which APIs are
  available" en F1 o F4. No existe en las fuentes consultadas.

---

## 6. F2 — Carpetas de packs compartidos y de mundo en BDS

F2 describe las carpetas creadas en el primer arranque del servidor dedicado:

> "**worlds:** This is the folder where newly-created worlds will be installed. Worlds will be installed in subfolders of **worlds/** named by the value of the `level-name` property in **server.properties**. **While multiple worlds can be installed on the server, only one world is active at a time, set by the `level-name` property.**" — **F2**

> "**behavior_packs:** Behavior packs shared across all worlds on the server should be placed here." — **F2**

> "**resource_packs:** Resource packs shared across all worlds on the server should be placed here." — **F2**

### 6.1 La sección "Shared resource and behavior packs" (cita literal)

> "You might have noticed that there are **behavior_packs** and **resource_packs** folders both within the worlds in the **worlds/** folder _and_ at the top level where Bedrock Dedicated Server is installed. What's the difference?" — **F2**

> "- Packs installed in a folder for a world are **only available when that world is running on the server**.
> - Packs installed in the top level folders are available on **_any_ world being run on the server**." — **F2**

> "Unless a pack only makes sense in a specific world, you'll probably want to install your resource and behavior packs in the shared folders at the top level." — **F2**

### 6.2 Rutas concretas

| Ámbito | Ruta | Respaldo |
| :--- | :--- | :--- |
| Compartido (todo el servidor) | `<raíz BDS>/behavior_packs/` | F2: "**behavior_packs:** Behavior packs shared across all worlds on the server should be placed here." |
| Compartido (todo el servidor) | `<raíz BDS>/resource_packs/` | F2: "**resource_packs:** Resource packs shared across all worlds on the server should be placed here." |
| Por mundo | `worlds/<level-name>/behavior_packs/` | F2 dice literalmente que hay una carpeta **behavior_packs** "within the worlds in the **worlds/** folder" y que esos packs "are only available when that world is running". |
| Por mundo | `worlds/<level-name>/resource_packs/` | Ídem para **resource_packs**. |
| Mundo activo | `worlds/<level-name>/` donde `level-name` viene de `server.properties` | F2: "named by the value of the `level-name` property in **server.properties**" + "**This has to match exactly, including letter case.**" |

**Precisión sobre el nivel de literalidad:** F2 **no escribe** la ruta completa `worlds/<mundo>/behavior_packs`
como cadena. Escribe que las carpetas **behavior_packs** y **resource_packs** existen "both **within the worlds in
the worlds/ folder** _and_ at the top level". La ruta exacta se **confirma de forma independiente** en **F3-en**, que
documenta el contenido de un mundo exportado con addons:

> "- **behavior_packs** — All the behavior packs you activated in the world will be copied into here
> - **db**
> - **resource_packs** — 0.All the resource packs you activated in the world will be copied into here
> - **level.dat**
> - …
> - **world_behavior_packs.json** - Contains behavior pack ID and version
> - **world_resource_packs.json** - Contains resource pack ID and version" — **F3-en**

*(El "0." al inicio de la línea de `resource_packs` es un defecto de formato presente en la página oficial; se
transcribe tal cual para no alterar la cita.)*

→ Ruta por mundo **respaldada por F2 (cualitativo) + F3-en (listado explícito de carpetas dentro del mundo)**.

**Advertencia importante para el analizador:** F2 establece que **solo un mundo está activo a la vez**
(`level-name`). Por tanto, el inventario de packs **efectivos** en un momento dado combina:
`<raíz>/behavior_packs` + `<raíz>/resource_packs` + `worlds/<level-name>/behavior_packs` +
`worlds/<level-name>/resource_packs`. Los packs de **otros** mundos en `worlds/` **no** están activos.

---

## 7. F3 — `world_behavior_packs.json` y `world_resource_packs.json`

Aplicación del ámbito F2 en el analizador (inferencia de disponibilidad, no de
carga): una dependencia de un pack compartido puede encontrar un candidato local
del mundo que lo referencia. Se propaga ese contexto a dependencias transitivas
y se conservan resultados separados por mundo. La documentación no fija una
precedencia entre candidatos iguales, por lo que siguen siendo ambiguos.

### 7.1 Contexto de empaquetado (cita literal de F3)

> "Para empaquetar una plantilla de mundo, crea una carpeta `world_template` que contenga los archivos del mundo
> (una carpeta `db` con un archivo manifest.jason, `level.dat`, etc.), un `world_behavior_packs.json`,
> `world_resource_packs.json` y tu arte especial como el `world_icon.jpeg`." — **F3**

*(El texto oficial dice literalmente "manifest.jason" — errata de la documentación, transcrita sin corregir.)*

### 7.2 Estructura exacta

> "Si tu mundo requiere un pack de recursos o de comportamiento, **debes definirlos explícitamente aquí usando el `uuid` de los packs**. Ambos archivos JSON usan el mismo formato, pero debes asegurarte de ingresar el `uuid` en cada uno de los archivos." — **F3**

> "- **`pack_id`**: el uuid del recurso requerido o pack de comportamiento.
> - Asegúrate de que `world_resource_packs.json` solo contenga los packs de recursos necesarios y que `world_behavior_packs.json` solo contenga los packs de comportamiento necesarios.
> - **`version`**: la versión del pack de recursos o comportamiento, **definida en el `manifest.json` de los packs**." — **F3**

Plantilla literal de F3:

```json
[
    {
        "pack_id": "<UUID FROM REQUIRED PACK>",
        "version": [1, 0, 0]
    }
]
```

**Reglas verificables derivadas:**

| Regla | Respaldo |
| :--- | :--- |
| El archivo es un **array JSON** de objetos. | Plantilla de F3 (`[ { … } ]`). |
| Cada entrada tiene **exactamente** las claves `pack_id` y `version`. | Plantilla de F3. |
| `pack_id` = el **UUID** del pack requerido (es decir, el `header.uuid` del `manifest.json` de ese pack). | "`pack_id`: el uuid del recurso requerido o pack de comportamiento." (F3) |
| `version` = la versión **definida en el `manifest.json`** del pack referenciado. | "`version`: la versión del pack … definida en el `manifest.json` de los packs." (F3) |
| `world_behavior_packs.json` **solo** packs de comportamiento; `world_resource_packs.json` **solo** packs de recursos. | "Asegúrate de que `world_resource_packs.json` solo contenga los packs de recursos necesarios y que `world_behavior_packs.json` solo contenga los packs de comportamiento necesarios." (F3) |
| Ambos archivos comparten el mismo formato. | "Ambos archivos JSON usan el mismo formato" (F3) |

F3-en añade la descripción funcional:

> "**world_behavior_packs.json** - Contains behavior pack ID and version" / "**world_resource_packs.json** - Contains resource pack ID and version" — **F3-en**

### 7.3 Requisitos de plantilla publicable que NO deben imponerse a mundos existentes

Esta es la parte más importante de F3 para un analizador, porque **separa requisitos de plantilla de requisitos de mundo**.

**(a) Longitud del nombre de carpeta del pack ≤ 10 caracteres — requisito de PLANTILLA:**

> "Por último, los nombres de las carpetas del pack de recursos y del pack de comportamiento deben tener
> **10 caracteres o menos**. Esto se debe a un problema en Xbox en el que las rutas largas pueden provocar que tu
> pack de recursos o comportamiento no se cargue de manera correcta. Te recomendamos usar un acrónimo del título
> de tu contenido para los nombres de las carpetas de tu pack." — **F3**

F3-en lo confirma y **acota el alcance a world templates**:

> "**Resource pack and behavior pack folder names in world templates** must be **10 characters or shorter**. This is due to an issue on Xbox where long paths may cause resource or behavior packs to not load properly." — **F3-en**

→ **Conclusión:** el límite de 10 caracteres es una **condición de la plantilla de mundo** (por un problema de
rutas largas en Xbox). **NO debe reportarse como error en mundos existentes ni en packs del servidor**, porque la
documentación no lo establece para ellos. En un analizador, como máximo, **aviso informativo** y solo si el sujeto
analizado es una plantilla.

**(b) Otros requisitos que son de plantilla y no de mundo:**

| Requisito | Cita de F3 | Por qué no aplica a mundos existentes |
| :--- | :--- | :--- |
| `world_icon.jpeg` 800x450 JPEG | "**Dimensiones:** 800x450px / **Formato de archivo:** JPEG" | Es arte de presentación de la plantilla. F3: "Las plantillas que no pertenecen al mercado no necesitan un ícono de mundo". |
| `texts/en_US.lang` con `pack.name`/`pack.description` | "Debes tener estas dos líneas en tu archivo `.lang`" | Solo define el nombre/descripción mostrados al **crear** un mundo desde la plantilla. |
| `languages.json` | "Solo requerimos inglés." | Metadato de localización de plantilla. |
| `lock_template_options` | F1: "This option is required for any world templates." | Bloquea que el jugador modifique las opciones **del mundo creado desde la plantilla**. No es un campo de pack de comportamiento/recurso. |
| Nombre de carpeta `world_template` | "crea una carpeta `world_template` que contenga los archivos del mundo" | Es la **raíz** del paquete `.mctemplate`, no la estructura de un mundo en `worlds/`. |

**(c) Advertencia documentada sobre romper contenido al actualizar plantillas (contexto):**

> "Con el lanzamiento de la versión `1.18`, las plantillas creadas con la versión `1.17.4` o anterior del juego base
> se actualizarán con la herramienta de generación de mundos nuevos. Es posible que el contenido se rompa cuando se
> creen mapas nuevos en función de esa plantilla." — **F3**

Y el límite de ruta de Windows, relevante si el analizador recorre rutas profundas:

> "La ruta de archivo máxima permitida por defecto en Windows10 es de 260caracteres. Ten esto en cuenta cuando
> configures tu directorio de carpetas y usa convenciones de nomenclatura taquigráficas si estás cerca del límite de
> caracteres." — **F3**

---

## 8. F4 — Versión del juego vs. versión de API/módulo de scripting

### 8.1 Los tres canales (cita literal)

> "Minecraft API modules currently operate on three tracks:
> - a **stable track** (for example, version `1.1.0`)
> - a **beta track** (for example, version `1.3.0-beta`)
> - an **internal track** (for example, version `1.4.0-internal`)" — **F4**

### 8.2 Tabla comparativa: `min_engine_version` vs. versión de módulo de scripting

| Dimensión | `min_engine_version` | Versión del módulo de scripting |
| :--- | :--- | :--- |
| Dónde vive | `header.min_engine_version` del manifiesto | `dependencies[].version` con clave `module_name` |
| Qué versiona | "the minimum version of the game that this pack was written for" (F1) | "these version numbers increment as changes occur to the API surface" (F4) |
| Formato | "Vector `[a, b, c]` or SemVer String" (F1) | "`[major].[minor].[patch]` with an optional suffix" (F4) |
| Relación con la versión de Minecraft | **Es** una versión de Minecraft | "**is not connected to** the overall Minecraft version numbering scheme" (F4) |
| Canal | No aplica | stable / beta (`-beta`) / internal (`-internal`) |
| Compatibilidad hacia atrás | "This helps the game identify whether any backwards compatibility is needed for your pack." (F1) | stable: sí, semver. beta: "**no backwards compatibility is implied**" (F4) |
| Requisito extra | Ninguno documentado | beta exige el experimento "Beta APIs" (F4) |

### 8.3 Compatibilidad: reglas documentadas

**Estable (reglas semver, citas literales de F4):**

> "API modules in the stable track are numbered with a version number like `1.1.0`, and with no suffix on the end. These APIs are considered "finished" and should not change in functionality across releases where minor or patch versions are incremented." — **F4**

> "**Major version increments** (for example, `2.3.0` -> `3.0.0`) imply changes that break backwards-compatibility, potentially in both API signature and functionality. Across major versions, a method signature might not change but it may work differently and impact the gameplay of worlds. Note that Minecraft **may support multiple major versions of APIs in the future**, so if a behavior pack has a dependency on an older major version of the API, it may still continue to work even if a newer major version of the script API module is available." — **F4**

> "**Minor and patch version increments** could imply new functionality and API signature additions, but should be backwards-compatible within the same major version." — **F4**

**Beta (cita literal de F4, ya reproducida en §4.4):**
"Beta APIs do not follow the rules of semantic versioning. With beta APIs, no backwards compatibility is implied,
and even minor version increments can include backwards-compatibility breaking changes…"

**Interna:** "Internal APIs are not functional or supported for use in custom behavior packs."

**Sobre usar estables cuando sea posible:**

> "When specifying dependencies within `manifest.json` of a behavior pack, it is important to consider the impact of
> the versions of APIs that you wish to use. **Where possible, try to use stable track APIs.**" — **F4**

**Cobertura estable limitada (dato relevante para diagnosticar):**

> "As of version 1.19.70, **only `@minecraft/server` has APIs that are in the stable track.** … Note that **only a
> subset of the members of these types are currently exposed in the stable track**." — **F4**

### 8.4 ¿Una versión beta requiere un mundo/experimento?

**SÍ, y está documentado de forma imperativa (cita exacta, bloque `[!IMPORTANT]` de F4):**

> "**In order to use -beta APIs, you must enable the "Beta APIs" experiment within worlds that use these behavior packs.**" — **F4**

C7 lo refuerza para el caso V2:

> "**Scripting V2 APIs are currently in experimental preview and require the "Beta APIs" experiment to use.** They may undergo some changes before becoming stabilized and generally available." — **C7**

> "Custom Components V2 is a new experiment which **must be enabled along with the "Beta APIs" experiment** to use the new features for custom components." — **C7**

**Consecuencia dura para el analizador:** el requisito del experimento **no vive en el manifiesto del pack**, sino
en el **mundo** (estado de experimentos). Un analizador que solo lee metadatos de packs **puede detectar** que una
dependencia usa un módulo `-beta` (sufijo en la cadena de versión), pero **no puede verificar** desde el manifiesto
si el mundo tiene activado el experimento. Ese cruce requiere leer el mundo (`level.dat` / configuración de
experimentos), fuera del alcance de un inventario de packs.

### 8.5 ¿`min_engine_version` basta para deducir APIs?

**No, y ninguna fuente obligatoria lo dice con esas palabras.** Ver §5.2 para el análisis completo. Resumen:

- **F4 no menciona `min_engine_version`** (verificado contra fuente cruda C2).
- **F1** lo define como versión mínima del juego / indicador de compatibilidad hacia atrás, no como selector de API.
- **F4** desacopla explícitamente la numeración de módulos de la numeración del producto.
- Además, la tabla de correspondencia de F4 está **incompleta** (llega hasta `1.17.0` / Minecraft `1.21.60` y omite
  `1.12.0`), por lo que **ni siquiera con la tabla** se puede mapear de forma fiable una versión de Minecraft a una
  versión de `@minecraft/server`.

→ **NO DETERMINADO (literal)** + derivación respaldada. Ver §5.2 y §11.

---

## 9. F5 — Contenido real observado en `microsoft/minecraft-samples`

### 9.1 Metadatos del repositorio (API de GitHub, consultado 2026-10-06)

| Dato | Valor |
| :--- | :--- |
| Repositorio | `microsoft/minecraft-samples` |
| Descripción | "Contains custom add-on samples for Minecraft Bedrock Edition." |
| Rama por defecto | **`main`** |
| **Commit (HEAD de `main` en la consulta)** | **`5e04b6f719c316b0611f569af0cab7d6e9a2fb26`** |
| Fecha del commit | `2026-08-24T20:08:41Z` |
| Mensaje del commit | "Pin GitHub Actions to full-length commit SHAs (#147)" |
| Autor | Dan Fiedler (`danfiedler-msft`) |
| Verificación de firma | `verified: true` (`reason: "valid"`) |
| **Licencia** | **MIT License** — `license.key = "mit"`, `spdx_id = "MIT"` |
| Estrellas / forks | 433 / 248 |
| Último push | `2026-10-03T14:14:51Z` |

### 9.2 Licencia: confirmación leyendo el archivo `LICENSE`

Se leyó el archivo **`LICENSE`** del repositorio en el commit fijado
(`https://raw.githubusercontent.com/microsoft/minecraft-samples/main/LICENSE`, HTTP 200). **Contenido literal:**

```
    MIT License

    Copyright (c) Microsoft Corporation.

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE
```

**✅ Confirmado: el repositorio `microsoft/minecraft-samples` usa licencia MIT** (doble confirmación: archivo
`LICENSE` + campo `license` de la API de GitHub). Titular: **Microsoft Corporation**.

**Matiz relevante:** la licencia MIT es **del repositorio**. Los `manifest.json` de los ejemplos **no** incluyen
bloque `metadata` ni campo `metadata.license` (ver §9.3), por lo que la licencia **no es legible desde el propio
manifiesto**: hay que consultarla en el `LICENSE` del repositorio. Un analizador **no puede** deducir la licencia
de un pack a partir de su `manifest.json` cuando `metadata` está ausente.

### 9.3 `behavior_pack_sample/manifest.json` — JSON literal

- **Ruta en el repo:** `behavior_pack_sample/manifest.json`
- **Blob SHA:** `dd90d617eb0c63d8cec274a78395e12980cd5a69` (tamaño 426 bytes)
- **URL cruda (commit fijado):** `https://raw.githubusercontent.com/microsoft/minecraft-samples/5e04b6f719c316b0611f569af0cab7d6e9a2fb26/behavior_pack_sample/manifest.json`

```json
{
  "format_version": 2,
  "header": {
    "description": "My attack cow behavior pack Add-On!",
    "name": "My Behavior Pack",
    "uuid": "3958f9a2-96e4-4db0-a907-145d065cd7f0",
    "version": [1, 0, 0],
    "min_engine_version": [1, 16, 0]
  },
  "modules": [
    {
      "description": "My First Add-On!",
      "type": "data",
      "uuid": "1b85a99a-bfeb-481d-8a77-b5cda182e7d3",
      "version": [1, 0, 0]
    }
  ]
}
```

### 9.4 `resource_pack_sample/manifest.json` — JSON literal

- **Ruta en el repo:** `resource_pack_sample/manifest.json`
- **Blob SHA:** `770f49e8bf0287bba1b388e599c0681c83663b2c` (tamaño 459 bytes)
- **URL cruda (commit fijado):** `https://raw.githubusercontent.com/microsoft/minecraft-samples/5e04b6f719c316b0611f569af0cab7d6e9a2fb26/resource_pack_sample/manifest.json`

```json
{
    "format_version": 2,
    "header": {
      "description": "My dirt resource pack Add-On!",
      "name": "My Resource Pack",
      "uuid":"f792a765-6eec-47e1-baea-599424fec93d",
      "version": [1, 0, 0],
      "min_engine_version": [1, 16, 0]
     },
    "modules": [
      {
        "description": "My First Add-On!",
        "type": "resources",
        "uuid": "457f55a3-2573-4e3c-a5db-f7e64b3d43a5",
        "version": [1, 0, 0]
      }
    ]
   }
```

*(La indentación irregular de `resource_pack_sample` —incluido `"uuid":` sin espacio tras los dos puntos—
se reproduce literalmente tal como está en el repositorio.)*

### 9.5 Estructura de los ejemplos (listado de archivos verificado)

| Ejemplo | Contenido |
| :--- | :--- |
| `behavior_pack_sample/` | `README.md`, `entities/` (dir), `manifest.json`, `pack_icon.png` (29 058 bytes) |
| `resource_pack_sample/` | `README.md`, `manifest.json`, `pack_icon.png` (333 699 bytes), `textures/` (dir) |

### 9.6 Observaciones sobre los ejemplos (contraste con la norma de F1)

| Observación | Detalle | Implicación para el analizador |
| :--- | :--- | :--- |
| `format_version: 2` | Ambos usan `2`. | Coherente con F1 ("**2** for resource, behavior, and world templates"). |
| `header` completo | Ambos tienen `description`, `name`, `uuid`, `version`, `min_engine_version`. | Coincide con F1 (los 5 campos presentes, incluido el "required field" `name` y el "required field for resource and behavior packs" `min_engine_version`). |
| **Sin bloque `metadata`** | Ninguno de los dos tiene `metadata` (ni `authors`, ni `license`, ni `url`). | `metadata` es **opcional** en la práctica (F1 no lo marca como required). El analizador **no** debe exigirlo. |
| **Sin bloque `dependencies`** | Ninguno de los dos tiene `dependencies`. | `dependencies` es **opcional** en los ejemplos oficiales, aunque F1 lo describa como "definitions for any other packs that are required". No debe ser obligatorio. |
| `modules[].uuid` ≠ `header.uuid` | En ambos, los dos UUIDs son distintos y bien formados. | Cumple la regla de F1: "should be different from the pack's UUID". |
| Solo **un** módulo por pack | `data` (behavior) y `resources` (resource). | No hay ejemplo oficial de módulo `script` en estos samples → no se puede documentar `entry` desde F5. |
| `min_engine_version: [1, 16, 0]` | Ambos fijan 1.16.0, pero F1 dice "You should always use the highest version currently available when creating packs." | Los samples oficiales **no** siguen esa recomendación (son de 2022, `ms.date: 05/17/2022`). Un analizador **no** debe tratar una `min_engine_version` baja como error: F1 la formula como "should always", no como obligación verificable. |
| ✅ UUIDs **distintos** entre los dos samples | `3958f9a2…`/`1b85a99a…` (behavior) vs `f792a765…`/`457f55a3…` (resource) y vs los de F1 (`ee649bcf…`, `66c6e9a8…`, `743f6949…`). | Verificado: **no hay colisión** entre los UUID de ejemplo de F1 y los de los samples — buena noticia, porque una colisión entre un ejemplo de la doc y un sample real sería una trampa para el analizador. |

### 9.7 READMEs de los samples (contexto de instalación)

Ambos README declaran su origen y su uso, con `ms.date: 05/17/2022`:

> "This sample is the behavior pack used in the Behavior Pack Tutorial." — `behavior_pack_sample/README.md`

> "The behavior pack sample is a useful tool to check your work while completing the Behavior Pack Tutorial. Using it is as simple as adding it to your `development_behavior_pack` folder." — `behavior_pack_sample/README.md`

> "This sample is the resource pack used in the Intro to Resource Packs Tutorial." — `resource_pack_sample/README.md`

**Nota de relevancia:** los samples se instalan en `development_behavior_packs` / `development_resource_packs`
(carpetas de **desarrollo del cliente**, `com.mojang`), **no** en las carpetas de BDS documentadas en F2.
Es decir, F5 ilustra la **forma del manifiesto**, no la disposición de carpetas de un servidor dedicado.
No confundir `development_*_packs` (cliente) con `behavior_packs` / `resource_packs` (BDS, F2).

---

## 10. REGLAS DERIVADAS Y LÍMITES

**Cómo leer esta tabla.** Cada fila es una regla **candidata** para el analizador, con su fuente, una **cita corta
literal** y si es **comprobable con metadatos locales** (es decir, leyendo únicamente `manifest.json`,
`world_*_packs.json` y la disposición de carpetas, sin abrir el mundo ni consultar el motor).

**Leyenda de la última columna:**
`SÍ` = verificable solo con metadatos locales ·
`PARCIAL` = verificable solo si el pack referenciado también está presente en el conjunto escaneado ·
`NO` = requiere información que no está en los metadatos (estado del mundo, versión del motor, orden de carga, etc.)

### A. Manifiesto — propiedades generales

| # | Regla verificable | Fuente | Cita corta | ¿Comprobable con metadatos locales? |
| :--- | :--- | :--- | :--- | :--- |
| A1 | `format_version` debe ser `1` (skin packs) o `2` (resource, behavior, world templates) | F1 | "This may be 1 for skin packs or 2 for resource, behavior, and world templates." | **SÍ** — pero `3` es válido en preview; no rechazar. |
| A2 | Un behavior/resource pack debe usar `format_version: 2` | F1 | "…or 2 for resource, behavior, and world templates." | **SÍ** |
| A3 | Existe `format_version: 3` en preview (1.21.110+) con versiones como **string semver** | F1 | "Version 3 is a new update of the manifest currently in preview." | **SÍ** — aceptar `[a,b,c]` **y** string según versión. |
| A4 | El manifiesto debe ser JSON válido con `header` y `modules` | F1 | "The manifest file contains all the basic information about the pack that Minecraft needs to identify it." | **SÍ** |
| A5 | `metadata.generated_with`: nombres de herramienta `[a-zA-Z0-9_-]`, máx. 32 caracteres; versiones semver | F1 | "The tool names are strings that must be `[a-zA-Z0-9_-]` and 32 characters maximum." | **SÍ** |
| A6 | `metadata.product_type`, si existe, solo puede ser `"addon"` | F1 | "The only supported value is `"addon"`…" | **SÍ** |
| A7 | `header.pack_scope` ∈ {`world`, `global`, `any`}; ausente ⇒ `"any"` | F1 | "If not specified, this is interpreted as `"any"`." | **SÍ** |
| A8 | `capabilities` solo admite valores documentados | F1 | "chemistry / editorExtension / experimental_custom_ui / raytraced / pbr" | **SÍ** — como aviso, no error duro. |

### B. `header`

| # | Regla verificable | Fuente | Cita corta | ¿Comprobable con metadatos locales? |
| :--- | :--- | :--- | :--- | :--- |
| B1 | `header.name` es **obligatorio** | F1 | "This is the name of the pack as it appears within Minecraft. **This is a required field.**" | **SÍ** |
| B2 | `header.description` describe el pack; recomendado 1-2 líneas | F1 | "We recommend keeping it to 1-2 lines." | **SÍ** (presencia); la longitud es **recomendación**, no norma. |
| B3 | `header.uuid` con formato `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` hexadecimal | F1 | "where each x is a hexadecimal value (0-9 or a-f)" | **SÍ** — regex. Caja alta/baja **NO DETERMINADO**. |
| B4 | `header.uuid` identifica el pack de forma única frente a cualquier otro pack | F1 | "uniquely identifies this pack from any other pack" | **PARCIAL** — solo colisiones dentro del conjunto escaneado. |
| B5 | `header.version` con formato de 3 componentes `[major, minor, revision]` | F1 | "in the format `[majorVersion, minorVersion, revision]`" | **SÍ** |
| B6 | En la importación, versión **mayor** reemplaza; versión **igual o menor** se ignora | F1 | "The new pack will replace the old one if the version is higher, and ignored if it's the same or lower." | **NO** — es comportamiento en tiempo de importación; solo heurística comparando instalado vs. candidato. |
| B7 | `min_engine_version` es **obligatorio** en resource y behavior packs | F1 | "This is a required field for resource and behavior packs." | **SÍ** — pero **no** exigirlo en `world_template` ni skin packs. |
| B8 | `min_engine_version` en formato `[a, b, c]` (o string en v3) | F1 | "Vector `[a, b, c]` or SemVer String" | **SÍ** |
| B9 | `min_engine_version` describe la versión mínima del juego y la necesidad de compatibilidad hacia atrás | F1 | "This helps the game identify whether any backwards compatibility is needed for your pack." | **PARCIAL** — el valor se lee, pero **no** hay versión del motor con la que contrastarlo. |
| B10 | Debería usarse la versión más alta disponible al crear packs | F1 | "You should always use the highest version currently available when creating packs." | **PARCIAL** — "should"; **no** es error. Los samples oficiales usan `[1,16,0]`. |
| B11 | `min_engine_version` **no** permite deducir las APIs disponibles | **NO DETERMINADO** (derivado de F1 + F4) | F1: "…whether any backwards compatibility is needed…"; F4: "not connected to the overall Minecraft version numbering scheme" | **NO** — y **no debe inferirse**. Ver §5.2 y §11. |

### C. `modules`

| # | Regla verificable | Fuente | Cita corta | ¿Comprobable con metadatos locales? |
| :--- | :--- | :--- | :--- | :--- |
| C1 | `modules[].type` documentado ∈ {`resources`, `data`, `world_template`, `script`} | F1 | "Can be any of the following: `resources`, `data`, `world_template` or `script`." | **SÍ** — pero **solo como aviso**: el ejemplo de F1 usa `client_data`, no documentado. |
| C2 | Un behavior pack usa módulo `data`; un resource pack, `resources` | F1 + F5 | F1: "Behavior packs use the **data** type" (C5); F5: `"type": "data"` / `"type": "resources"` | **SÍ** |
| C3 | `modules[].uuid` debe ser **distinto** del `header.uuid` | F1 | "This should be different from the pack's UUID" | **SÍ** |
| C4 | Cada módulo debe tener un `uuid` **distinto** de los demás módulos | F1 | "and different for every module" | **SÍ** |
| C5 | `modules[].version` con el mismo formato de 3 componentes que `header.version` | F1 | "in the same format as the pack's version in the header" | **SÍ** |
| C6 | `modules[].description` es informativa, no visible al usuario | F1 | "This is not user-facing at the moment" | **SÍ** |
| C7 | `modules[].language` **solo** si `type == "script"`, y el único valor es `javascript` | F1 | "Only present if `type` is `script`. … The only supported value is `javascript`." | **SÍ** |
| C8 | `modules[].entry` (ruta del script de entrada) | **NO DETERMINADO** | No aparece en la tabla de `modules` de F1 (verificado en fuente cruda C1); ausente en F2–F5 | **NO** — no hay norma oficial que citar. Ver §11. |

### D. `dependencies`

| # | Regla verificable | Fuente | Cita corta | ¿Comprobable con metadatos locales? |
| :--- | :--- | :--- | :--- | :--- |
| D1 | Una dependencia de pack usa la clave `uuid` | F1 | "the unique identifier of the pack that this pack depends on" | **SÍ** |
| D2 | El `uuid` de la dependencia debe ser **exactamente** el `header.uuid` del pack dependido | F1 | "It needs to be the exact same UUID that the pack has defined in the header section of its manifest file." | **PARCIAL** — requiere que el pack dependido esté en el conjunto escaneado. |
| D3 | La `version` de una dependencia de pack **debería coincidir** con la versión del pack dependido | F1 | "**Should match** the version the other pack has in its manifest file." | **PARCIAL** — "Should"; reportar como **advertencia**, no error. |
| D4 | Una dependencia de módulo de scripting usa la clave `module_name` | F1 | "For dependencies on built-in scripting modules, contains the name of the module." | **SÍ** |
| D5 | Una dependencia con `module_name` puede llevar `version` como **string** semver | F1 | Ejemplo: `{ "module_name": "@minecraft/server", "version": "1.9.0" }` | **SÍ** — aceptar string **y** vector en el mismo array. |
| D6 | Una dependencia con sufijo `-beta` exige el experimento "Beta APIs" en el mundo | F4 | "you must enable the "Beta APIs" experiment within worlds that use these behavior packs" | **NO** — el estado del experimento vive en el mundo, no en el pack. Solo se detecta el sufijo. |
| D7 | Una dependencia de módulo `-beta` puede romperse en cada release mayor y requerir actualización manual | F4 | "you may need to update the version number of `manifest.json` dependencies at every major release if you are using `-beta` APIs" | **SÍ** — como **aviso de mantenimiento**, no como error. |
| D8 | Una dependencia con sufijo `-internal` **no está soportada** en packs personalizados | F4 | "Internal APIs are not functional or supported for use in custom behavior packs." | **SÍ** — este sí es un hallazgo sólido. |
| D9 | En canal estable, una dependencia `1.3.0` puede satisfacerse con `1.8.0` (semántica tipo `^`) | F4 | "it may actually have that dependency fulfilled with `1.8.0`" | **NO** — requiere conocer la versión del motor. **Prohibido** marcarlo como error. |
| D10 | Las dependencias de API estables deberían apuntar a la versión más alta soportada en el momento de publicar | F4 | "please base your dependencies for APIs on the latest and highest version number that is supported within Minecraft at the time of your release" | **PARCIAL** — recomendación ("please"), no error. |

### E. Carpetas de packs (BDS)

| # | Regla verificable | Fuente | Cita corta | ¿Comprobable con metadatos locales? |
| :--- | :--- | :--- | :--- | :--- |
| E1 | Los packs compartidos de comportamiento van en `<raíz>/behavior_packs/` | F2 | "**behavior_packs:** Behavior packs shared across all worlds on the server should be placed here." | **SÍ** |
| E2 | Los packs compartidos de recursos van en `<raíz>/resource_packs/` | F2 | "**resource_packs:** Resource packs shared across all worlds on the server should be placed here." | **SÍ** |
| E3 | Existen carpetas `behavior_packs` y `resource_packs` también **dentro de cada mundo** | F2 | "there are **behavior_packs** and **resource_packs** folders both within the worlds in the **worlds/** folder _and_ at the top level" | **SÍ** |
| E4 | Los packs por mundo solo están disponibles cuando ese mundo corre | F2 | "Packs installed in a folder for a world are only available when that world is running on the server." | **SÍ** — cruzando con `level-name`. |
| E5 | Los packs del nivel superior están disponibles en **cualquier** mundo | F2 | "Packs installed in the top level folders are available on _any_ world being run on the server." | **SÍ** |
| E6 | La ruta del mundo es `worlds/<level-name>/`, con `level-name` de `server.properties` (coincidencia **exacta**, incluida caja) | F2 | "Worlds will be installed in subfolders of **worlds/** named by the value of the `level-name` property" + "**This has to match exactly, including letter case.**" | **SÍ** |
| E7 | Solo **un** mundo está activo a la vez | F2 | "only one world is active at a time, set by the `level-name` property" | **SÍ** — define cuál es el inventario *efectivo*. |
| E8 | La disposición por mundo incluye `behavior_packs/`, `resource_packs/`, `world_behavior_packs.json`, `world_resource_packs.json` | F3-en | "- **behavior_packs** … - **resource_packs** … - **world_behavior_packs.json** - Contains behavior pack ID and version" | **SÍ** |
| E9 | El análisis de un mismo pack debe considerar ambas ubicaciones (raíz y mundo) | F2 | "What's the difference?" → "only available when that world is running" vs. "available on _any_ world" | **SÍ** — riesgo de reportar duplicados falsos si se mezclan ámbitos. |

### F. `world_behavior_packs.json` / `world_resource_packs.json`

| # | Regla verificable | Fuente | Cita corta | ¿Comprobable con metadatos locales? |
| :--- | :--- | :--- | :--- | :--- |
| F-1 | El archivo es un **array** de objetos con `pack_id` y `version` | F3 | `[ { "pack_id": "<UUID FROM REQUIRED PACK>", "version": [1, 0, 0] } ]` | **SÍ** |
| F-2 | `pack_id` es el **UUID** del pack requerido (el `header.uuid` de su manifiesto) | F3 | "`pack_id`: el uuid del recurso requerido o pack de comportamiento." | **SÍ** |
| F-3 | `version` es la versión **definida en el `manifest.json`** del pack referenciado | F3 | "`version`: la versión del pack … definida en el `manifest.json` de los packs." | **PARCIAL** — requiere el pack presente para contrastar. |
| F-4 | Cada archivo solo debe listar packs del tipo correspondiente | F3 | "Asegúrate de que `world_resource_packs.json` solo contenga los packs de recursos necesarios y que `world_behavior_packs.json` solo contenga los packs de comportamiento necesarios." | **PARCIAL** — cruzando `pack_id` con el `modules[].type` del pack. |
| F-5 | Ambos archivos comparten el mismo formato | F3 | "Ambos archivos JSON usan el mismo formato" | **SÍ** |
| F-6 | Nombres de carpeta de pack ≤ 10 caracteres | F3 / F3-en | F3-en: "**Resource pack and behavior pack folder names in world templates** must be **10 characters or shorter**." | **SÍ**, pero **solo como aviso y solo en plantillas**. **NO imponerlo a mundos existentes.** |
| F-7 | UUIDs duplicados ya cargados en `com.mojang` producen errores de importación | F3-en | "You will get **"Failed to import" errors** if you already have content with the same UUIDs loaded into your `com.mojang` folder." | **PARCIAL** — solo colisión dentro del conjunto escaneado. |
| F-8 | Requisitos de plantilla (`world_icon.jpeg` 800x450 JPEG, `texts/en_US.lang`, `languages.json`, `lock_template_options`) | F3 / F3-en / F1 | "**Dimensiones:** 800x450px / **Formato de archivo:** JPEG"; F1: "This option is required for any world templates." | **SÍ** — pero **exclusivamente** para plantillas. **No** exigirlos a mundos existentes. |

### G. Límites duros del análisis con metadatos locales (lo que NO se puede verificar)

| # | Cuestión | Por qué no es verificable | Fuente que lo implica |
| :--- | :--- | :--- | :--- |
| G1 | Si el mundo tiene activado el experimento **"Beta APIs"** | El estado del experimento vive en el **mundo**, no en el manifiesto del pack | F4: "you must enable the "Beta APIs" experiment **within worlds** that use these behavior packs" |
| G2 | Qué versión de `@minecraft/server` **tiene** el motor | No está en el pack; requiere interrogar al motor/servidor | F4: la relación módulo↔producto es una tabla externa, no derivable |
| G3 | Si una dependencia de API está realmente **satisfecha** | Depende de la versión del motor y de la semántica `^` | F4: "it may actually have that dependency fulfilled with `1.8.0`" |
| G4 | El **orden de apilamiento** (*pack stacking*) de resource packs | Depende de la configuración del mundo, no de los manifiestos | C4: "**Pack Stacking** is how content is loaded on top of Vanilla content, causing each object that has the same name in both packs to be overwritten by the _latest_ applied pack." |
| G5 | Si un pack **reemplazará** o será **ignorado** al importar | Es comportamiento de importación comparando contra lo ya instalado | F1: "The new pack will replace the old one if the version is higher, and ignored if it's the same or lower." |
| G6 | Si `min_engine_version` es **compatible** con el motor instalado | Requiere la versión del motor (no está en los metadatos del pack) | F1: "This helps the game identify whether any backwards compatibility is needed" |
| G7 | Qué APIs concretas expone una versión de módulo | Depende de las definiciones de tipos de npm, no del manifiesto | F4: "consider using the type definitions available through **npm**" |
| G8 | Efectos de `world_behavior_pack_history.json` / `world_resource_pack_history.json` | F3-en los lista ("Contains information about the behavior packs, such as UUIDs") pero **su esquema no se documenta en F1–F5** | **NO DETERMINADO** — ver §11 |

---

## 11. NO DETERMINADO — vacíos documentales y qué falta

Se listan **únicamente** los puntos en los que la documentación consultada **no** permite afirmar una regla.
No se rellenan por inferencia.

| # | Punto no determinado | Qué dice (o no dice) la doc | Qué falta exactamente |
| :--- | :--- | :--- | :--- |
| N1 | **`modules[].entry`** | F1 no lo lista en la tabla de `modules` (confirmado contra fuente cruda C1). El único módulo tipo script de la doc (`"type": "client_data"` en el ejemplo de F1) **no** tiene `entry`. F2–F5 tampoco lo mencionan. | Una fila `entry` en la referencia de `modules` de F1, o un ejemplo oficial completo de módulo `"type": "script"` con `entry` + `language`. |
| N2 | **Enum real de `modules[].type`** | F1 declara 4 tipos (`resources`, `data`, `world_template`, `script`) pero **su propio ejemplo usa `client_data`**, que no está en la lista. | Lista oficial completa de tipos, o confirmación de que `client_data` es un tipo válido no documentado. **Mientras tanto: aviso, no error.** |
| N3 | **Caja de los UUID** | F1 enumera "hexadecimal value (0-9 or a-f)" — solo minúsculas. No dice si las mayúsculas son válidas ni si la comparación es case-insensitive. | Frase explícita sobre normalización/caja de UUID. **Mientras tanto: normalizar a minúsculas antes de comparar.** |
| N4 | **`header.description` obligatoria** | F1 marca solo `name` como "required field". De `description` dice "This is a short description…" y "We recommend keeping it to 1-2 lines", sin "required". | Confirmación explícita de obligatoriedad de `description`. |
| N5 | **Operador de comparación de la versión de una dependencia de pack** | F1 dice "Should match the version the other pack has in its manifest file" — no define si es igualdad exacta, mínimo, o rango. | Frase que defina el operador (p. ej. `>=` o igualdad exacta). **Mientras tanto: "no coincide" ⇒ advertencia.** |
| N6 | **Colisión de UUID con versiones distintas** | F1 explica qué pasa con **mismo UUID y versión mayor/igual/menor** en la importación; F3-en explica el error de importación por **UUIDs ya cargados**. Ninguna fuente cubre el caso combinado "mismo UUID, versión distinta, ambos instalados en carpetas distintas". | Frase oficial sobre resolución de colisiones con UUID igual y versión distinta. |
| N7 | **`min_engine_version` no determina las APIs** | **Ninguna** de las cinco fuentes obligatorias contiene esa frase. F4 **no menciona** `min_engine_version` (verificado en fuente cruda C2). | Frase oficial explícita. La conclusión es **derivable** de F1 (compatibilidad hacia atrás) + F4 (desacoplamiento de numeraciones), pero no es una cita. |
| N8 | **Esquema de `world_*_pack_history.json`** | F3-en solo dice de ellos "Contains information about the behavior packs, such as UUIDs". No hay tabla de campos. | Esquema oficial (claves, tipos, si son editables a mano). |
| N9 | **`dependencies` con `uuid` que apunta a un pack ausente** | F1 define la dependencia como "any other packs that are required in order for this manifest.json file to work", pero no documenta el comportamiento cuando el pack dependido no está instalado, ni si hay un mecanismo de error/reporte. | Frase sobre dependencias no satisfechas. |
| N10 | **Obligatoriedad de `min_engine_version` en world templates** | F1 dice "required field for resource and behavior packs" — no menciona world templates. F3 propone una plantilla de manifiesto de plantilla de mundo **sin** `min_engine_version`. | Aclaración oficial. **Mientras tanto: no exigirlo en `world_template`.** |
| N11 | **Requisito del experimento "Beta APIs" y su detección** | F4 dice que el experimento debe activarse "within worlds"; no documenta cómo leer ese estado desde fuera. | Formato del estado de experimentos en el mundo (`level.dat`). |
| N12 | **`format_version: 3` y `settings`** | F1 los marca como **preview/experimental**: "subject to change or removal in future builds". Tabla de mapeo módulo↔producto en F4 **incompleta** (llega a 1.17.0 / 1.21.60 y omite 1.12.0). | Documentación estable de v3 y tabla de correspondencia completa. |

---

## 12. Síntesis para el implementador (resumen ejecutivo de límites)

1. **Cinco fuentes obligatorias, cinco respuestas OK.** Sin sustituciones forzadas. Se añadieron 7 fuentes
   complementarias para verificar y cerrar huecos; todas documentadas en §1.1.
2. **La referencia canónica del manifiesto es F1.** La URL "de ejemplo" (`examples/addonmanifest`) **redirige a F1**
   (C6): no existe una tabla de campos alternativa.
3. **La lista de tipos de módulo de F1 no es un enum fiable**: su propio ejemplo oficial usa un tipo que no
   documenta (`client_data`). → **Nunca fallar en duro por un `type` desconocido.**
4. **`entry` no está documentado en ninguna fuente consultada.** No inventar su formato ni su obligatoriedad.
5. **`version` y `min_engine_version` admiten dos tipos** (`[a,b,c]` **o** string semver, obligatorio en v3 preview).
   Validar solo vectores produce **falsos positivos**.
6. **La versión de una dependencia de pack "Should match"** (recomendación), mientras que su **UUID** "needs to be
   the exact same" (imperativo). Tratar la discrepancia de versión como **advertencia**.
7. **Semántica `^` en dependencias de API estables** (F4): declarar `1.3.0` y ser servido por `1.8.0` es
   **correcto**. Marcarlo como error sería un **falso positivo documentado**.
8. **`-beta` es un hallazgo sólido** (exige experimento "Beta APIs"; sin compatibilidad hacia atrás);
   **`-internal` es directamente no soportado**.
9. **El estado del experimento, la versión del motor y el orden de apilamiento NO están en los metadatos del pack.**
   Cualquier diagnóstico que dependa de ellos debe declararse como no verificable (§10-G), no adivinarse.
10. **Separar siempre el ámbito del pack**: `<raíz>/behavior_packs|resource_packs` (todo el servidor) frente a
    `worlds/<level-name>/behavior_packs|resource_packs` (solo ese mundo). Un inventario que mezcle ámbitos
    reportará duplicados inexistentes.
11. **Los requisitos de plantilla publicable (≤10 caracteres en el nombre de carpeta, `world_icon.jpeg`,
    `texts/`, `languages.json`, `lock_template_options`) NO son requisitos de mundo existente.** Imponerlos a
    mundos reales sería un error normativo.
12. **Sin sorpresas de colisión en los ejemplos oficiales:** los UUID de F1 y de los dos samples de F5 son todos
    distintos entre sí (verificado). El analizador puede usar los samples como *fixtures* válidos.

---

### Anexo — Inventario de citas por fuente

| Fuente | Nº de citas literales usadas en este informe |
| :--- | :--- |
| F1 (`packmanifest`) | 26 |
| F2 (`bedrockserver/getting-started`) | 9 |
| F3 (`packagingaworldtemplate`, es-mx) | 10 |
| F3-en (`createaworldtemplate`, equivalente inglés) | 5 |
| F4 (`scripting/versioning`) | 15 |
| F5 (`microsoft/minecraft-samples`) | 2 `manifest.json` literales + `LICENSE` + 2 READMEs + metadatos de API |
| C1 (fuente cruda de F1) | Verificación negativa: `entry` ausente |
| C2 (fuente cruda de F4) | Verificación negativa: `min_engine_version` ausente |
| C4 (`resourcepack`) | 3 |
| C5 (`behaviorpack`) | 1 |
| C7 (`v2-overview`) | 2 |

*Fin del informe.*
