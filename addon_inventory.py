# -*- coding: utf-8 -*-
"""addon_inventory.py — Inventario y diagnóstico de addons (SOLO LECTURA).

Analizador compartido por la CLI (``addon_inventory_cli.py``) y la GUI
(``gui_backend/services/addons.py`` + ``gui_backend/routers/addons.py``).
Este módulo NO importa FastAPI y NO escribe nada: solo abre archivos en modo
lectura. Es determinista (mismo árbol de instalación => mismo payload, sin
fechas ni duraciones) para que la equivalencia CLI/GUI sea comprobable byte a
byte.

ALCANCE DE ESTA FASE (inventario y diagnóstico, sin instalar ni activar nada)
---------------------------------------------------------------------------
* Behavior packs y resource packs en las ubicaciones documentadas:
  ``behavior_packs/``, ``resource_packs/`` (compartidos, F2),
  ``system_behavior_packs/``, ``system_resource_packs/`` (de sistema, how-to de
  BDS) y ``worlds/<nombre>/{behavior_packs,resource_packs}`` (propios de un
  mundo, F2/F3).
* Manifiestos ``manifest.json`` con ``format_version`` 2 (estable, F1). El
  formato 1 (skin packs) y el 3 (preview 1.21.110+) se reportan como NO
  ANALIZADOS con su motivo, nunca como corruptos (A1/A3/N12).
* ``world_behavior_packs.json`` y ``world_resource_packs.json`` de cada mundo
  (pack_id + version, F3).

Reglas, fuentes y límites: ``docs/INVESTIGACION_FUENTES_ADDONS.md`` (consulta
2026-10-06 a F1..F5) y la tabla de códigos de ``docs/INFORME_ADDONS.md``. Cada
diagnóstico declara su ``source`` (F1..F5, "BDS-howto") y si la consecuencia
está documentada (``determined``) o queda como no determinada.
"""

import json
import os
import re

import auto_backup  # reutiliza su deteccion de reparse points (no duplicar)
import server_properties

# Version del payload (contrato CLI/GUI).
SCHEMA_VERSION = 1

MANIFEST_NAME = "manifest.json"

# Tipos de pack y su carpeta en cada ambito (F2/E1..E3 + how-to de BDS).
KINDS = ("behavior", "resource")
DIR_COMPARTIDO = {"behavior": "behavior_packs", "resource": "resource_packs"}
DIR_SISTEMA = {"behavior": "system_behavior_packs", "resource": "system_resource_packs"}

# Archivo de referencias de packs dentro de un mundo (F3/F-1).
WORLD_REF_FILES = {
    "behavior": "world_behavior_packs.json",
    "resource": "world_resource_packs.json",
}

# Formatos de manifiesto que ESTA FASE analiza (declarado en el payload).
FORMATOS_SOPORTADOS = (2,)
FORMATOS_NO_ANALIZADOS = {
    1: "format_version 1 corresponde a skin packs (F1/A1); fuera del alcance de addons de mundo.",
    3: "format_version 3 esta en preview (F1/A3, N12); sus versiones son cadenas semver y el esquema puede cambiar.",
}

# Tipos de modulo documentados en F1 (C1). La lista NO es un enum fiable: el
# propio ejemplo de F1 usa "client_data"; un tipo desconocido es aviso, no error.
MODULE_TYPES_DOCUMENTADOS = ("resources", "data", "world_template", "script")

# Valores documentados de campos opcionales con lista cerrada.
CAPABILITIES_DOCUMENTADAS = (
    "chemistry", "editorExtension", "experimental_custom_ui", "raytraced", "pbr",
)
PACK_SCOPES_DOCUMENTADOS = ("world", "global", "any")
PRODUCT_TYPES_DOCUMENTADOS = ("addon",)

# Extensiones de representaciones empaquetadas que NO se analizan (se reportan
# como no analizadas con su motivo, nunca como corruptas).
EXTENSIONES_EMPAQUETADAS = (".mcpack", ".mcaddon", ".zip", ".mcworld", ".mctemplate")

SEVERIDADES = ("error", "aviso", "info")
_ORDEN_SEVERIDAD = {s: i for i, s in enumerate(SEVERIDADES)}

