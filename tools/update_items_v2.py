import json
import os
import shutil
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

try:
    from console_lang import L
except ImportError:  # script copiado fuera del arbol del suite: mismo criterio que console_lang.L
    def L(es, en):
        return es if os.environ.get("WRAPPER_LANG") == "es" else en

try:
    import server_properties
except ImportError:  # script copiado fuera del arbol del suite: level-name por defecto
    server_properties = None


def write_text_atomic(path, text):
    """Escritura atomica (tmp + os.replace): un corte a mitad no trunca el
    archivo original (mismo patron que enable_beta_apis_v2.py; este script
    toca manifiestos de packs y del mundo, un truncado los rompe)."""
    tmp_path = path + ".tmp_" + os.urandom(4).hex()
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

# 1. Update main.js
main_js_content = """import { system, world } from "@minecraft/server";

// Evitar doble activación usando un Set de registro rápido de cooldown (milisegundos)
const cooldowns = new Set();

function isCoolingDown(entityId, type) {
    const key = `${entityId}_${type}`;
    if (cooldowns.has(key)) return true;
    cooldowns.add(key);
    system.runTimeout(() => {
        cooldowns.delete(key);
    }, 10); // 0.5 segundos (10 ticks) de cooldown
    return false;
}

// REGISTRO DE COMPONENTES PERSONALIZADOS (Custom Components)
// Esto hace que Minecraft registre nativamente el uso del ítem (haciendo clic derecho o pulsando L2 en consolas)
world.beforeEvents.worldInitialize.subscribe(({ itemComponentRegistry }) => {
    
    // A. ACTIVADOR DE GUARDIÁN
    itemComponentRegistry.registerCustomComponent("custom:guardian_activator_behavior", {
        onUseOn(event) {
            const player = event.source;
            const block = event.block;
            const itemStack = event.itemStack;
            
            if (!player || !block || !itemStack) return;
            if (isCoolingDown(player.id, "activator")) return;

            const spawnLoc = {
                x: block.location.x + 0.5,
                y: block.location.y + 1,
                z: block.location.z + 0.5
            };

            const dimension = player.dimension;
            
            try {
                const guardian = dimension.spawnEntity("custom:guardian_robot", spawnLoc);
                
                if (guardian) {
                    // Registrar ancla de patrulla
                    guardian.setDynamicProperty("anchorX", spawnLoc.x);
                    guardian.setDynamicProperty("anchorY", spawnLoc.y);
                    guardian.setDynamicProperty("anchorZ", spawnLoc.z);

                    // Partículas y sonido de invocación usando APIs nativas
                    dimension.spawnParticle("minecraft:villager_happy", { x: spawnLoc.x, y: spawnLoc.y + 1, z: spawnLoc.z });
                    dimension.playSound("mob.irongolem.death", spawnLoc, { volume: 0.8, pitch: 1.5 });

                    player.sendMessage("§a[Guardián Robótico] ¡Guardián activado con éxito! Zona de patrulla inicial fijada en esta posición.");

                    // Consumir 1 ítem del inventario del jugador
                    player.runCommand(`clear @s custom:guardian_activator 0 1`);
                }
            } catch (e) {
                player.sendMessage("§c[Error] No se pudo activar el Guardián aquí. Asegúrate de tener espacio suficiente.");
            }
        }
    });

    // B. CONTROLADOR DE GUARDIÁN (Guardar ubicación al hacer clic en bloque)
    itemComponentRegistry.registerCustomComponent("custom:guardian_controller_behavior", {
        onUseOn(event) {
            const player = event.source;
            const block = event.block;
            const itemStack = event.itemStack;
            
            if (!player || !block || !itemStack) return;
            if (isCoolingDown(player.id, "controller_block")) return;

            const loc = block.location;
            player.setDynamicProperty("saved_patrol_x", loc.x);
            player.setDynamicProperty("saved_patrol_y", loc.y + 1);
            player.setDynamicProperty("saved_patrol_z", loc.z);

            player.sendMessage(`§b[Control de Guardián] Coordenadas de patrulla guardadas: §f${Math.floor(loc.x)}, ${Math.floor(loc.y)}, ${Math.floor(loc.z)}§b. \\n§e¡Ahora interactúa (clic derecho / L2) con un Guardián para asignárselas!`);
            
            const dimension = player.dimension;
            dimension.spawnParticle("minecraft:basic_spark_particle", { x: loc.x + 0.5, y: loc.y + 1.2, z: loc.z + 0.5 });
            dimension.playSound("random.click", { x: loc.x + 0.5, y: loc.y + 0.5, z: loc.z + 0.5 }, { volume: 0.5, pitch: 1.5 });
        }
    });
});

// 2. ASIGNAR PATRULLA INTERACTUANDO CON EL GUARDIÁN
world.afterEvents.playerInteractWithEntity.subscribe((event) => {
    const player = event.player;
    const targetEntity = event.target;
    const itemStack = event.beforeItemStack;

    if (!player || !targetEntity || !itemStack) return;

    if (targetEntity.typeId === "custom:guardian_robot" && itemStack.typeId === "custom:guardian_controller") {
        if (isCoolingDown(player.id, "controller_entity")) return;

        const x = player.getDynamicProperty("saved_patrol_x");
        const y = player.getDynamicProperty("saved_patrol_y");
        const z = player.getDynamicProperty("saved_patrol_z");

        if (x === undefined || y === undefined || z === undefined) {
            const playerLoc = player.location;
            targetEntity.setDynamicProperty("anchorX", playerLoc.x);
            targetEntity.setDynamicProperty("anchorY", playerLoc.y);
            targetEntity.setDynamicProperty("anchorZ", playerLoc.z);

            player.sendMessage(`§a[Control de Guardián] ¡Zona de patrulla del Guardián establecida en tu posición actual: §f${Math.floor(playerLoc.x)}, ${Math.floor(playerLoc.y)}, ${Math.floor(playerLoc.z)}§a!`);
        } else {
            targetEntity.setDynamicProperty("anchorX", x);
            targetEntity.setDynamicProperty("anchorY", y);
            targetEntity.setDynamicProperty("anchorZ", z);

            player.sendMessage(`§a[Control de Guardián] ¡Zona de patrulla del Guardián establecida en: §f${Math.floor(x)}, ${Math.floor(y)}, ${Math.floor(z)}§a!`);
        }

        const dimension = targetEntity.dimension;
        const targetLoc = targetEntity.location;
        dimension.playSound("random.levelup", targetLoc, { volume: 0.8, pitch: 1.2 });
        dimension.spawnParticle("minecraft:villager_happy", { x: targetLoc.x, y: targetLoc.y + 2, z: targetLoc.z });
    }
});

// 3. BUCLE DE CONTROL Y PROTECCIÓN DE LOS GUARDIANES (Ejecutado cada 1 segundo / 20 ticks)
system.runInterval(() => {
    const overworld = world.getDimension("overworld");
    const nether = world.getDimension("nether");
    const theEnd = world.getDimension("the_end");
    const dimensions = [overworld, nether, theEnd];

    for (const dimension of dimensions) {
        const guardians = dimension.getEntities({ type: "custom:guardian_robot" });

        for (const guardian of guardians) {
            const loc = guardian.location;

            // A. INICIALIZAR O VERIFICAR ANCLA (Patrulla)
            let anchorX = guardian.getDynamicProperty("anchorX");
            let anchorY = guardian.getDynamicProperty("anchorY");
            let anchorZ = guardian.getDynamicProperty("anchorZ");

            if (anchorX === undefined || anchorY === undefined || anchorZ === undefined) {
                guardian.setDynamicProperty("anchorX", loc.x);
                guardian.setDynamicProperty("anchorY", loc.y);
                guardian.setDynamicProperty("anchorZ", loc.z);
                anchorX = loc.x;
                anchorY = loc.y;
                anchorZ = loc.z;
            }

            // Calcular distancia al ancla
            const dx = loc.x - anchorX;
            const dy = loc.y - anchorY;
            const dz = loc.z - anchorZ;
            const distance = Math.sqrt(dx*dx + dy*dy + dz*dz);
            const maxRadius = 15; // Radio máximo de deambulación para patrulla

            if (distance > maxRadius) {
                dimension.spawnParticle("minecraft:portal_directional", { x: loc.x, y: loc.y + 1, z: loc.z });
                dimension.playSound("mob.endermen.portal", loc, { volume: 0.5, pitch: 1.5 });
                
                guardian.teleport({ x: anchorX, y: anchorY, z: anchorZ });

                dimension.spawnParticle("minecraft:portal_directional", { x: anchorX, y: anchorY + 1, z: anchorZ });
            }

            // B. COMBATE TÁCTICO CONTRA CREEPERS (Minimizar daños)
            const creepers = dimension.getEntities({
                location: loc,
                maxDistance: 10,
                type: "minecraft:creeper"
            });

            for (const creeper of creepers) {
                const cLoc = creeper.location;

                // 1. Mostrar un "Rayo Láser" desintegrador rojo
                const steps = 6;
                for (let i = 0; i <= steps; i++) {
                    const t = i / steps;
                    const px = (loc.x) + (cLoc.x - loc.x) * t;
                    const py = (loc.y + 2) + (cLoc.y + 1 - (loc.y + 2)) * t;
                    const pz = (loc.z) + (cLoc.z - loc.z) * t;
                    dimension.spawnParticle("minecraft:redstone_ore_dust_particle", { x: px, y: py, z: pz });
                }

                dimension.playSound("random.orb", cLoc, { volume: 0.7, pitch: 1.8 });

                creeper.kill();

                dimension.spawnParticle("minecraft:basic_smoke_particle", { x: cLoc.x, y: cLoc.y + 1, z: cLoc.z });
                
                const nearbyPlayers = dimension.getPlayers({ location: loc, maxDistance: 20 });
                for (const p of nearbyPlayers) {
                    p.sendMessage("§9[Guardián Robótico] ¡Creeper desintegrado de forma segura! ⚡");
                }
            }
        }
    }
}, 20);
"""

