import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

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

with open(os.path.join(BASE_DIR, "behavior_packs/guardian_robot_BP/scripts/main.js"), "w", encoding="utf-8") as f:
    f.write(main_js_content)
print("Updated main.js")

# 2. Update item JSONs to declare the custom components
def update_json_file(file_path, modify_func):
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    modify_func(data)
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Updated {file_path}")

def modify_activator(data):
    components = data["minecraft:item"]["components"]
    components["minecraft:custom_components"] = ["custom:guardian_activator_behavior"]

def modify_controller(data):
    components = data["minecraft:item"]["components"]
    components["minecraft:custom_components"] = ["custom:guardian_controller_behavior"]

update_json_file(os.path.join(BASE_DIR, "behavior_packs/guardian_robot_BP/items/guardian_activator.json"), modify_activator)
update_json_file(os.path.join(BASE_DIR, "behavior_packs/guardian_robot_BP/items/guardian_controller.json"), modify_controller)

# 3. Modify BP Manifest
def modify_bp_manifest(data):
    data["header"]["version"] = [1, 0, 6]
    for module in data.get("modules", []):
        if module["type"] == "script":
            module["version"] = [1, 0, 6]
    for dep in data.get("dependencies", []):
        if dep.get("uuid") == "9f075d4a-bc12-4c2c-8d14-6fa6b12a2b74":
            dep["version"] = [1, 0, 6]

update_json_file(os.path.join(BASE_DIR, "behavior_packs/guardian_robot_BP/manifest.json"), modify_bp_manifest)

# 4. Modify RP Manifest
def modify_rp_manifest(data):
    data["header"]["version"] = [1, 0, 6]
    for module in data.get("modules", []):
        if module["type"] == "resources":
            module["version"] = [1, 0, 6]

update_json_file(os.path.join(BASE_DIR, "resource_packs/guardian_robot_RP/manifest.json"), modify_rp_manifest)

# 5. Modify World JSONs
def modify_world_bp(data):
    for pack in data:
        if pack["pack_id"] == "8f075d4a-bc12-4c2c-8d14-6fa6b12a2b72":
            pack["version"] = [1, 0, 6]

update_json_file(os.path.join(BASE_DIR, "worlds/Bedrock level/world_behavior_packs.json"), modify_world_bp)

def modify_world_rp(data):
    for pack in data:
        if pack["pack_id"] == "9f075d4a-bc12-4c2c-8d14-6fa6b12a2b74":
            pack["version"] = [1, 0, 6]

update_json_file(os.path.join(BASE_DIR, "worlds/Bedrock level/world_resource_packs.json"), modify_world_rp)