# ---------------------------------------------------------------------------
# CATALOGO DE DIAGNOSTICOS
# ---------------------------------------------------------------------------
# Clave estable -> metadatos de la regla. Campos:
#   severity    : "error" (incumple una regla documentada con consecuencia
#                 funcional), "aviso" (documentado pero sin consecuencia
#                 funcional demostrable, o evidencia parcial) e "info"
#                 (informativo / no determinado).
#   source      : fuente que respalda la comprobacion (F1..F5, "BDS-howto",
#                 "N#": punto no determinado del informe de investigacion).
#   partial     : True si el hallazgo implica inventario PARCIAL (algo que
#                 deberia poder analizarse no se pudo analizar).
#   determined  : False si la documentacion no fija la consecuencia/regla; el
#                 hecho se reporta pero el resultado queda "no determinado".
#   es/en       : mensaje con los mismos {placeholders} en ambos idiomas.
CATALOGO = {
    # -- Ubicaciones, seguridad de rutas y representaciones -----------------
    "SCOPE_ROOT_MISSING": {
        "severity": "info", "source": "F2", "partial": False, "determined": True,
        "es": "La ubicacion documentada {root} no existe en esta instalacion.",
        "en": "The documented location {root} does not exist in this installation.",
    },
    "SCOPE_ROOT_UNREADABLE": {
        "severity": "error", "source": "F2", "partial": True, "determined": True,
        "es": "No se pudo listar la ubicacion {root}: {motivo}. Los packs que pueda contener no se analizaron.",
        "en": "The location {root} could not be listed: {motivo}. Any packs it may contain were not analyzed.",
    },
    "SCOPE_ROOT_REPARSE": {
        "severity": "aviso", "source": "F2", "partial": True, "determined": True,
        "es": "La ubicacion {root} es un enlace/junction (reparse point): no se explora para no salir del ambito autorizado.",
        "en": "The location {root} is a link/junction (reparse point): it is not traversed so the authorized scope is not escaped.",
    },
    "SCOPE_ENTRY_REPARSE": {
        "severity": "aviso", "source": "F2", "partial": True, "determined": True,
        "es": "{ruta} es un enlace/junction (reparse point): no se sigue ni se analiza.",
        "en": "{ruta} is a link/junction (reparse point): it is not followed or analyzed.",
    },
    "SCOPE_ENTRY_OUTSIDE_ROOT": {
        "severity": "error", "source": "F2", "partial": True, "determined": True,
        "es": "{ruta} resuelve fuera de {root} (enlace o redireccion): no se analiza.",
        "en": "{ruta} resolves outside {root} (link or redirection): it is not analyzed.",
    },
    "SCOPE_ENTRY_UNREADABLE": {
        "severity": "error", "source": "F2", "partial": True, "determined": True,
        "es": "No se pudieron leer los datos de {ruta}: {motivo}.",
        "en": "Could not read metadata of {ruta}: {motivo}.",
    },
    "PACK_FOLDER_WITHOUT_MANIFEST": {
        "severity": "aviso", "source": "F1", "partial": True, "determined": True,
        "es": "La carpeta {ruta} esta en una ubicacion de packs pero no contiene {archivo}: no se puede analizar como pack.",
        "en": "Folder {ruta} sits in a pack location but has no {archivo}: it cannot be analyzed as a pack.",
    },
    "PACK_MANIFEST_NESTED": {
        "severity": "info", "source": "F1", "partial": False, "determined": False,
        "es": "En {ruta} hay un {archivo} mas profundo ({encontrado}): la ubicacion documentada es <carpeta-del-pack>/{archivo}; no se analiza.",
        "en": "{ruta} contains a deeper {archivo} ({encontrado}): the documented location is <pack folder>/{archivo}; it is not analyzed.",
    },
    "PACK_ARCHIVED_REPRESENTATION": {
        "severity": "info", "source": "F1", "partial": False, "determined": False,
        "es": "{ruta} es una representacion empaquetada ({extension}) que esta fase no abre: no se analiza (no se considera corrupta).",
        "en": "{ruta} is a packaged representation ({extension}) that this phase does not open: not analyzed (not considered corrupt).",
    },
    "MANIFEST_REPARSE": {
        "severity": "aviso", "source": "F1", "partial": True, "determined": True,
        "es": "{ruta} es un enlace/junction (reparse point): no se lee el manifiesto.",
        "en": "{ruta} is a link/junction (reparse point): the manifest is not read.",
    },
    "MANIFEST_UNREADABLE": {
        "severity": "error", "source": "F1", "partial": True, "determined": True,
        "es": "No se pudo leer el manifiesto {ruta}: {motivo}.",
        "en": "The manifest {ruta} could not be read: {motivo}.",
    },
    "MANIFEST_ENCODING_NOT_UTF8": {
        "severity": "aviso", "source": "F1", "partial": False, "determined": True,
        "es": "El manifiesto {ruta} no esta codificado en UTF-8: se leyo como latin-1 para poder analizarlo.",
        "en": "Manifest {ruta} is not UTF-8 encoded: it was read as latin-1 so it could be analyzed.",
    },
    "MANIFEST_JSON_INVALID": {
        "severity": "error", "source": "F1", "partial": True, "determined": True,
        "es": "El manifiesto {ruta} no es JSON valido: {motivo}.",
        "en": "Manifest {ruta} is not valid JSON: {motivo}.",
    },
    "MANIFEST_JSON_NOT_OBJECT": {
        "severity": "error", "source": "F1", "partial": True, "determined": True,
        "es": "El manifiesto {ruta} no es un objeto JSON sino {tipo}: no se puede leer header ni modules.",
        "en": "Manifest {ruta} is not a JSON object but {tipo}: header and modules cannot be read.",
    },
    "MANIFEST_JSON_TOLERANT": {
        "severity": "info", "source": "F1", "partial": False, "determined": True,
        "es": "El manifiesto {ruta} no es JSON estricto ({motivo}); se analizo en modo tolerante (los packs vanilla de Mojang se distribuyen asi).",
        "en": "Manifest {ruta} is not strict JSON ({motivo}); it was analyzed in tolerant mode (Mojang vanilla packs ship this way).",
    },
    "MANIFEST_FORMAT_VERSION_MISSING": {
        "severity": "error", "source": "F1", "partial": True, "determined": True,
        "es": "El manifiesto {ruta} no declara format_version: no se puede determinar el formato (F1/A1).",
        "en": "Manifest {ruta} does not declare format_version: the format cannot be determined (F1/A1).",
    },
    "MANIFEST_FORMAT_VERSION_INVALID": {
        "severity": "error", "source": "F1", "partial": True, "determined": True,
        "es": "format_version de {ruta} no es un numero: {valor}.",
        "en": "format_version of {ruta} is not a number: {valor}.",
    },
    "MANIFEST_FORMAT_VERSION_UNSUPPORTED": {
        "severity": "info", "source": "F1", "partial": False, "determined": False,
        "es": "format_version {valor} de {ruta} no se analiza en esta fase: {motivo}",
        "en": "format_version {valor} of {ruta} is not analyzed in this phase: {motivo}",
    },
    "MANIFEST_HEADER_MISSING": {
        "severity": "error", "source": "F1", "partial": True, "determined": True,
        "es": "El manifiesto {ruta} no tiene un objeto header: no se puede identificar el pack (F1/A4).",
        "en": "Manifest {ruta} has no header object: the pack cannot be identified (F1/A4).",
    },
    "MANIFEST_MODULES_MISSING": {
        "severity": "error", "source": "F1", "partial": True, "determined": True,
        "es": "El manifiesto {ruta} no tiene una lista modules con al menos un modulo (F1/A4).",
        "en": "Manifest {ruta} has no modules list with at least one module (F1/A4).",
    },
    # -- header ------------------------------------------------------------
    "PACK_NAME_MISSING": {
        "severity": "error", "source": "F1", "partial": False, "determined": True,
        "es": "Falta header.name en {ruta}: F1 lo marca como campo obligatorio (B1).",
        "en": "header.name is missing in {ruta}: F1 marks it as a required field (B1).",
    },
    "PACK_DESCRIPTION_MISSING": {
        "severity": "aviso", "source": "F1", "partial": False, "determined": True,
        "es": "Falta header.description en {ruta}: F1 lo recomienda (1-2 lineas) pero no lo marca obligatorio (B2, N4).",
        "en": "header.description is missing in {ruta}: F1 recommends it (1-2 lines) but does not mark it required (B2, N4).",
    },
    "PACK_UUID_MISSING": {
        "severity": "error", "source": "F1", "partial": False, "determined": True,
        "es": "Falta header.uuid en {ruta}: sin UUID el pack no se puede identificar ni referenciar desde un mundo (B4).",
        "en": "header.uuid is missing in {ruta}: without a UUID the pack cannot be identified or referenced from a world (B4).",
    },
    "PACK_UUID_INVALID": {
        "severity": "error", "source": "F1", "partial": False, "determined": True,
        "es": "header.uuid de {ruta} no tiene el formato hexadecimal documentado (8-4-4-4-12): {valor} (B3).",
        "en": "header.uuid of {ruta} is not in the documented hexadecimal form (8-4-4-4-12): {valor} (B3).",
    },
    "PACK_VERSION_MISSING": {
        "severity": "error", "source": "F1", "partial": False, "determined": True,
        "es": "Falta header.version en {ruta}: la version forma parte de la identidad que usan las referencias de mundo (B5, F-3).",
        "en": "header.version is missing in {ruta}: the version is part of the identity used by world references (B5, F-3).",
    },
    "PACK_VERSION_INVALID": {
        "severity": "error", "source": "F1", "partial": False, "determined": True,
        "es": "header.version de {ruta} no se puede interpretar como version: {valor} (B5).",
        "en": "header.version of {ruta} cannot be interpreted as a version: {valor} (B5).",
    },
    "PACK_VERSION_FORMAT_UNEXPECTED": {
        "severity": "aviso", "source": "F1", "partial": False, "determined": True,
        "es": "header.version de {ruta} no sigue el formato de 3 componentes [major, minor, revision] documentado: {valor} (B5).",
        "en": "header.version of {ruta} does not follow the documented 3-component format [major, minor, revision]: {valor} (B5).",
    },
    "MIN_ENGINE_VERSION_MISSING": {
        "severity": "aviso", "source": "F1", "partial": False, "determined": True,
        "es": "Falta header.min_engine_version en {ruta}: F1 lo marca obligatorio para packs de comportamiento y recursos; su ausencia no impide identificar el pack (B7).",
        "en": "header.min_engine_version is missing in {ruta}: F1 marks it required for behavior and resource packs; its absence does not prevent identifying the pack (B7).",
    },
    "MIN_ENGINE_VERSION_INVALID": {
        "severity": "error", "source": "F1", "partial": False, "determined": True,
        "es": "header.min_engine_version de {ruta} no se puede interpretar: {valor} (B8).",
        "en": "header.min_engine_version of {ruta} cannot be interpreted: {valor} (B8).",
    },
    "MIN_ENGINE_VERSION_FORMAT_UNEXPECTED": {
        "severity": "aviso", "source": "F1", "partial": False, "determined": True,
        "es": "header.min_engine_version de {ruta} no sigue el formato documentado [a, b, c]: {valor} (B8).",
        "en": "header.min_engine_version of {ruta} does not follow the documented format [a, b, c]: {valor} (B8).",
    },
    "PACK_SCOPE_INVALID": {
        "severity": "aviso", "source": "F1", "partial": False, "determined": True,
        "es": "header.pack_scope de {ruta} no es uno de los valores documentados (world, global, any): {valor} (A7).",
        "en": "header.pack_scope of {ruta} is not one of the documented values (world, global, any): {valor} (A7).",
    },
    "CAPABILITY_UNKNOWN": {
        "severity": "aviso", "source": "F1", "partial": False, "determined": True,
        "es": "capabilities de {ruta} declara un valor no documentado: {valor} (A8). Puede ser una capacidad nueva.",
        "en": "capabilities of {ruta} declares an undocumented value: {valor} (A8). It may be a newer capability.",
    },
    "PRODUCT_TYPE_INVALID": {
        "severity": "aviso", "source": "F1", "partial": False, "determined": True,
        "es": "metadata.product_type de {ruta} no es \"addon\", el unico valor documentado: {valor} (A6).",
        "en": "metadata.product_type of {ruta} is not \"addon\", the only documented value: {valor} (A6).",
    },
    "GENERATED_WITH_INVALID": {
        "severity": "aviso", "source": "F1", "partial": False, "determined": True,
        "es": "metadata.generated_with de {ruta} no cumple el formato documentado (herramientas [a-zA-Z0-9_-], maximo 32 caracteres): {valor} (A5).",
        "en": "metadata.generated_with of {ruta} does not match the documented format (tool names [a-zA-Z0-9_-], 32 characters maximum): {valor} (A5).",
    },
    # -- modules -----------------------------------------------------------
    "MODULE_NOT_OBJECT": {
        "severity": "error", "source": "F1", "partial": True, "determined": True,
        "es": "modules[{indice}] de {ruta} no es un objeto JSON: se ignora ese modulo (C1).",
        "en": "modules[{indice}] of {ruta} is not a JSON object: that module is ignored (C1).",
    },
    "MODULE_TYPE_MISSING": {
        "severity": "error", "source": "F1", "partial": True, "determined": True,
        "es": "modules[{indice}] de {ruta} no declara type: el modulo no se puede clasificar (C1).",
        "en": "modules[{indice}] of {ruta} does not declare type: the module cannot be classified (C1).",
    },
    "MODULE_TYPE_UNKNOWN": {
        "severity": "aviso", "source": "N2", "partial": False, "determined": False,
        "es": "modules[{indice}] de {ruta} usa type \"{valor}\", que no esta en la lista documentada (resources, data, world_template, script): no se valida (C1/N2).",
        "en": "modules[{indice}] of {ruta} uses type \"{valor}\", not in the documented list (resources, data, world_template, script): not validated (C1/N2).",
    },
    "MODULE_UUID_MISSING": {
        "severity": "error", "source": "F1", "partial": False, "determined": True,
        "es": "modules[{indice}] de {ruta} no declara uuid: cada modulo necesita un UUID propio (C4).",
        "en": "modules[{indice}] of {ruta} does not declare uuid: every module needs its own UUID (C4).",
    },
    "MODULE_UUID_INVALID": {
        "severity": "error", "source": "F1", "partial": False, "determined": True,
        "es": "modules[{indice}].uuid de {ruta} no tiene el formato hexadecimal documentado: {valor} (B3).",
        "en": "modules[{indice}].uuid of {ruta} is not in the documented hexadecimal form: {valor} (B3).",
    },
    "MODULE_UUID_EQUALS_HEADER": {
        "severity": "aviso", "source": "F1", "partial": False, "determined": True,
        "es": "modules[{indice}].uuid de {ruta} repite header.uuid: F1 pide que sea distinto (C3).",
        "en": "modules[{indice}].uuid of {ruta} repeats header.uuid: F1 requires it to be different (C3).",
    },
    "MODULE_UUID_DUPLICATE_IN_PACK": {
        "severity": "aviso", "source": "F1", "partial": False, "determined": True,
        "es": "modules[{indice}].uuid de {ruta} repite el UUID de otro modulo del mismo manifiesto: F1 pide un UUID distinto por modulo (C4).",
        "en": "modules[{indice}].uuid of {ruta} repeats the UUID of another module in the same manifest: F1 requires a different UUID per module (C4).",
    },
    "MODULE_UUID_DUPLICATE_IN_SCOPE": {
        "severity": "aviso", "source": "F1", "partial": False, "determined": False,
        "es": "El UUID de modulo {uuid} aparece tambien en {otros} del mismo ambito: contenido con UUIDs repetidos da errores de importacion (C4/F-7); no se determina cual carga BDS.",
        "en": "Module UUID {uuid} also appears in {otros} of the same scope: content with repeated UUIDs produces import errors (C4/F-7); which one BDS loads is not determined.",
    },
    "MODULE_VERSION_MISSING": {
        "severity": "aviso", "source": "F1", "partial": False, "determined": True,
        "es": "modules[{indice}] de {ruta} no declara version (formato documentado [major, minor, revision], C5).",
        "en": "modules[{indice}] of {ruta} does not declare version (documented format [major, minor, revision], C5).",
    },
    "MODULE_VERSION_INVALID": {
        "severity": "error", "source": "F1", "partial": False, "determined": True,
        "es": "modules[{indice}].version de {ruta} no se puede interpretar como version: {valor} (C5).",
        "en": "modules[{indice}].version of {ruta} cannot be interpreted as a version: {valor} (C5).",
    },
    "MODULE_VERSION_FORMAT_UNEXPECTED": {
        "severity": "aviso", "source": "F1", "partial": False, "determined": True,
        "es": "modules[{indice}].version de {ruta} no sigue el formato de 3 componentes documentado: {valor} (C5).",
        "en": "modules[{indice}].version of {ruta} does not follow the documented 3-component format: {valor} (C5).",
    },
    "MODULE_LANGUAGE_UNEXPECTED": {
        "severity": "aviso", "source": "F1", "partial": False, "determined": True,
        "es": "modules[{indice}] de {ruta} declara language={valor}: F1 solo admite language en modulos script y con el valor \"javascript\" (C7).",
        "en": "modules[{indice}] of {ruta} declares language={valor}: F1 only allows language on script modules and with the value \"javascript\" (C7).",
    },
    "MODULE_KIND_MISMATCH": {
        "severity": "aviso", "source": "F1", "partial": False, "determined": True,
        "es": "El pack {ruta} esta en una carpeta de {ubicacion} pero sus modulos son de tipo {tipos}: un pack de comportamiento usa data/script y uno de recursos usa resources (C2).",
        "en": "Pack {ruta} sits in a {ubicacion} folder but its modules are of type {tipos}: a behavior pack uses data/script and a resource pack uses resources (C2).",
    },
    # -- dependencies ------------------------------------------------------
    "DEPENDENCY_NOT_OBJECT": {
        "severity": "error", "source": "F1", "partial": True, "determined": True,
        "es": "dependencies[{indice}] de {ruta} no es un objeto JSON: se ignora esa dependencia (D1/D4).",
        "en": "dependencies[{indice}] of {ruta} is not a JSON object: that dependency is ignored (D1/D4).",
    },
    "DEPENDENCY_WITHOUT_KEY": {
        "severity": "error", "source": "F1", "partial": True, "determined": True,
        "es": "dependencies[{indice}] de {ruta} no declara ni uuid (pack) ni module_name (modulo de scripting): no se puede interpretar (D1/D4).",
        "en": "dependencies[{indice}] of {ruta} declares neither uuid (pack) nor module_name (scripting module): it cannot be interpreted (D1/D4).",
    },
    "DEPENDENCY_PACK_UUID_INVALID": {
        "severity": "error", "source": "F1", "partial": False, "determined": True,
        "es": "dependencies[{indice}].uuid de {ruta} no tiene el formato hexadecimal documentado: {valor} (D2).",
        "en": "dependencies[{indice}].uuid of {ruta} is not in the documented hexadecimal form: {valor} (D2).",
    },
    "DEPENDENCY_PACK_VERSION_MISSING": {
        "severity": "info", "source": "F1", "partial": False, "determined": False,
        "es": "dependencies[{indice}] de {ruta} no declara version: F1 recomienda que coincida con la del pack dependido, asi que no se puede comprobar (D3/N5).",
        "en": "dependencies[{indice}] of {ruta} does not declare a version: F1 recommends it match the depended pack's, so it cannot be checked (D3/N5).",
    },
    "DEPENDENCY_PACK_VERSION_INVALID": {
        "severity": "error", "source": "F1", "partial": False, "determined": True,
        "es": "dependencies[{indice}].version de {ruta} no se puede interpretar como version: {valor} (D3).",
        "en": "dependencies[{indice}].version of {ruta} cannot be interpreted as a version: {valor} (D3).",
    },
    "DEPENDENCY_PACK_MISSING": {
        "severity": "error", "source": "F1", "partial": False, "determined": False,
        "es": "El pack {ruta} depende de {uuid}, que no existe en su ambito ({ambito}): la dependencia queda sin satisfacer (F1/N9).",
        "en": "Pack {ruta} depends on {uuid}, which does not exist in its scope ({ambito}): the dependency is unsatisfied (F1/N9).",
    },
    "DEPENDENCY_PACK_AMBIGUOUS": {
        "severity": "aviso", "source": "F1", "partial": False, "determined": False,
        "es": "El pack {ruta} depende de {uuid} y hay varios candidatos en su ambito ({candidatos}): la documentacion no define precedencia (F1/N6).",
        "en": "Pack {ruta} depends on {uuid} and several candidates exist in its scope ({candidatos}): the documentation defines no precedence (F1/N6).",
    },
    "DEPENDENCY_PACK_VERSION_MISMATCH": {
        "severity": "aviso", "source": "F1", "partial": False, "determined": False,
        "es": "El pack {ruta} depende de {uuid} version {version} y el candidato instalado es {instalada}: F1 dice que la version \"should match\" (recomendacion) y no define el operador (D3/N5).",
        "en": "Pack {ruta} depends on {uuid} version {version} and the installed candidate is {instalada}: F1 says the version \"should match\" (recommendation) and defines no operator (D3/N5).",
    },
    "DEPENDENCY_PACK_OTHER_KIND": {
        "severity": "info", "source": "F1", "partial": False, "determined": False,
        "es": "El pack {ruta} ({tipo}) depende de {uuid}, que solo existe como {otro}: F1 no restringe el tipo del pack dependido; no se determina si BDS lo resuelve (D2).",
        "en": "Pack {ruta} ({tipo}) depends on {uuid}, which only exists as {otro}: F1 does not restrict the depended pack's type; whether BDS resolves it is not determined (D2).",
    },
    # -- modulos de scripting ---------------------------------------------
    "SCRIPT_DEP_MODULE_NAME_INVALID": {
        "severity": "aviso", "source": "F1", "partial": False, "determined": True,
        "es": "dependencies[{indice}].module_name de {ruta} no parece un modulo integrado (se espera un nombre con prefijo @, como @minecraft/server): {valor} (D4).",
        "en": "dependencies[{indice}].module_name of {ruta} does not look like a built-in module (a name prefixed with @ is expected, such as @minecraft/server): {valor} (D4).",
    },
    "SCRIPT_DEP_VERSION_MISSING": {
        "severity": "aviso", "source": "F4", "partial": False, "determined": True,
        "es": "dependencies[{indice}] de {ruta} depende de {valor} sin version: F4 pide basar las dependencias de API en la version mas alta soportada (D10).",
        "en": "dependencies[{indice}] of {ruta} depends on {valor} without a version: F4 asks to base API dependencies on the highest supported version (D10).",
    },
    "SCRIPT_DEP_VERSION_INVALID": {
        "severity": "error", "source": "F4", "partial": False, "determined": True,
        "es": "dependencies[{indice}] de {ruta} declara la version \"{valor}\" de {modulo}, que no es semver ni \"beta\" (D5).",
        "en": "dependencies[{indice}] of {ruta} declares version \"{valor}\" of {modulo}, which is neither semver nor \"beta\" (D5).",
    },
    "SCRIPT_DEP_BETA": {
        "severity": "aviso", "source": "F4", "partial": False, "determined": False,
        "es": "El pack {ruta} depende de {modulo} {version} (beta): F4 exige el experimento \"Beta APIs\" EN EL MUNDO y las APIs beta pueden romperse en cada release mayor; el estado del experimento no esta en los metadatos (D6/D7/G1).",
        "en": "Pack {ruta} depends on {modulo} {version} (beta): F4 requires the \"Beta APIs\" experiment IN THE WORLD and beta APIs may break on every major release; the experiment state is not in the metadata (D6/D7/G1).",
    },
    "SCRIPT_DEP_INTERNAL": {
        "severity": "error", "source": "F4", "partial": False, "determined": True,
        "es": "El pack {ruta} depende de {modulo} {version} (internal): F4 dice que las APIs internas no son funcionales ni soportadas en packs personalizados (D8).",
        "en": "Pack {ruta} depends on {modulo} {version} (internal): F4 says internal APIs are not functional or supported in custom behavior packs (D8).",
    },
    # -- identidad y duplicados -------------------------------------------
    "PACK_UUID_DUPLICATE": {
        "severity": "error", "source": "F1", "partial": False, "determined": True,
        "es": "El UUID {uuid} version {version} esta declarado por dos packs del mismo ambito ({ambito}): {otros}. F1 pide que identifique al pack de forma unica y UUIDs repetidos dan errores de importacion (B4/F-7).",
        "en": "UUID {uuid} version {version} is declared by two packs in the same scope ({ambito}): {otros}. F1 requires it to uniquely identify the pack and repeated UUIDs produce import errors (B4/F-7).",
    },
    "PACK_UUID_MULTIPLE_VERSIONS": {
        "severity": "info", "source": "N6", "partial": False, "determined": False,
        "es": "El UUID {uuid} aparece en {cuantos} packs del ambito {ambito} con versiones distintas ({versiones}): es el patron de los packs vanilla versionados de BDS; la documentacion no cubre esta colision (B6/N6).",
        "en": "UUID {uuid} appears in {cuantos} packs of scope {ambito} with different versions ({versiones}): this is the pattern of BDS versioned vanilla packs; the documentation does not cover this collision (B6/N6).",
    },
    "PACK_UUID_IN_OTHER_SCOPES": {
        "severity": "info", "source": "F2", "partial": False, "determined": False,
        "es": "El UUID {uuid} aparece tambien en otro ambito ({ambitos}): el mismo UUID en ambitos distintos no demuestra por si solo un conflicto (F2/E9, N6).",
        "en": "UUID {uuid} also appears in another scope ({ambitos}): the same UUID in different scopes does not by itself prove a conflict (F2/E9, N6).",
    },
    "SYSTEM_PACK_UUID_PROTECTED": {
        "severity": "error", "source": "BDS-howto", "partial": False, "determined": True,
        "es": "El pack de usuario {ruta} usa el UUID {uuid}, reservado por un pack de sistema ({sistema}): el how-to de BDS avisa de que los packs de usuario fallan al cargar si repiten el ID de un pack de sistema.",
        "en": "User pack {ruta} uses UUID {uuid}, reserved by a system pack ({sistema}): the BDS how-to warns that user packs fail to load when they reuse a system pack ID.",
    },
    # -- mundos y referencias ---------------------------------------------
    "WORLD_ENTRY_REPARSE": {
        "severity": "aviso", "source": "F2", "partial": True, "determined": True,
        "es": "{ruta} es un enlace/junction (reparse point) dentro de worlds/: no se analiza como mundo.",
        "en": "{ruta} is a link/junction (reparse point) inside worlds/: it is not analyzed as a world.",
    },
    "WORLD_WITHOUT_LEVEL_DAT": {
        "severity": "aviso", "source": "F2", "partial": True, "determined": True,
        "es": "La carpeta {ruta} esta en worlds/ pero no tiene level.dat: no parece un mundo valido (F2/E6).",
        "en": "Folder {ruta} is inside worlds/ but has no level.dat: it does not look like a valid world (F2/E6).",
    },
    "WORLD_REFS_UNREADABLE": {
        "severity": "error", "source": "F3", "partial": True, "determined": True,
        "es": "No se pudo leer {ruta}: {motivo}. Los packs referenciados por el mundo {mundo} no se pudieron relacionar.",
        "en": "Could not read {ruta}: {motivo}. The packs referenced by world {mundo} could not be matched.",
    },
    "WORLD_REFS_REPARSE": {
        "severity": "aviso", "source": "F3", "partial": True, "determined": True,
        "es": "{ruta} es un enlace/junction (reparse point): no se lee.",
        "en": "{ruta} is a link/junction (reparse point): it is not read.",
    },
    "WORLD_REFS_JSON_INVALID": {
        "severity": "error", "source": "F3", "partial": True, "determined": True,
        "es": "{ruta} no es JSON valido: {motivo}.",
        "en": "{ruta} is not valid JSON: {motivo}.",
    },
    "WORLD_REFS_NOT_ARRAY": {
        "severity": "error", "source": "F3", "partial": True, "determined": True,
        "es": "{ruta} no es una lista JSON sino {tipo}: F3 documenta un array de objetos con pack_id y version (F-1).",
        "en": "{ruta} is not a JSON array but {tipo}: F3 documents an array of objects with pack_id and version (F-1).",
    },
    "WORLD_REFS_ENTRY_INVALID": {
        "severity": "error", "source": "F3", "partial": True, "determined": True,
        "es": "{ruta}[{indice}] no es un objeto JSON con pack_id y version: se ignora esa referencia (F-1).",
        "en": "{ruta}[{indice}] is not a JSON object with pack_id and version: that reference is ignored (F-1).",
    },
    "WORLD_REF_PACK_ID_MISSING": {
        "severity": "error", "source": "F3", "partial": True, "determined": True,
        "es": "{ruta}[{indice}] no declara pack_id: la referencia no se puede relacionar con ningun pack (F-2).",
        "en": "{ruta}[{indice}] does not declare pack_id: the reference cannot be matched to any pack (F-2).",
    },
    "WORLD_REF_PACK_ID_INVALID": {
        "severity": "error", "source": "F3", "partial": True, "determined": True,
        "es": "{ruta}[{indice}].pack_id no tiene el formato hexadecimal documentado: {valor} (F-2/B3).",
        "en": "{ruta}[{indice}].pack_id is not in the documented hexadecimal form: {valor} (F-2/B3).",
    },
    "WORLD_REF_VERSION_MISSING": {
        "severity": "aviso", "source": "F3", "partial": True, "determined": False,
        "es": "{ruta}[{indice}] declara pack_id {valor} sin version: F3 documenta la version definida en el manifiesto del pack, asi que la referencia queda sin contrastar (F-3).",
        "en": "{ruta}[{indice}] declares pack_id {valor} without a version: F3 documents the version defined in the pack manifest, so the reference cannot be checked (F-3).",
    },
    "WORLD_REF_VERSION_INVALID": {
        "severity": "error", "source": "F3", "partial": True, "determined": True,
        "es": "{ruta}[{indice}].version no se puede interpretar como version: {valor} (F-3).",
        "en": "{ruta}[{indice}].version cannot be interpreted as a version: {valor} (F-3).",
    },
    "WORLD_REF_VERSION_FORMAT_UNEXPECTED": {
        "severity": "aviso", "source": "F3", "partial": False, "determined": True,
        "es": "{ruta}[{indice}].version no sigue el formato de 3 componentes documentado: {valor} (F-3/B5).",
        "en": "{ruta}[{indice}].version does not follow the documented 3-component format: {valor} (F-3/B5).",
    },
    "WORLD_REF_UNRESOLVED": {
        "severity": "error", "source": "F3", "partial": False, "determined": True,
        "es": "El mundo {mundo} referencia {uuid} version {version} y no hay ningun pack con ese UUID en su ambito ({ambito}){extra} (F2/F-2).",
        "en": "World {mundo} references {uuid} version {version} and no pack with that UUID exists in its scope ({ambito}){extra} (F2/F-2).",
    },
    "WORLD_REF_AMBIGUOUS": {
        "severity": "aviso", "source": "F3", "partial": False, "determined": False,
        "es": "El mundo {mundo} referencia {uuid} version {version} y hay {cuantos} candidatos con esa misma identidad en su ambito ({ambito}): {candidatos}. La documentacion no define precedencia (N6).",
        "en": "World {mundo} references {uuid} version {version} and {cuantos} candidates share that identity in its scope ({ambito}): {candidatos}. The documentation defines no precedence (N6).",
    },
    "WORLD_REF_VERSION_UNAVAILABLE": {
        "severity": "aviso", "source": "F3", "partial": False, "determined": False,
        "es": "El mundo {mundo} referencia {uuid} version {version}, pero en su ambito ({ambito}) solo estan instaladas las versiones {versiones}: F3 documenta la version del manifiesto y no define sustitucion (F-3/N5).",
        "en": "World {mundo} references {uuid} version {version}, but its scope ({ambito}) only has versions {versiones} installed: F3 documents the manifest version and defines no substitution (F-3/N5).",
    },
    "WORLD_REF_KIND_MISMATCH": {
        "severity": "aviso", "source": "F3", "partial": False, "determined": True,
        "es": "El mundo {mundo} referencia {uuid} en {archivo}, pero el pack resuelto ({pack}) es de tipo {tipo}: cada archivo deberia listar solo packs de su tipo (F-4).",
        "en": "World {mundo} references {uuid} in {archivo}, but the resolved pack ({pack}) is of type {tipo}: each file should list only packs of its own type (F-4).",
    },
    # -- incidencias puntuales del analisis --------------------------------
    "BASE_DIR_MISSING": {
        "severity": "error", "source": "F2", "partial": True, "determined": True,
        "es": "La instalacion indicada no existe o no es una carpeta: {ruta}.",
        "en": "The given installation does not exist or is not a folder: {ruta}.",
    },
    "SERVER_PROPERTIES_REPARSE": {
        "severity": "info", "source": "F2", "partial": False, "determined": True,
        "es": "{ruta} es un enlace/junction: no se lee para determinar el mundo activo (level-name).",
        "en": "{ruta} is a link/junction: it is not read to determine the active world (level-name).",
    },
    "ITEM_ANALYSIS_ERROR": {
        "severity": "error", "source": "F2", "partial": True, "determined": True,
        "es": "Error inesperado al analizar {ruta}: {motivo}. El resto del inventario se presenta igualmente.",
        "en": "Unexpected error while analyzing {ruta}: {motivo}. The rest of the inventory is still reported.",
    },
}