# 2. Update item JSONs to declare the custom components
MAX_RESPALDOS = 3


def _respaldo(path):
    """Respaldo previo del archivo que se va a reescribir.

    Si falla se aborta sin tocar el original (mismo criterio que
    enable_beta_apis_v2). El sufijo no es .bak_: el recuperador de
    restauraciones interrumpidas renombra *.bak_* de worlds/ como huerfano.
    Se conservan los MAX_RESPALDOS mas recientes de ESE archivo (los de
    worlds/ entran en cada backup del mundo) y nunca el recien creado.
    """
    respaldo = path + ".respaldo_" + datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + os.urandom(2).hex()
    shutil.copyfile(path, respaldo)
    carpeta, prefijo = os.path.dirname(path), os.path.basename(path) + ".respaldo_"
    viejos = []
    for nombre in os.listdir(carpeta):
        ruta = os.path.join(carpeta, nombre)
        if nombre.startswith(prefijo) and ruta != respaldo:
            try:
                viejos.append((os.path.getmtime(ruta), ruta))
            except OSError:
                continue
    for _mtime, ruta in sorted(viejos, reverse=True)[MAX_RESPALDOS - 1:]:
        try:
            os.remove(ruta)
        except OSError:
            pass
    return respaldo


def update_json_file(file_path, modify_func):
    """Valida, respalda y reescribe un JSON con modify_func (escritura atomica).

    Devuelve False si no se pudo actualizar (explicado por consola, sin
    traceback); un archivo que no existe solo avisa y no cuenta como fallo.
    """
    if not os.path.exists(file_path):
        print(L(f"[AVISO] No se encontró el archivo: {file_path}",
                f"[WARNING] File not found: {file_path}"))
        return True
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(L(f"[ERROR] JSON ilegible en {file_path}: {e}",
                f"[ERROR] Unreadable JSON in {file_path}: {e}"))
        return False
    try:
        modify_func(data)
    except (KeyError, TypeError) as e:
        print(L(f"[ERROR] Estructura inesperada en {file_path} (falta {e!r}); queda sin modificar.",
                f"[ERROR] Unexpected structure in {file_path} (missing {e!r}); left unchanged."))
        return False
    try:
        respaldo = _respaldo(file_path)
    except OSError as e:
        print(L(f"[ERROR] No se pudo crear el respaldo de {file_path} ({e}); queda sin modificar.",
                f"[ERROR] Could not back up {file_path} ({e}); left unchanged."))
        return False
    write_text_atomic(file_path, json.dumps(data, indent=2, ensure_ascii=False))
    print(L(f"Actualizado {file_path} (respaldo: {os.path.basename(respaldo)})",
            f"Updated {file_path} (backup: {os.path.basename(respaldo)})"))
    return True