# ---------------------------------------------------------------------------
# Utilidades puras
# ---------------------------------------------------------------------------

_RE_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
# Semver con prerelease opcional: "1.9.0", "2.9.0-beta", "1.0.0-rc.1".
_RE_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$")
# SemVer 2.0 para las herramientas de metadata.generated_with (F1/A5).
_RE_TOOL_SEMVER = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)
# Cadena de version laxa (min_engine_version como texto, formato v3): "1.21.110".
_RE_VER_TEXTO = re.compile(r"^\d+(?:\.\d+){0,3}$")


def uuid_valido(valor):
    return isinstance(valor, str) and bool(_RE_UUID.match(valor.strip()))


def normalizar_uuid(valor):
    """Normaliza a minusculas (F1 solo enumera hex en minusculas; N3 no define
    la caja, asi que se compara siempre normalizado)."""
    return valor.strip().lower() if isinstance(valor, str) else valor


def clasificar_version(valor):
    """Clasifica un campo de version de manifiesto o de referencia de mundo.

    Devuelve (estado, componentes) con estado en:
      "ok"        -> vector de 3 enteros >= 0, como documenta F1 (B5)
      "formato"   -> interpretable pero no son 3 componentes (aviso, no error)
      "texto"     -> cadena semver (F1/A3 la admite en format_version 3 y en
                     min_engine_version; en un manifiesto v2 es inesperada)
      "invalido"  -> no se puede interpretar como version
    """
    if isinstance(valor, bool):
        return "invalido", None
    if isinstance(valor, list):
        if not valor or not all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in valor):
            return "invalido", None
        if len(valor) == 3:
            return "ok", tuple(valor)
        if len(valor) < 3:
            return "formato", tuple(valor) + (0,) * (3 - len(valor))
        return "formato", tuple(valor[:3])
    if isinstance(valor, str):
        texto = valor.strip()
        if _RE_SEMVER.match(texto) or _RE_VER_TEXTO.match(texto):
            return "texto", _tupla_desde_texto(texto)
        return "invalido", None
    return "invalido", None


def _tupla_desde_texto(texto):
    base = texto.split("-", 1)[0]
    partes = [int(p) for p in base.split(".") if p.isdigit()]
    while len(partes) < 3:
        partes.append(0)
    return tuple(partes[:3])


def version_comparable(valor):
    """Tupla de 3 enteros para comparar, o None si no es comparable."""
    estado, comps = clasificar_version(valor)
    return comps if estado in ("ok", "formato", "texto") else None


def texto_version(valor):
    """Representacion corta y estable de un campo de version para mensajes."""
    if isinstance(valor, list):
        return "[" + ", ".join(str(x) for x in valor) + "]"
    if isinstance(valor, str):
        return valor if valor.strip() else json.dumps(valor)
    return json.dumps(valor, ensure_ascii=False, sort_keys=True)


def _tipo_json(valor):
    if valor is None:
        return "null"
    if isinstance(valor, bool):
        return "booleano"
    if isinstance(valor, dict):
        return "objeto"
    if isinstance(valor, list):
        return "lista"
    if isinstance(valor, str):
        return "texto"
    return "numero"


def leer_texto(ruta):
    """Lee un archivo de texto devolviendo (texto, diagnostico_extra).

    UTF-8 (con BOM) primero; latin-1 como respaldo para no perder el analisis
    por un editor de Windows. Devuelve el texto y el sufijo de motivo con el
    que reportar la codificacion.
    """
    with open(ruta, "rb") as f:
        crudo = f.read()
    try:
        return crudo.decode("utf-8-sig"), None
    except UnicodeDecodeError:
        return crudo.decode("latin-1"), "no_utf8"


def _quitar_comentarios(texto):
    """Elimina comentarios // y /* */ y comas finales FUERA de las cadenas.

    Los manifiestos oficiales de Mojang incluyen comentarios (p. ej.
    behavior_packs/chemistry/manifest.json), asi que el analisis estricto
    daria un falso positivo sobre los propios packs del servidor.
    """
    salida = []
    i = 0
    n = len(texto)
    en_cadena = False
    while i < n:
        c = texto[i]
        if en_cadena:
            salida.append(c)
            if c == "\\" and i + 1 < n:
                salida.append(texto[i + 1])
                i += 2
                continue
            if c == '"':
                en_cadena = False
            i += 1
            continue
        if c == '"':
            en_cadena = True
            salida.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and texto[i + 1] == "/":
            while i < n and texto[i] not in "\r\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and texto[i + 1] == "*":
            # El comentario separa tokens: 1/* ... */2 no debe convertirse en 12.
            salida.append(" ")
            i += 2
            while i + 1 < n and not (texto[i] == "*" and texto[i + 1] == "/"):
                i += 1
            if i + 1 >= n:
                raise ValueError("comentario de bloque sin cerrar")
            i += 2
            continue
        salida.append(c)
        i += 1
    limpio = "".join(salida)
    # Segunda pasada con estado de cadena: nunca borrar comas de nombres,
    # descripciones ni claves JSON, incluso si contienen una llave/corchete.
    salida = []
    i = 0
    en_cadena = False
    while i < len(limpio):
        c = limpio[i]
        if en_cadena:
            salida.append(c)
            if c == "\\" and i + 1 < len(limpio):
                salida.append(limpio[i + 1])
                i += 2
                continue
            if c == '"':
                en_cadena = False
        elif c == '"':
            en_cadena = True
            salida.append(c)
        elif c == ",":
            siguiente = i + 1
            while siguiente < len(limpio) and limpio[siguiente] in " \t\r\n":
                siguiente += 1
            if siguiente >= len(limpio) or limpio[siguiente] not in "}]":
                salida.append(c)
        else:
            salida.append(c)
        i += 1
    return "".join(salida)


def cargar_json(texto):
    """JSON estricto y, si falla, tolerante (comentarios y comas finales).

    Devuelve (objeto, motivo_tolerancia, error) donde motivo_tolerancia es
    None si el JSON era estricto.
    """
    try:
        return json.loads(texto), None, None
    except ValueError as exc_estricto:
        try:
            return json.loads(_quitar_comentarios(texto)), "comentarios o comas finales", None
        except ValueError:
            return None, None, str(exc_estricto)


def _es_reparse(ruta):
    """Reutiliza la deteccion de reparse points del pipeline de backups."""
    return auto_backup._es_punto_reparse(ruta)


def _dentro_de(raiz_real, ruta):
    """True si ruta resuelta esta dentro de la raiz resuelta (sin escapar)."""
    try:
        destino = os.path.normcase(os.path.realpath(ruta))
    except OSError:
        return False
    prefijo = os.path.normcase(os.path.realpath(raiz_real)) + os.sep
    return destino.startswith(prefijo)


def _rel(base, ruta):
    try:
        return os.path.relpath(ruta, base).replace(os.sep, "/")
    except ValueError:
        return ruta.replace(os.sep, "/")


def _render(plantilla, params):
    """Sustituye {clave} sin re-formatear los valores (evita inyeccion de llaves)."""
    salida = plantilla
    for clave, valor in params.items():
        salida = salida.replace("{" + clave + "}", str(valor))
    return salida


# ---------------------------------------------------------------------------
# Analisis
# ---------------------------------------------------------------------------