def _quitar_animacion_de_uso(components):
    """Paso de la 1.0.5 (antes en update_items.py, ahora un alias de este
    script): sin esto, ir de 1.0.4 a 1.0.6 con la v2 dejaba esos componentes."""
    components.pop("minecraft:use_animation", None)
    components.pop("minecraft:use_modifiers", None)


def modify_activator(data):
    components = data["minecraft:item"]["components"]
    _quitar_animacion_de_uso(components)
    components["minecraft:custom_components"] = ["custom:guardian_activator_behavior"]

def modify_controller(data):
    components = data["minecraft:item"]["components"]
    _quitar_animacion_de_uso(components)
    components["minecraft:custom_components"] = ["custom:guardian_controller_behavior"]

# 3. Modify BP Manifest
def modify_bp_manifest(data):
    data["header"]["version"] = [1, 0, 6]
    for module in data.get("modules", []):
        if module["type"] == "script":
            module["version"] = [1, 0, 6]
    for dep in data.get("dependencies", []):
        if dep.get("uuid") == "9f075d4a-bc12-4c2c-8d14-6fa6b12a2b74":
            dep["version"] = [1, 0, 6]

# 4. Modify RP Manifest
def modify_rp_manifest(data):
    data["header"]["version"] = [1, 0, 6]
    for module in data.get("modules", []):
        if module["type"] == "resources":
            module["version"] = [1, 0, 6]