class _Analisis:
    """Estado de un analisis concreto (una instalacion)."""

    def __init__(self, base_dir):
        self.base = os.path.abspath(base_dir)
        self.diagnosticos = []
        self.parciales = set()
        self.no_analizados = []
        self.packs = []
        self.worlds = []
        self.scopes = []
        self.mundo_activo = self._leer_mundo_activo()

    # -- diagnosticos ----------------------------------------------------
    def diag(self, code, source_file, scope=None, pack=None, world=None,
             field=None, ref=None, params=None):
        spec = CATALOGO[code]
        params = params or {}
        entrada = {
            "code": code,
            "severity": spec["severity"],
            "source": spec["source"],
            "determined": spec["determined"],
            "source_file": source_file,
            "scope": scope,
            "pack": pack,
            "world": world,
            "field": field,
            "ref": ref,
            "message_es": _render(spec["es"], params),
            "message_en": _render(spec["en"], params),
        }
        self.diagnosticos.append(entrada)
        if spec["partial"]:
            self.parciales.add(code)
        return entrada

    def no_analizado(self, ruta, motivo_code, detalle=None):
        self.no_analizados.append({
            "path": ruta,
            "reason_code": motivo_code,
            "detail": detalle,
        })

    # -- mundo activo ----------------------------------------------------
    def _leer_mundo_activo(self):
        props = os.path.join(self.base, "server.properties")
        if not os.path.isfile(props):
            return None
        if _es_reparse(props):
            self.diag("SERVER_PROPERTIES_REPARSE", _rel(self.base, props),
                      params={"ruta": _rel(self.base, props)})
            return None
        try:
            return server_properties.read_value(props, "level-name")
        except OSError:
            return None

    # -- ambitos ---------------------------------------------------------
    def _registrar_scope(self, scope_id, origin, kind, root):
        """Registra un ambito y devuelve sus entradas listables (o None)."""
        scope = {
            "id": scope_id,
            "origin": origin,
            "kind": kind,
            "root": _rel(self.base, root),
            "exists": os.path.isdir(root),
        }
        self.scopes.append(scope)
        if not scope["exists"]:
            self.diag("SCOPE_ROOT_MISSING", scope["root"], scope=scope_id,
                      params={"root": scope["root"]})
            return None
        if _es_reparse(root):
            self.diag("SCOPE_ROOT_REPARSE", scope["root"], scope=scope_id,
                      params={"root": scope["root"]})
            return None
        try:
            entradas = sorted(os.scandir(root), key=lambda e: e.name)
        except OSError as exc:
            self.diag("SCOPE_ROOT_UNREADABLE", scope["root"], scope=scope_id,
                      params={"root": scope["root"], "motivo": exc.strerror or str(exc)})
            return None
        return entradas

    def _entradas_seguras(self, scope, root, entradas, reparse_code="SCOPE_ENTRY_REPARSE"):
        """Filtra entradas que no se deben seguir (reparse / fuera de raiz)."""
        seguras = []
        for entrada in entradas:
            ruta = entrada.path
            rel = _rel(self.base, ruta)
            try:
                es_reparse = _es_reparse(ruta)
            except OSError as exc:
                self.diag("SCOPE_ENTRY_UNREADABLE", rel, scope=scope["id"],
                          params={"ruta": rel, "motivo": exc.strerror or str(exc)})
                continue
            if es_reparse:
                self.diag(reparse_code, rel, scope=scope["id"],
                          params={"ruta": rel})
                self.no_analizado(rel, reparse_code)
                continue
            if not _dentro_de(root, ruta):
                self.diag("SCOPE_ENTRY_OUTSIDE_ROOT", rel, scope=scope["id"],
                          params={"ruta": rel, "root": _rel(self.base, root)})
                self.no_analizado(rel, "SCOPE_ENTRY_OUTSIDE_ROOT")
                continue
            seguras.append(entrada)
        return seguras

    # -- escaneo de packs -------------------------------------------------
    def escanear_scope_packs(self, scope_id, origin, kind, root, mundo=None):
        entradas = self._registrar_scope(scope_id, origin, kind, root)
        if entradas is None:
            return
        for entrada in self._entradas_seguras({"id": scope_id}, root, entradas):
            rel = _rel(self.base, entrada.path)
            try:
                es_dir = entrada.is_dir(follow_symlinks=False)
            except OSError as exc:
                self.diag("SCOPE_ENTRY_UNREADABLE", rel, scope=scope_id,
                          params={"ruta": rel, "motivo": exc.strerror or str(exc)})
                continue
            if not es_dir:
                extension = os.path.splitext(entrada.name)[1].lower()
                if extension in EXTENSIONES_EMPAQUETADAS:
                    self.diag("PACK_ARCHIVED_REPRESENTATION", rel, scope=scope_id,
                              params={"ruta": rel, "extension": extension})
                    self.no_analizado(rel, "PACK_ARCHIVED_REPRESENTATION")
                continue
            self.analizar_carpeta_pack(scope_id, origin, kind, root, entrada.path, mundo)

    def analizar_carpeta_pack(self, scope_id, origin, kind, root, carpeta, mundo):
        """Analiza UNA carpeta de pack. Cualquier fallo se aisla por elemento."""
        rel = _rel(self.base, carpeta)
        manifest = os.path.join(carpeta, MANIFEST_NAME)
        try:
            if not os.path.isfile(manifest):
                anidado = _buscar_manifest_anidado(carpeta)
                if anidado is not None:
                    self.diag("PACK_MANIFEST_NESTED", rel, scope=scope_id,
                              params={"ruta": rel, "archivo": MANIFEST_NAME,
                                      "encontrado": _rel(self.base, anidado)})
                    self.no_analizado(rel, "PACK_MANIFEST_NESTED")
                else:
                    self.diag("PACK_FOLDER_WITHOUT_MANIFEST", rel, scope=scope_id,
                              params={"ruta": rel, "archivo": MANIFEST_NAME})
                    self.no_analizado(rel, "PACK_FOLDER_WITHOUT_MANIFEST")
                return
        except OSError as exc:
            self.diag("SCOPE_ENTRY_UNREADABLE", rel, scope=scope_id,
                      params={"ruta": rel, "motivo": exc.strerror or str(exc)})
            return
        pack = {
            "id": rel,
            "folder": rel,
            "manifest": _rel(self.base, manifest),
            "kind": kind,
            "origin": origin,
            "world": mundo,
            "scope": scope_id,
            "status": "ok",
            "unsupported_reason": None,
            "name": None,
            "description": None,
            "format_version": None,
            "header_uuid": None,
            "version": None,
            "min_engine_version": None,
            "pack_scope": None,
            "json_tolerant": False,
            "modules": [],
            "pack_dependencies": [],
            "script_dependencies": [],
            "referenced_by_worlds": [],
            "dependency_resolution": [],
            "scripting_compatibility": "no_determinada",
            "diagnostic_codes": [],
        }
        antes = len(self.diagnosticos)
        try:
            self._leer_manifest(pack, manifest, scope_id, kind)
        except Exception as exc:  # aislamiento: un pack roto no tumba el resto
            self.diag("ITEM_ANALYSIS_ERROR", pack["manifest"], scope=scope_id,
                      pack=pack["id"], world=mundo,
                      params={"ruta": pack["manifest"],
                              "motivo": "%s: %s" % (type(exc).__name__, exc)})
        pack["diagnostic_codes"] = [d["code"] for d in self.diagnosticos[antes:]]
        self.packs.append(pack)

    def _leer_manifest(self, pack, manifest, scope_id, kind):
        if _es_reparse(manifest):
            self.diag("MANIFEST_REPARSE", pack["manifest"], scope=scope_id,
                      pack=pack["id"], world=pack["world"],
                      params={"ruta": pack["manifest"]})
            pack["status"] = "unreadable"
            return
        try:
            texto, codificacion = leer_texto(manifest)
        except OSError as exc:
            self.diag("MANIFEST_UNREADABLE", pack["manifest"], scope=scope_id,
                      pack=pack["id"], world=pack["world"],
                      params={"ruta": pack["manifest"], "motivo": exc.strerror or str(exc)})
            pack["status"] = "unreadable"
            return
        if codificacion == "no_utf8":
            self.diag("MANIFEST_ENCODING_NOT_UTF8", pack["manifest"], scope=scope_id,
                      pack=pack["id"], world=pack["world"],
                      params={"ruta": pack["manifest"]})
        datos, motivo_tolerante, error = cargar_json(texto)
        if error is not None:
            self._marcar_invalido(pack, "MANIFEST_JSON_INVALID", scope_id,
                                  params={"ruta": pack["manifest"], "motivo": error})
            return
        if motivo_tolerante:
            pack["json_tolerant"] = True
            self.diag("MANIFEST_JSON_TOLERANT", pack["manifest"], scope=scope_id,
                      pack=pack["id"], world=pack["world"],
                      params={"ruta": pack["manifest"], "motivo": motivo_tolerante})
        if not isinstance(datos, dict):
            self._marcar_invalido(pack, "MANIFEST_JSON_NOT_OBJECT", scope_id,
                                  params={"ruta": pack["manifest"],
                                          "tipo": _tipo_json(datos)})
            return
        self._leer_format_version(pack, datos, scope_id)
        if pack["status"] == "unsupported":
            return
        self._leer_header(pack, datos, scope_id)
        self._leer_modules(pack, datos, scope_id, kind)
        self._leer_dependencies(pack, datos, scope_id)

    def _marcar_invalido(self, pack, code, scope_id, params, field=None):
        self.diag(code, pack["manifest"], scope=scope_id, pack=pack["id"],
                  world=pack["world"], field=field, params=params)
        if pack["status"] == "ok":
            pack["status"] = "invalid"

    # -- manifiesto: format_version --------------------------------------
    def _leer_format_version(self, pack, datos, scope_id):
        if "format_version" not in datos:
            self._marcar_invalido(pack, "MANIFEST_FORMAT_VERSION_MISSING", scope_id,
                                  params={"ruta": pack["manifest"]},
                                  field="format_version")
            return
        valor = datos["format_version"]
        if isinstance(valor, bool) or not isinstance(valor, int):
            self._marcar_invalido(pack, "MANIFEST_FORMAT_VERSION_INVALID", scope_id,
                                  params={"ruta": pack["manifest"],
                                          "valor": texto_version(valor)},
                                  field="format_version")
            return
        pack["format_version"] = valor
        if valor in FORMATOS_SOPORTADOS:
            return
        motivo = FORMATOS_NO_ANALIZADOS.get(
            valor, "esta fase solo analiza format_version 2 (F1/A1).")
        self.diag("MANIFEST_FORMAT_VERSION_UNSUPPORTED", pack["manifest"],
                  scope=scope_id, pack=pack["id"], world=pack["world"],
                  field="format_version",
                  params={"valor": valor, "ruta": pack["manifest"], "motivo": motivo})
        pack["status"] = "unsupported"
        pack["unsupported_reason"] = "format_version"
        self.no_analizado(pack["manifest"], "MANIFEST_FORMAT_VERSION_UNSUPPORTED",
                          detalle=str(valor))

    # -- manifiesto: header ----------------------------------------------
    def _leer_header(self, pack, datos, scope_id):
        cabecera = datos.get("header")
        if not isinstance(cabecera, dict):
            self._marcar_invalido(pack, "MANIFEST_HEADER_MISSING", scope_id,
                                  params={"ruta": pack["manifest"]}, field="header")
            return
        pack["name"] = cabecera.get("name") if isinstance(cabecera.get("name"), str) else None
        pack["description"] = cabecera.get("description") if isinstance(cabecera.get("description"), str) else None
        if not pack["name"]:
            self.diag("PACK_NAME_MISSING", pack["manifest"], scope=scope_id,
                      pack=pack["id"], world=pack["world"], field="header.name",
                      params={"ruta": pack["manifest"]})
        if not pack["description"]:
            self.diag("PACK_DESCRIPTION_MISSING", pack["manifest"], scope=scope_id,
                      pack=pack["id"], world=pack["world"], field="header.description",
                      params={"ruta": pack["manifest"]})
        uuid = cabecera.get("uuid")
        if uuid is None or (isinstance(uuid, str) and not uuid.strip()):
            self.diag("PACK_UUID_MISSING", pack["manifest"], scope=scope_id,
                      pack=pack["id"], world=pack["world"], field="header.uuid",
                      params={"ruta": pack["manifest"]})
        elif not uuid_valido(uuid):
            self.diag("PACK_UUID_INVALID", pack["manifest"], scope=scope_id,
                      pack=pack["id"], world=pack["world"], field="header.uuid",
                      params={"ruta": pack["manifest"], "valor": texto_version(uuid)})
        else:
            pack["header_uuid"] = normalizar_uuid(uuid)
        self._campo_version(pack, cabecera, "version", scope_id,
                            "PACK_VERSION_MISSING", "PACK_VERSION_INVALID",
                            "PACK_VERSION_FORMAT_UNEXPECTED")
        self._campo_version(pack, cabecera, "min_engine_version", scope_id,
                            "MIN_ENGINE_VERSION_MISSING", "MIN_ENGINE_VERSION_INVALID",
                            "MIN_ENGINE_VERSION_FORMAT_UNEXPECTED")
        pack_scope = cabecera.get("pack_scope")
        if pack_scope is not None:
            pack["pack_scope"] = pack_scope if isinstance(pack_scope, str) else texto_version(pack_scope)
            if pack["pack_scope"] not in PACK_SCOPES_DOCUMENTADOS:
                self.diag("PACK_SCOPE_INVALID", pack["manifest"], scope=scope_id,
                          pack=pack["id"], world=pack["world"], field="header.pack_scope",
                          params={"ruta": pack["manifest"], "valor": pack["pack_scope"]})
        metadatos = datos.get("metadata")
        if isinstance(metadatos, dict):
            producto = metadatos.get("product_type")
            if producto is not None and producto not in PRODUCT_TYPES_DOCUMENTADOS:
                self.diag("PRODUCT_TYPE_INVALID", pack["manifest"], scope=scope_id,
                          pack=pack["id"], world=pack["world"],
                          field="metadata.product_type",
                          params={"ruta": pack["manifest"], "valor": texto_version(producto)})
            generado = metadatos.get("generated_with")
            if "generated_with" in metadatos and not _generated_with_valido(generado):
                self.diag("GENERATED_WITH_INVALID", pack["manifest"], scope=scope_id,
                          pack=pack["id"], world=pack["world"],
                          field="metadata.generated_with",
                          params={"ruta": pack["manifest"], "valor": texto_version(generado)})
        capacidades = datos.get("capabilities")
        if isinstance(capacidades, list):
            desconocidas = [
                c for c in capacidades
                if isinstance(c, str) and c not in CAPABILITIES_DOCUMENTADAS
            ]
            if desconocidas:
                self.diag("CAPABILITY_UNKNOWN", pack["manifest"], scope=scope_id,
                          pack=pack["id"], world=pack["world"], field="capabilities",
                          params={"ruta": pack["manifest"],
                                  "valor": ", ".join(sorted(desconocidas))})

    def _campo_version(self, pack, contenedor, campo, scope_id,
                       code_missing, code_invalid, code_formato):
        """Valida header.version / header.min_engine_version (B5/B8)."""
        if campo not in contenedor:
            self.diag(code_missing, pack["manifest"], scope=scope_id, pack=pack["id"],
                      world=pack["world"], field="header." + campo,
                      params={"ruta": pack["manifest"]})
            return
        valor = contenedor[campo]
        estado, comps = clasificar_version(valor)
        if estado in ("ok", "formato"):
            pack[campo] = list(comps)
        elif estado == "texto":
            pack[campo] = valor
        if estado == "invalido":
            self.diag(code_invalid, pack["manifest"], scope=scope_id, pack=pack["id"],
                      world=pack["world"], field="header." + campo,
                      params={"ruta": pack["manifest"], "valor": texto_version(valor)})
        elif estado in ("formato", "texto"):
            self.diag(code_formato, pack["manifest"], scope=scope_id, pack=pack["id"],
                      world=pack["world"], field="header." + campo,
                      params={"ruta": pack["manifest"], "valor": texto_version(valor)})

    # -- manifiesto: modules ---------------------------------------------
    def _leer_modules(self, pack, datos, scope_id, kind):
        modulos = datos.get("modules")
        if not isinstance(modulos, list) or not modulos:
            self._marcar_invalido(pack, "MANIFEST_MODULES_MISSING", scope_id,
                                  params={"ruta": pack["manifest"]}, field="modules")
            return
        uuids_vistos = {}
        tipos = []
        for indice, modulo in enumerate(modulos):
            campo = "modules[%d]" % indice
            if not isinstance(modulo, dict):
                self.diag("MODULE_NOT_OBJECT", pack["manifest"], scope=scope_id,
                          pack=pack["id"], world=pack["world"], field=campo,
                          params={"indice": indice, "ruta": pack["manifest"]})
                continue
            entrada = {
                "index": indice,
                "type": modulo.get("type") if isinstance(modulo.get("type"), str) else None,
                "uuid": None,
                "version": None,
                "language": modulo.get("language") if isinstance(modulo.get("language"), str) else None,
                "entry": modulo.get("entry") if isinstance(modulo.get("entry"), str) else None,
                "description": modulo.get("description") if isinstance(modulo.get("description"), str) else None,
            }
            tipo = modulo.get("type")
            if tipo is None:
                self.diag("MODULE_TYPE_MISSING", pack["manifest"], scope=scope_id,
                          pack=pack["id"], world=pack["world"], field=campo + ".type",
                          params={"indice": indice, "ruta": pack["manifest"]})
            elif not isinstance(tipo, str):
                self.diag("MODULE_TYPE_MISSING", pack["manifest"], scope=scope_id,
                          pack=pack["id"], world=pack["world"], field=campo + ".type",
                          params={"indice": indice, "ruta": pack["manifest"]})
            elif tipo not in MODULE_TYPES_DOCUMENTADOS:
                self.diag("MODULE_TYPE_UNKNOWN", pack["manifest"], scope=scope_id,
                          pack=pack["id"], world=pack["world"], field=campo + ".type",
                          params={"indice": indice, "ruta": pack["manifest"], "valor": tipo})
            if isinstance(tipo, str):
                tipos.append(tipo)
            uuid = modulo.get("uuid")
            if uuid is None or (isinstance(uuid, str) and not uuid.strip()):
                self.diag("MODULE_UUID_MISSING", pack["manifest"], scope=scope_id,
                          pack=pack["id"], world=pack["world"], field=campo + ".uuid",
                          params={"indice": indice, "ruta": pack["manifest"]})
            elif not uuid_valido(uuid):
                self.diag("MODULE_UUID_INVALID", pack["manifest"], scope=scope_id,
                          pack=pack["id"], world=pack["world"], field=campo + ".uuid",
                          params={"indice": indice, "ruta": pack["manifest"],
                                  "valor": texto_version(uuid)})
            else:
                uuid_norm = normalizar_uuid(uuid)
                entrada["uuid"] = uuid_norm
                if pack["header_uuid"] and uuid_norm == pack["header_uuid"]:
                    self.diag("MODULE_UUID_EQUALS_HEADER", pack["manifest"], scope=scope_id,
                              pack=pack["id"], world=pack["world"], field=campo + ".uuid",
                              params={"indice": indice, "ruta": pack["manifest"]})
                if uuid_norm in uuids_vistos:
                    self.diag("MODULE_UUID_DUPLICATE_IN_PACK", pack["manifest"], scope=scope_id,
                              pack=pack["id"], world=pack["world"], field=campo + ".uuid",
                              params={"indice": indice, "ruta": pack["manifest"]})
                uuids_vistos[uuid_norm] = indice
            if "version" not in modulo:
                self.diag("MODULE_VERSION_MISSING", pack["manifest"], scope=scope_id,
                          pack=pack["id"], world=pack["world"], field=campo + ".version",
                          params={"indice": indice, "ruta": pack["manifest"]})
            else:
                estado, comps = clasificar_version(modulo["version"])
                if estado in ("ok", "formato"):
                    entrada["version"] = list(comps)
                if estado == "invalido":
                    self.diag("MODULE_VERSION_INVALID", pack["manifest"], scope=scope_id,
                              pack=pack["id"], world=pack["world"], field=campo + ".version",
                              params={"indice": indice, "ruta": pack["manifest"],
                                      "valor": texto_version(modulo["version"])})
                elif estado in ("formato", "texto"):
                    self.diag("MODULE_VERSION_FORMAT_UNEXPECTED", pack["manifest"], scope=scope_id,
                              pack=pack["id"], world=pack["world"], field=campo + ".version",
                              params={"indice": indice, "ruta": pack["manifest"],
                                      "valor": texto_version(modulo["version"])})
            idioma = modulo.get("language")
            if idioma is not None and (tipo != "script" or idioma != "javascript"):
                self.diag("MODULE_LANGUAGE_UNEXPECTED", pack["manifest"], scope=scope_id,
                          pack=pack["id"], world=pack["world"], field=campo + ".language",
                          params={"indice": indice, "ruta": pack["manifest"],
                                  "valor": texto_version(idioma)})
            pack["modules"].append(entrada)
        self._validar_kind_modulos(pack, scope_id, kind, tipos)

    def _validar_kind_modulos(self, pack, scope_id, kind, tipos):
        """C2: la carpeta dice el tipo de pack; los modulos deberian coincidir."""
        relevantes = {t for t in tipos if t in ("data", "script", "resources")}
        if not relevantes:
            return
        esperados = {"data", "script"} if kind == "behavior" else {"resources"}
        if relevantes & esperados:
            return
        self.diag("MODULE_KIND_MISMATCH", pack["manifest"], scope=scope_id,
                  pack=pack["id"], world=pack["world"], field="modules",
                  params={"ruta": pack["manifest"],
                          "ubicacion": DIR_COMPARTIDO[kind].rsplit("_", 1)[0],
                          "tipos": ", ".join(sorted(relevantes))})

    # -- manifiesto: dependencies ----------------------------------------
    def _leer_dependencies(self, pack, datos, scope_id):
        dependencias = datos.get("dependencies")
        if dependencias is None:
            return
        if not isinstance(dependencias, list):
            self.diag("DEPENDENCY_NOT_OBJECT", pack["manifest"], scope=scope_id,
                      pack=pack["id"], world=pack["world"], field="dependencies",
                      params={"indice": 0, "ruta": pack["manifest"]})
            return
        for indice, dep in enumerate(dependencias):
            campo = "dependencies[%d]" % indice
            if not isinstance(dep, dict):
                self.diag("DEPENDENCY_NOT_OBJECT", pack["manifest"], scope=scope_id,
                          pack=pack["id"], world=pack["world"], field=campo,
                          params={"indice": indice, "ruta": pack["manifest"]})
                continue
            tiene_uuid = "uuid" in dep
            tiene_modulo = "module_name" in dep
            if not tiene_uuid and not tiene_modulo:
                self.diag("DEPENDENCY_WITHOUT_KEY", pack["manifest"], scope=scope_id,
                          pack=pack["id"], world=pack["world"], field=campo,
                          params={"indice": indice, "ruta": pack["manifest"]})
                continue
            if tiene_uuid:
                self._dependencia_de_pack(pack, dep, indice, scope_id)
            if tiene_modulo:
                self._dependencia_de_script(pack, dep, indice, scope_id)

    def _dependencia_de_pack(self, pack, dep, indice, scope_id):
        campo = "dependencies[%d].uuid" % indice
        uuid = dep.get("uuid")
        entrada = {
            "index": indice,
            "uuid": None,
            "version": None,
            "version_presente": "version" in dep,
        }
        if not uuid_valido(uuid):
            self.diag("DEPENDENCY_PACK_UUID_INVALID", pack["manifest"], scope=scope_id,
                      pack=pack["id"], world=pack["world"], field=campo,
                      params={"indice": indice, "ruta": pack["manifest"],
                              "valor": texto_version(uuid)})
            pack["pack_dependencies"].append(entrada)
            return
        entrada["uuid"] = normalizar_uuid(uuid)
        if "version" not in dep:
            self.diag("DEPENDENCY_PACK_VERSION_MISSING", pack["manifest"], scope=scope_id,
                      pack=pack["id"], world=pack["world"],
                      field="dependencies[%d].version" % indice,
                      params={"indice": indice, "ruta": pack["manifest"]})
        else:
            estado, comps = clasificar_version(dep["version"])
            if estado in ("ok", "formato"):
                entrada["version"] = list(comps)
            if estado == "invalido":
                self.diag("DEPENDENCY_PACK_VERSION_INVALID", pack["manifest"], scope=scope_id,
                          pack=pack["id"], world=pack["world"],
                          field="dependencies[%d].version" % indice,
                          params={"indice": indice, "ruta": pack["manifest"],
                                  "valor": texto_version(dep["version"])})
        pack["pack_dependencies"].append(entrada)

    def _dependencia_de_script(self, pack, dep, indice, scope_id):
        campo = "dependencies[%d].module_name" % indice
        nombre = dep.get("module_name")
        entrada = {"index": indice, "module_name": None, "version": None, "beta": False,
                   "internal": False}
        if not isinstance(nombre, str) or not nombre.strip():
            self.diag("SCRIPT_DEP_MODULE_NAME_INVALID", pack["manifest"], scope=scope_id,
                      pack=pack["id"], world=pack["world"], field=campo,
                      params={"indice": indice, "ruta": pack["manifest"],
                              "valor": texto_version(nombre)})
            pack["script_dependencies"].append(entrada)
            return
        nombre = nombre.strip()
        entrada["module_name"] = nombre
        if not nombre.startswith("@"):
            self.diag("SCRIPT_DEP_MODULE_NAME_INVALID", pack["manifest"], scope=scope_id,
                      pack=pack["id"], world=pack["world"], field=campo,
                      params={"indice": indice, "ruta": pack["manifest"], "valor": nombre})
        version = dep.get("version")
        if version is None:
            self.diag("SCRIPT_DEP_VERSION_MISSING", pack["manifest"], scope=scope_id,
                      pack=pack["id"], world=pack["world"],
                      field="dependencies[%d].version" % indice,
                      params={"indice": indice, "ruta": pack["manifest"], "valor": nombre})
            pack["script_dependencies"].append(entrada)
            return
        texto = version if isinstance(version, str) else texto_version(version)
        entrada["version"] = texto
        if not isinstance(version, str) or not _version_script_valida(version):
            self.diag("SCRIPT_DEP_VERSION_INVALID", pack["manifest"], scope=scope_id,
                      pack=pack["id"], world=pack["world"],
                      field="dependencies[%d].version" % indice,
                      params={"indice": indice, "ruta": pack["manifest"],
                              "valor": texto, "modulo": nombre})
            pack["script_dependencies"].append(entrada)
            return
        sufijo = version.split("-", 1)[1].lower() if "-" in version else ""
        if sufijo.startswith("internal"):
            entrada["internal"] = True
            self.diag("SCRIPT_DEP_INTERNAL", pack["manifest"], scope=scope_id,
                      pack=pack["id"], world=pack["world"],
                      field="dependencies[%d].version" % indice,
                      params={"ruta": pack["manifest"], "modulo": nombre, "version": texto})
        elif version.strip().lower() == "beta" or sufijo.startswith("beta") or sufijo:
            entrada["beta"] = True
            self.diag("SCRIPT_DEP_BETA", pack["manifest"], scope=scope_id,
                      pack=pack["id"], world=pack["world"],
                      field="dependencies[%d].version" % indice,
                      params={"ruta": pack["manifest"], "modulo": nombre, "version": texto})
        pack["script_dependencies"].append(entrada)

    # -- mundos -----------------------------------------------------------
    def escanear_worlds(self):
        raiz = os.path.join(self.base, "worlds")
        entradas = self._registrar_scope("worlds", "mundos", None, raiz)
        if entradas is None:
            return
        for entrada in self._entradas_seguras({"id": "worlds"}, raiz, entradas,
                                               reparse_code="WORLD_ENTRY_REPARSE"):
            rel = _rel(self.base, entrada.path)
            try:
                if not entrada.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            self.analizar_mundo(entrada.name, entrada.path, rel)

    def analizar_mundo(self, nombre, carpeta, rel):
        mundo = {
            "name": nombre,
            "path": rel,
            "active": bool(self.mundo_activo) and nombre == self.mundo_activo,
            "has_level_dat": os.path.isfile(os.path.join(carpeta, "level.dat")),
            "ref_files": [],
            "references": [],
            "pack_dirs": {},
            "diagnostic_codes": [],
        }
        antes = len(self.diagnosticos)
        try:
            if not mundo["has_level_dat"]:
                self.diag("WORLD_WITHOUT_LEVEL_DAT", rel, scope="mundo:%s" % nombre,
                          world=nombre, params={"ruta": rel})
            for kind in KINDS:
                sub = os.path.join(carpeta, DIR_COMPARTIDO[kind])
                mundo["pack_dirs"][kind] = os.path.isdir(sub)
                if mundo["pack_dirs"][kind]:
                    self.escanear_scope_packs(
                        "mundo:%s:%s" % (nombre, kind), "mundo", kind, sub, nombre
                    )
            for kind in KINDS:
                self._leer_referencias_mundo(mundo, carpeta, kind)
        except Exception as exc:
            self.diag("ITEM_ANALYSIS_ERROR", rel, scope="mundo:%s" % nombre,
                      world=nombre,
                      params={"ruta": rel, "motivo": "%s: %s" % (type(exc).__name__, exc)})
        mundo["diagnostic_codes"] = [d["code"] for d in self.diagnosticos[antes:]]
        self.worlds.append(mundo)

    def _leer_referencias_mundo(self, mundo, carpeta, kind):
        archivo = WORLD_REF_FILES[kind]
        ruta = os.path.join(carpeta, archivo)
        rel = _rel(self.base, ruta)
        scope_id = "mundo:%s:%s" % (mundo["name"], kind)
        estado = {"kind": kind, "file": rel, "status": "missing", "references": 0}
        mundo["ref_files"].append(estado)
        if not os.path.isfile(ruta):
            return
        if _es_reparse(ruta):
            self.diag("WORLD_REFS_REPARSE", rel, scope=scope_id, world=mundo["name"],
                      params={"ruta": rel})
            estado["status"] = "reparse"
            return
        try:
            texto, codificacion = leer_texto(ruta)
        except OSError as exc:
            self.diag("WORLD_REFS_UNREADABLE", rel, scope=scope_id, world=mundo["name"],
                      params={"ruta": rel, "motivo": exc.strerror or str(exc),
                              "mundo": mundo["name"]})
            estado["status"] = "unreadable"
            return
        if codificacion == "no_utf8":
            self.diag("MANIFEST_ENCODING_NOT_UTF8", rel, scope=scope_id,
                      world=mundo["name"], params={"ruta": rel})
        datos, _motivo, error = cargar_json(texto)
        if error is not None:
            self.diag("WORLD_REFS_JSON_INVALID", rel, scope=scope_id, world=mundo["name"],
                      params={"ruta": rel, "motivo": error})
            estado["status"] = "invalid"
            return
        if not isinstance(datos, list):
            self.diag("WORLD_REFS_NOT_ARRAY", rel, scope=scope_id, world=mundo["name"],
                      params={"ruta": rel, "tipo": _tipo_json(datos)})
            estado["status"] = "unsupported"
            return
        estado["status"] = "ok"
        for indice, item in enumerate(datos):
            self._leer_referencia(mundo, kind, rel, scope_id, indice, item)
        estado["references"] = sum(
            1 for r in mundo["references"] if r["file"] == rel)

    def _leer_referencia(self, mundo, kind, rel, scope_id, indice, item):
        ref = {
            "kind": kind,
            "file": rel,
            "index": indice,
            "pack_id": None,
            "version": None,
            "status": "invalid",
            "resolved_pack": None,
            "candidates": [],
        }
        if not isinstance(item, dict):
            self.diag("WORLD_REFS_ENTRY_INVALID", rel, scope=scope_id, world=mundo["name"],
                      field="[%d]" % indice,
                      params={"ruta": rel, "indice": indice})
            mundo["references"].append(ref)
            return
        pack_id = item.get("pack_id")
        if pack_id is None:
            self.diag("WORLD_REF_PACK_ID_MISSING", rel, scope=scope_id, world=mundo["name"],
                      field="[%d].pack_id" % indice,
                      params={"ruta": rel, "indice": indice})
            mundo["references"].append(ref)
            return
        if not uuid_valido(pack_id):
            self.diag("WORLD_REF_PACK_ID_INVALID", rel, scope=scope_id, world=mundo["name"],
                      field="[%d].pack_id" % indice,
                      ref={"pack_id": pack_id},
                      params={"ruta": rel, "indice": indice,
                              "valor": texto_version(pack_id)})
            mundo["references"].append(ref)
            return
        ref["pack_id"] = normalizar_uuid(pack_id)
        if "version" not in item or item.get("version") is None:
            self.diag("WORLD_REF_VERSION_MISSING", rel, scope=scope_id, world=mundo["name"],
                      field="[%d].version" % indice,
                      ref={"pack_id": ref["pack_id"]},
                      params={"ruta": rel, "indice": indice, "valor": ref["pack_id"]})
            ref["status"] = "version_missing"
            mundo["references"].append(ref)
            return
        estado, comps = clasificar_version(item["version"])
        if estado in ("ok", "formato"):
            ref["version"] = list(comps)
        if estado == "invalido":
            self.diag("WORLD_REF_VERSION_INVALID", rel, scope=scope_id, world=mundo["name"],
                      field="[%d].version" % indice,
                      ref={"pack_id": ref["pack_id"], "version": item["version"]},
                      params={"ruta": rel, "indice": indice,
                              "valor": texto_version(item["version"])})
            mundo["references"].append(ref)
            return
        if estado in ("formato", "texto"):
            self.diag("WORLD_REF_VERSION_FORMAT_UNEXPECTED", rel, scope=scope_id,
                      world=mundo["name"], field="[%d].version" % indice,
                      ref={"pack_id": ref["pack_id"], "version": item["version"]},
                      params={"ruta": rel, "indice": indice,
                              "valor": texto_version(item["version"])})
        ref["status"] = "pending"
        mundo["references"].append(ref)

    # -- resolucion --------------------------------------------------------
    def resolver_referencias(self):
        """Relaciona cada referencia de mundo con los candidatos de su ambito."""
        por_uuid = {}
        for pack in self.packs:
            if pack["header_uuid"]:
                por_uuid.setdefault(pack["header_uuid"], []).append(pack)
        for mundo in self.worlds:
            for ref in mundo["references"]:
                if ref["status"] != "pending":
                    continue
                ambito = self._ambito_de_mundo(mundo["name"], ref["kind"])
                candidatos = [
                    p for p in por_uuid.get(ref["pack_id"], [])
                    if p["scope"] in ambito and p["status"] in ("ok", "invalid")
                ]
                ref["candidates"] = [
                    {"pack": p["id"], "name": p["name"], "version": p["version"],
                     "kind": p["kind"], "scope": p["scope"]}
                    for p in candidatos
                ]
                if not candidatos:
                    # F-4: cada archivo deberia listar solo packs de su tipo.
                    # Si el UUID solo existe en el ambito del OTRO tipo, el
                    # hallazgo es de tipo cruzado (aviso), no un fantasma.
                    otro_kind = "resource" if ref["kind"] == "behavior" else "behavior"
                    otro_ambito = self._ambito_de_mundo(mundo["name"], otro_kind)
                    cruzados = [
                        p for p in por_uuid.get(ref["pack_id"], [])
                        if p["scope"] in otro_ambito and p["status"] in ("ok", "invalid")
                    ]
                    if cruzados:
                        ref["status"] = "kind_mismatch"
                        ref["candidates"] = [
                            {"pack": p["id"], "name": p["name"], "version": p["version"],
                             "kind": p["kind"], "scope": p["scope"]}
                            for p in cruzados
                        ]
                        for pack in cruzados:
                            pack["referenced_by_worlds"].append(mundo["name"])
                        self.diag("WORLD_REF_KIND_MISMATCH", ref["file"],
                                  scope=ref["kind"], world=mundo["name"],
                                  pack=cruzados[0]["id"],
                                  field="[%d].pack_id" % ref["index"],
                                  ref={"pack_id": ref["pack_id"], "version": ref["version"]},
                                  params={"mundo": mundo["name"], "uuid": ref["pack_id"],
                                          "archivo": os.path.basename(ref["file"]),
                                          "pack": "; ".join(p["id"] for p in cruzados),
                                          "tipo": cruzados[0]["kind"]})
                        continue
                    ref["status"] = "unresolved"
                    fuera = self._ambitos_fuera(mundo["name"], ref["kind"], ref["pack_id"])
                    extra = ""
                    if fuera:
                        extra = ("; el UUID existe en %s, que no esta disponible para este mundo"
                                 % ", ".join(fuera))
                    self.diag("WORLD_REF_UNRESOLVED", ref["file"], scope=ref["kind"],
                              world=mundo["name"], field="[%d].pack_id" % ref["index"],
                              ref={"pack_id": ref["pack_id"], "version": ref["version"]},
                              params={"mundo": mundo["name"], "uuid": ref["pack_id"],
                                      "version": texto_version(ref["version"]),
                                      "ambito": self._nombre_ambito(mundo["name"], ref["kind"]),
                                      "extra": extra})
                    continue
                exactos = [p for p in candidatos if p["version"] == ref["version"]]
                if len(exactos) == 1:
                    ref["status"] = "resolved"
                    ref["resolved_pack"] = exactos[0]["id"]
                    exactos[0]["referenced_by_worlds"].append(mundo["name"])
                    continue
                if len(exactos) > 1:
                    ref["status"] = "ambiguous"
                    self.diag("WORLD_REF_AMBIGUOUS", ref["file"], scope=ref["kind"],
                              world=mundo["name"], field="[%d].pack_id" % ref["index"],
                              ref={"pack_id": ref["pack_id"], "version": ref["version"]},
                              params={"mundo": mundo["name"], "uuid": ref["pack_id"],
                                      "version": texto_version(ref["version"]),
                                      "cuantos": len(exactos),
                                      "ambito": self._nombre_ambito(mundo["name"], ref["kind"]),
                                      "candidatos": "; ".join(p["id"] for p in exactos)})
                    for pack in exactos:
                        pack["referenced_by_worlds"].append(mundo["name"])
                    continue
                ref["status"] = "version_unavailable"
                self.diag("WORLD_REF_VERSION_UNAVAILABLE", ref["file"], scope=ref["kind"],
                          world=mundo["name"], field="[%d].version" % ref["index"],
                          ref={"pack_id": ref["pack_id"], "version": ref["version"]},
                          params={"mundo": mundo["name"], "uuid": ref["pack_id"],
                                  "version": texto_version(ref["version"]),
                                  "ambito": self._nombre_ambito(mundo["name"], ref["kind"]),
                                  "versiones": ", ".join(
                                      sorted({texto_version(p["version"]) for p in candidatos}))})

    def _ambito_de_mundo(self, nombre, kind):
        return {"mundo:%s:%s" % (nombre, kind), "compartido:" + kind, "sistema:" + kind}

    def _ambitos_fuera(self, nombre, kind, uuid):
        fuera = sorted({
            p["scope"] for p in self.packs
            if p["header_uuid"] == uuid and p["scope"] not in self._ambito_de_mundo(nombre, kind)
        })
        return fuera

    def _nombre_ambito(self, nombre, kind):
        etiqueta = "packs de comportamiento" if kind == "behavior" else "packs de recursos"
        return ("el ambito del mundo %s mas los compartidos y de sistema (%s)"
                % (nombre, etiqueta))

    # -- dependencias entre packs -----------------------------------------
    def resolver_dependencias(self):
        por_uuid = {}
        for pack in self.packs:
            if pack["header_uuid"] and pack["status"] in ("ok", "invalid"):
                por_uuid.setdefault(pack["header_uuid"], []).append(pack)
        contextos = self._contextos_de_dependencias(por_uuid)
        for pack in self.packs:
            if pack["status"] not in ("ok", "invalid"):
                continue
            mundos = sorted(contextos[pack["id"]]) or [None]
            for dep in pack["pack_dependencies"]:
                if not dep["uuid"]:
                    continue
                por_mundo = [
                    self._resolver_dependencia(pack, dep, por_uuid, mundo)
                    for mundo in mundos
                ]
                estados = {r["status"] for r in por_mundo}
                candidatos = {c["pack"]: c for r in por_mundo for c in r["candidates"]}
                resolucion = {
                    "uuid": dep["uuid"], "version": dep["version"],
                    "status": por_mundo[0]["status"],
                    "candidates": [candidatos[k] for k in sorted(candidatos)],
                    "world_resolutions": por_mundo,
                }
                if len(estados) > 1:
                    resolucion["status"] = "context_dependent"
                pack["dependency_resolution"].append(resolucion)

    def _contextos_de_dependencias(self, por_uuid):
        """Mundos de uso, incluidos consumidores transitivos; ciclos acotados.

        Los packs locales tienen su mundo propio. Los compartidos/de sistema
        heredan los mundos que los referencian o los necesitan como dependencia.
        Sin mundo conocido solo se comprueba el ambito compartido/de sistema.
        Esto describe disponibilidad estatica, no carga efectiva por BDS.
        """
        por_id = {p["id"]: p for p in self.packs}
        contextos = {p["id"]: set() for p in self.packs}
        pendientes = [(p["id"], p["world"]) for p in self.packs if p["world"] is not None]
        for mundo in self.worlds:
            for ref in mundo["references"]:
                if ref["resolved_pack"]:
                    pendientes.append((ref["resolved_pack"], mundo["name"]))
                elif ref["status"] in ("ambiguous", "kind_mismatch"):
                    pendientes.extend((c["pack"], mundo["name"]) for c in ref["candidates"])
        while pendientes:
            pack_id, mundo = pendientes.pop()
            if mundo in contextos[pack_id]:
                continue
            contextos[pack_id].add(mundo)
            for dep in por_id[pack_id]["pack_dependencies"]:
                for candidato in por_uuid.get(dep["uuid"], []):
                    if (self._disponible_en_mundo(candidato, mundo)
                            and (dep["version"] is None or candidato["version"] == dep["version"])):
                        pendientes.append((candidato["id"], mundo))
        return contextos

    def _resolver_dependencia(self, pack, dep, por_uuid, mundo):
        candidatos = [p for p in por_uuid.get(dep["uuid"], [])
                      if self._disponible_en_mundo(p, mundo)]
        resolucion = {"world": mundo, "status": "missing", "candidates": []}
        contexto = ("worlds/%s + behavior_packs/resource_packs + system_*" % mundo
                    if mundo else pack["scope"])
        if not candidatos:
            self.diag("DEPENDENCY_PACK_MISSING", pack["manifest"],
                      scope=pack["scope"], pack=pack["id"], world=mundo,
                      field="dependencies[%d].uuid" % dep["index"],
                      ref={"pack_uuid": dep["uuid"], "version": dep["version"]},
                      params={"ruta": pack["manifest"], "uuid": dep["uuid"], "ambito": contexto})
            return resolucion
        resolucion["candidates"] = [
            {"pack": p["id"], "name": p["name"], "version": p["version"],
             "kind": p["kind"], "scope": p["scope"]}
            for p in candidatos
        ]
        exactos = [p for p in candidatos if dep["version"] and p["version"] == dep["version"]]
        if len(exactos) == 1:
            resolucion["status"] = "resolved"
        elif len(exactos) > 1:
            resolucion["status"] = "ambiguous"
            self.diag("DEPENDENCY_PACK_AMBIGUOUS", pack["manifest"],
                      scope=pack["scope"], pack=pack["id"], world=mundo,
                      field="dependencies[%d].uuid" % dep["index"],
                      ref={"pack_uuid": dep["uuid"], "version": dep["version"]},
                      params={"ruta": pack["manifest"], "uuid": dep["uuid"],
                              "candidatos": "; ".join(p["id"] for p in exactos)})
        elif dep["version"] is None:
            resolucion["status"] = "unchecked"
        else:
            mismo_tipo = [p for p in candidatos if p["kind"] == pack["kind"]]
            if not mismo_tipo:
                # Compatibilidad historica: un BP puede depender de un RP.
                # La discrepancia de version queda como estado sin diagnostico.
                resolucion["status"] = "other_kind"
            else:
                resolucion["status"] = "version_mismatch"
                candidato = mismo_tipo[0]
                self.diag("DEPENDENCY_PACK_VERSION_MISMATCH", pack["manifest"],
                          scope=pack["scope"], pack=pack["id"], world=mundo,
                          field="dependencies[%d].version" % dep["index"],
                          ref={"pack_uuid": dep["uuid"], "version": dep["version"]},
                          params={"ruta": pack["manifest"], "uuid": dep["uuid"],
                                  "version": texto_version(dep["version"]),
                                  "instalada": texto_version(candidato["version"])})
        return resolucion

    def _disponible_en_mundo(self, candidato, mundo):
        """F2/E4/E5: raiz compartida/sistema mas el mundo que se evalua."""
        return (candidato["origin"] in ("compartido", "sistema")
                or (mundo is not None and candidato["world"] == mundo))

    # -- identidad ---------------------------------------------------------
    def detectar_duplicados(self):
        por_scope = {}
        por_uuid_global = {}
        por_modulo_scope = {}
        for pack in self.packs:
            if not pack["header_uuid"]:
                continue
            por_scope.setdefault(pack["scope"], {}).setdefault(pack["header_uuid"], []).append(pack)
            por_uuid_global.setdefault(pack["header_uuid"], {}).setdefault(pack["scope"], []).append(pack)
            for modulo in pack["modules"]:
                if modulo.get("uuid"):
                    por_modulo_scope.setdefault(pack["scope"], {}).setdefault(
                        modulo["uuid"], []).append((pack, modulo))
        # Igual UUID y misma version dentro del mismo ambito: identidad duplicada.
        for scope_id, por_uuid in sorted(por_scope.items()):
            for uuid, packs in sorted(por_uuid.items()):
                if len(packs) < 2:
                    continue
                por_version = {}
                for pack in packs:
                    por_version.setdefault(texto_version(pack["version"]), []).append(pack)
                duplicados = [(v, ps) for v, ps in por_version.items() if len(ps) > 1]
                if duplicados:
                    for version, ps in sorted(duplicados):
                        primero = ps[0]
                        self.diag("PACK_UUID_DUPLICATE", primero["manifest"], scope=scope_id,
                                  pack=primero["id"], world=primero["world"],
                                  field="header.uuid",
                                  params={"uuid": uuid, "version": version,
                                          "ambito": scope_id,
                                          "otros": "; ".join(p["id"] for p in ps[1:])})
                else:
                    versiones = sorted({texto_version(p["version"]) for p in packs})
                    self.diag("PACK_UUID_MULTIPLE_VERSIONS", packs[0]["manifest"],
                              scope=scope_id, pack=packs[0]["id"], world=packs[0]["world"],
                              field="header.uuid",
                              params={"uuid": uuid, "cuantos": len(packs),
                                      "ambito": scope_id,
                                      "versiones": ", ".join(versiones)})
        for uuid, scopes in sorted(por_uuid_global.items()):
            if len(scopes) > 1:
                primero = sorted(scopes.items())[0][1][0]
                self.diag("PACK_UUID_IN_OTHER_SCOPES", primero["manifest"],
                          scope=primero["scope"], pack=primero["id"], world=primero["world"],
                          field="header.uuid",
                          params={"uuid": uuid,
                                  "ambitos": ", ".join(sorted(scopes))})
        # Modulos con el mismo UUID en packs distintos del mismo ambito. El
        # patron de los packs vanilla versionados de BDS (mismo UUID, version
        # distinta) NO es un conflicto: solo se reporta si comparten version.
        for scope_id, por_uuid in sorted(por_modulo_scope.items()):
            for uuid, apariciones in sorted(por_uuid.items()):
                packs = sorted({p["id"]: p for p, _m in apariciones}.values(),
                               key=lambda p: p["id"])
                if len(packs) < 2:
                    continue
                versiones = {texto_version(p["version"]) for p in packs}
                if len(versiones) > 1:
                    continue
                self.diag("MODULE_UUID_DUPLICATE_IN_SCOPE", packs[0]["manifest"],
                          scope=scope_id, pack=packs[0]["id"],
                          world=packs[0]["world"], field="modules",
                          params={"uuid": uuid,
                                  "otros": "; ".join(p["id"] for p in packs[1:])})
        # UUID reservado por un pack de sistema (how-to de BDS).
        sistema = {}
        for pack in self.packs:
            if pack["origin"] == "sistema" and pack["header_uuid"]:
                sistema[pack["header_uuid"]] = pack["id"]
        for pack in self.packs:
            if pack["origin"] == "sistema" or not pack["header_uuid"]:
                continue
            if pack["header_uuid"] in sistema:
                self.diag("SYSTEM_PACK_UUID_PROTECTED", pack["manifest"], scope=pack["scope"],
                          pack=pack["id"], world=pack["world"], field="header.uuid",
                          params={"ruta": pack["manifest"], "uuid": pack["header_uuid"],
                                  "sistema": sistema[pack["header_uuid"]]})

    # -- ejecucion ---------------------------------------------------------
    def ejecutar(self):
        if not os.path.isdir(self.base):
            self.diag("BASE_DIR_MISSING", _rel(os.getcwd(), self.base),
                      params={"ruta": self.base})
            return self._payload()
        for origin, tabla in (("compartido", DIR_COMPARTIDO), ("sistema", DIR_SISTEMA)):
            for kind in KINDS:
                raiz = os.path.join(self.base, tabla[kind])
                self.escanear_scope_packs("%s:%s" % (origin, kind), origin, kind, raiz)
        self.escanear_worlds()
        self.detectar_duplicados()
        self.resolver_referencias()
        self.resolver_dependencias()
        return self._payload()

    # -- payload -----------------------------------------------------------
    def _payload(self):
        self.scopes.sort(key=lambda s: (_ORDEN_ORIGEN.get(s["origin"], 9), s["id"]))
        self.packs.sort(key=lambda p: (p["scope"], p["folder"]))
        self.worlds.sort(key=lambda w: w["name"])
        # Un mundo puede referenciar el mismo pack en los dos archivos o
        # repetir la entrada: esta lista responde "que mundos referencian el
        # pack", asi que se presenta sin repetir (orden de primera aparicion).
        # Las referencias del mundo y sus diagnosticos conservan cada entrada.
        for pack in self.packs:
            if len(pack["referenced_by_worlds"]) > 1:
                pack["referenced_by_worlds"] = list(dict.fromkeys(
                    pack["referenced_by_worlds"]))
        self.diagnosticos.sort(key=lambda d: (
            _ORDEN_SEVERIDAD.get(d["severity"], 9), d["code"],
            d["source_file"] or "", d["field"] or "",
        ))
        self.no_analizados.sort(key=lambda n: (n["reason_code"], n["path"]))
        resumen = {
            "packs_total": len(self.packs),
            "packs_analizados": sum(1 for p in self.packs if p["status"] == "ok"),
            "packs_behavior": sum(1 for p in self.packs if p["kind"] == "behavior"),
            "packs_resource": sum(1 for p in self.packs if p["kind"] == "resource"),
            "packs_compartidos": sum(1 for p in self.packs if p["origin"] == "compartido"),
            "packs_de_sistema": sum(1 for p in self.packs if p["origin"] == "sistema"),
            "packs_de_mundo": sum(1 for p in self.packs if p["origin"] == "mundo"),
            "packs_sin_analizar": sum(1 for p in self.packs if p["status"] == "unsupported"),
            "packs_ilegibles": sum(1 for p in self.packs if p["status"] == "unreadable"),
            "packs_invalidos": sum(1 for p in self.packs if p["status"] == "invalid"),
            "mundos_total": len(self.worlds),
            "referencias_total": sum(len(w["references"]) for w in self.worlds),
            "referencias_resueltas": sum(
                1 for w in self.worlds for r in w["references"] if r["status"] == "resolved"),
            "referencias_sin_resolver": sum(
                1 for w in self.worlds for r in w["references"] if r["status"] == "unresolved"),
            "referencias_ambiguas": sum(
                1 for w in self.worlds for r in w["references"] if r["status"] == "ambiguous"),
            "referencias_tipo_cruzado": sum(
                1 for w in self.worlds for r in w["references"] if r["status"] == "kind_mismatch"),
            "referencias_sin_version": sum(
                1 for w in self.worlds for r in w["references"] if r["status"] == "version_unavailable"),
            "diagnosticos_total": len(self.diagnosticos),
            "errores": sum(1 for d in self.diagnosticos if d["severity"] == "error"),
            "avisos": sum(1 for d in self.diagnosticos if d["severity"] == "aviso"),
            "informativos": sum(1 for d in self.diagnosticos if d["severity"] == "info"),
        }
        completo = not self.parciales
        resumen["complete"] = completo
        return {
            "schema_version": SCHEMA_VERSION,
            "base_dir": self.base,
            "complete": completo,
            "partial_reasons": sorted(self.parciales),
            "active_world": self.mundo_activo,
            "supported": {
                "manifest_format_versions": list(FORMATOS_SOPORTADOS),
                "manifest_format_versions_not_analyzed": {
                    str(k): v for k, v in sorted(FORMATOS_NO_ANALIZADOS.items())
                },
                "locations": ["behavior_packs", "resource_packs",
                              "system_behavior_packs", "system_resource_packs",
                              "worlds/<mundo>/behavior_packs", "worlds/<mundo>/resource_packs"],
                "excluded_locations": ["development_behavior_packs",
                                       "development_resource_packs", "world_templates"],
                "documented_module_types": list(MODULE_TYPES_DOCUMENTADOS),
                "world_reference_files": sorted(WORLD_REF_FILES.values()),
            },
            "scopes": self.scopes,
            "packs": self.packs,
            "worlds": self.worlds,
            "not_analyzed": self.no_analizados,
            "diagnostics": self.diagnosticos,
            "summary": resumen,
        }