# 5. Modify World JSONs
def modify_world_bp(data):
    for pack in data:
        if pack["pack_id"] == "8f075d4a-bc12-4c2c-8d14-6fa6b12a2b72":
            pack["version"] = [1, 0, 6]

def modify_world_rp(data):
    for pack in data:
        if pack["pack_id"] == "9f075d4a-bc12-4c2c-8d14-6fa6b12a2b74":
            pack["version"] = [1, 0, 6]


def _ruta_mundo():
    """Carpeta del mundo segun level-name de server.properties (default de BDS)."""
    nombre = "Bedrock level"
    if server_properties is not None:
        nombre = server_properties.read_value(
            os.path.join(BASE_DIR, "server.properties"), "level-name", nombre) or nombre
    return os.path.join(BASE_DIR, "worlds", nombre)


def _actualizar_main_js(ruta):
    """Reescribe scripts/main.js con respaldo previo; False si no se pudo.

    Antes se sobrescribia sin respaldo (se perdian cambios hechos a mano) y,
    sin la carpeta scripts/, moria con FileNotFoundError (2026-10-21).
    """
    if not os.path.isdir(os.path.dirname(ruta)):
        print(L(f"[ERROR] No existe {os.path.dirname(ruta)}; main.js queda sin modificar.",
                f"[ERROR] {os.path.dirname(ruta)} does not exist; main.js left unchanged."))
        return False
    if os.path.exists(ruta):
        try:
            with open(ruta, encoding="utf-8") as f:
                if f.read() == main_js_content:
                    print(L("main.js ya estaba actualizado", "main.js was already up to date"))
                    return True
            respaldo = _respaldo(ruta)
        except (OSError, UnicodeDecodeError) as e:
            print(L(f"[ERROR] No se pudo respaldar {ruta} ({e}); queda sin modificar.",
                    f"[ERROR] Could not back up {ruta} ({e}); left unchanged."))
            return False
        print(L(f"Respaldo de main.js: {os.path.basename(respaldo)}", f"main.js backup: {os.path.basename(respaldo)}"))
    write_text_atomic(ruta, main_js_content)
    print(L("Actualizado main.js", "Updated main.js"))
    return True


def main():
    """Aplica las modificaciones (solo al ejecutar como script).

    Antes este modulo escribia packs/mundo al importarlo; ahora importar
    es inocuo y el trabajo vive aqui. Devuelve 0 si todo se aplico.
    """
    pack = os.path.join(BASE_DIR, "behavior_packs", "guardian_robot_BP")
    if not os.path.isdir(pack):
        print(L(f"[ERROR] No se encontró el addon guardian_robot_BP en {os.path.dirname(pack)}; no se modificó nada.",
                f"[ERROR] The guardian_robot_BP add-on was not found in {os.path.dirname(pack)}; nothing was changed."))
        return 1
    if not _actualizar_main_js(os.path.join(pack, "scripts", "main.js")):
        return 1
    mundo = _ruta_mundo()
    trabajos = [
        (os.path.join(BASE_DIR, "behavior_packs/guardian_robot_BP/items/guardian_activator.json"), modify_activator),
        (os.path.join(BASE_DIR, "behavior_packs/guardian_robot_BP/items/guardian_controller.json"), modify_controller),
        (os.path.join(BASE_DIR, "behavior_packs/guardian_robot_BP/manifest.json"), modify_bp_manifest),
        (os.path.join(BASE_DIR, "resource_packs/guardian_robot_RP/manifest.json"), modify_rp_manifest),
    ]
    if os.path.isdir(mundo):
        trabajos.append((os.path.join(mundo, "world_behavior_packs.json"), modify_world_bp))
        trabajos.append((os.path.join(mundo, "world_resource_packs.json"), modify_world_rp))
    else:
        print(L(f"[AVISO] El mundo {mundo} no existe (level-name de server.properties); no se tocaron sus packs.",
                f"[WARNING] World {mundo} does not exist (level-name from server.properties); its packs were not touched."))
    fallos = 0
    for ruta, modificador in trabajos:
        if not update_json_file(ruta, modificador):
            fallos += 1
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