_ORDEN_ORIGEN = {"compartido": 0, "sistema": 1, "mundo": 2, "mundos": 3}


def _buscar_manifest_anidado(carpeta, profundidad=2):
    """Busca manifest.json por debajo de <carpeta>/<sub>/manifest.json.

    Devuelve la primera ruta encontrada (ordenada) o None.
    """
    try:
        hijos = sorted(os.scandir(carpeta), key=lambda e: e.name)
    except OSError:
        return None
    for hijo in hijos:
        try:
            if not hijo.is_dir(follow_symlinks=False):
                continue
        except OSError:
            continue
        if _es_reparse(hijo.path):
            continue
        candidato = os.path.join(hijo.path, MANIFEST_NAME)
        if os.path.isfile(candidato):
            return candidato
    return None


def _generated_with_valido(valor):
    """Objeto {herramienta: [versiones SemVer]} del ejemplo oficial F1/A5.

    F1 no impone un minimo de herramientas ni de versiones.
    """
    if not isinstance(valor, dict):
        return False
    for nombre, versiones in valor.items():
        if not isinstance(nombre, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", nombre):
            return False
        if not isinstance(versiones, list):
            return False
        if any(not isinstance(v, str) or not _RE_TOOL_SEMVER.fullmatch(v) for v in versiones):
            return False
    return True


def _version_script_valida(valor):
    """Version de una dependencia de modulo de scripting (D5)."""
    if not isinstance(valor, str):
        return False
    texto = valor.strip()
    if not texto:
        return False
    if texto.lower() == "beta":
        return True
    return bool(_RE_SEMVER.match(texto))


# ---------------------------------------------------------------------------
# API publica
# ---------------------------------------------------------------------------

def analyze_addons(base_dir=None):
    """Inventario + diagnostico deterministico de una instalacion.

    Solo lee: no crea, modifica ni borra nada. `base_dir` por defecto es la
    carpeta de este modulo (la instalacion que contiene al analizador).
    """
    base = base_dir or os.path.dirname(os.path.abspath(__file__))
    return _Analisis(base).ejecutar()


def filter_payload(payload, world=None, kind=None):
    """Vista filtrada de un payload ya calculado (misma semantica CLI/GUI).

    - `world`: conserva los packs del ambito de ese mundo (propios, compartidos
      y de sistema, que son los que pueden resolver sus referencias) y solo ese
      mundo. El resumen filtrado se acompana de `summary_installation`.
    - `kind`: conserva packs, referencias, archivos de referencias y diagnosticos
      de ese tipo ("behavior"/"resource"), ademas de diagnosticos sin tipo.
    `complete` y `partial_reasons` describen SIEMPRE la instalacion completa.
    """
    if world is None and kind is None:
        return payload
    kinds = [kind] if kind in KINDS else list(KINDS)
    scopes = {
        "compartido:" + k for k in kinds
    } | {"sistema:" + k for k in kinds}
    if world is None:
        scopes |= {s["id"] for s in payload["scopes"] if s["id"].startswith("mundo:")}
    else:
        scopes |= {"mundo:%s:%s" % (world, k) for k in kinds}
    packs = [
        p for p in payload["packs"]
        if p["scope"] in scopes and p["kind"] in kinds
        and (world is None or p["origin"] in ("compartido", "sistema") or p["world"] == world)
    ]
    ids = {p["id"] for p in packs}
    worlds = [
        dict(w, references=[r for r in w["references"] if kind not in KINDS or r.get("kind") in kinds],
             ref_files=[f for f in w["ref_files"] if f["kind"] in kinds],
             pack_dirs={k: v for k, v in w["pack_dirs"].items() if k in kinds})
        for w in payload["worlds"]
        if world is None or w["name"] == world
    ]
    nombres_mundo = {w["name"] for w in worlds}
    diagnostics = [
        d for d in payload["diagnostics"]
        if (world is None or d["world"] is None or d["world"] == world)
        and (kind not in KINDS or _tipo_de_scope(d["scope"]) in (None, kind))
        and (d["scope"] in scopes
            or (d["world"] is not None and d["world"] in nombres_mundo)
            or d["scope"] is None)
        and (d["pack"] is None or d["pack"] in ids)
    ]
    if world is not None:
        packs = [dict(p, dependency_resolution=[
            _resolucion_en_mundo(r, world) for r in p["dependency_resolution"]
        ]) for p in packs]
    resumen = dict(payload["summary"])
    resumen.update({
        "packs_total": len(packs),
        "packs_analizados": sum(1 for p in packs if p["status"] == "ok"),
        "packs_behavior": sum(1 for p in packs if p["kind"] == "behavior"),
        "packs_resource": sum(1 for p in packs if p["kind"] == "resource"),
        "packs_compartidos": sum(1 for p in packs if p["origin"] == "compartido"),
        "packs_de_sistema": sum(1 for p in packs if p["origin"] == "sistema"),
        "packs_de_mundo": sum(1 for p in packs if p["origin"] == "mundo"),
        "mundos_total": len(worlds),
        "referencias_total": sum(len(w["references"]) for w in worlds),
        "referencias_resueltas": sum(
            1 for w in worlds for r in w["references"] if r["status"] == "resolved"),
        "referencias_sin_resolver": sum(
            1 for w in worlds for r in w["references"] if r["status"] == "unresolved"),
        "referencias_ambiguas": sum(
            1 for w in worlds for r in w["references"] if r["status"] == "ambiguous"),
        "referencias_tipo_cruzado": sum(
            1 for w in worlds for r in w["references"] if r["status"] == "kind_mismatch"),
        "referencias_sin_version": sum(
            1 for w in worlds for r in w["references"] if r["status"] == "version_unavailable"),
        "diagnosticos_total": len(diagnostics),
        "errores": sum(1 for d in diagnostics if d["severity"] == "error"),
        "avisos": sum(1 for d in diagnostics if d["severity"] == "aviso"),
        "informativos": sum(1 for d in diagnostics if d["severity"] == "info"),
    })
    filtrado = dict(payload)
    filtrado["filter"] = {"world": world, "kind": kind if kind in KINDS else None}
    filtrado["summary"] = resumen
    filtrado["summary_installation"] = payload["summary"]
    filtrado["packs"] = packs
    filtrado["worlds"] = worlds
    filtrado["diagnostics"] = diagnostics
    return filtrado


def _tipo_de_scope(scope):
    """Los refs usan 'behavior'; los packs 'mundo:<nombre>:behavior'."""
    if scope in KINDS:
        return scope
    partes = (scope or "").split(":")
    if ((len(partes) == 2 and partes[0] in ("compartido", "sistema"))
            or (len(partes) == 3 and partes[0] == "mundo")):
        return partes[-1] if partes[-1] in KINDS else None
    return None


def _resolucion_en_mundo(resolucion, world):
    contextos = resolucion.get("world_resolutions", [])
    contexto = next((r for r in contextos if r["world"] == world), None)
    if contexto is None:
        if any(r["world"] is not None for r in contextos):
            return dict(resolucion, status="unchecked", candidates=[], world_resolutions=[])
        return resolucion
    return dict(resolucion, status=contexto["status"], candidates=contexto["candidates"],
                world_resolutions=[contexto])


def catalogo_publico():
    """Catalogo de diagnosticos para la CLI (`--codes`) y la documentacion."""
    return [
        {
            "code": code,
            "severity": spec["severity"],
            "source": spec["source"],
            "partial": spec["partial"],
            "determined": spec["determined"],
            "message_es": spec["es"],
            "message_en": spec["en"],
        }
        for code, spec in sorted(CATALOGO.items())
    ]
