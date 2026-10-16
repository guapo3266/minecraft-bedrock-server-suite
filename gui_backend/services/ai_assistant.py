"""
ai_assistant.py — Servicio de Asistente IA para traducción a comandos Bedrock
=============================================================================
Conecta con LM Studio local (FunctionGemma / GGUF), traduce peticiones en
lenguaje natural a llamadas de función estructuradas, auto-resuelve objetivos
cuando hay un único jugador online y convierte la llamada a comandos válidos de
Minecraft Bedrock con advertencias contextuales (p. ej. límites de stack).
"""

import json
import os
import random
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

import requests

LMSTUDIO_DEFAULT_URL = os.getenv("LMSTUDIO_URL", "http://127.0.0.1:1234/v1")
# El primer prefill de Qwen3 Q8 en CPU puede superar 15 s, aun con top-4.
# 45 s evita marcar un modelo sano como caído; las respuestas calientes son mucho más rápidas.
HTTP_TIMEOUT_SECONDS = 45.0
HEALTH_TIMEOUT_SECONDS = 3.0

SYSTEM_PROMPT = (
    "Eres el asistente del servidor Minecraft Bedrock. "
    "Tu función es traducir instrucciones en lenguaje natural a llamadas de "
    "función estructuradas para ejecutar comandos en el servidor."
)

BEDROCK_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "teleport",
            "description": "Teletransporta un jugador hacia otro jugador o a coordenadas específicas en el mundo de Minecraft Bedrock.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "Jugador a teletransportar (ej. 'steva', '@a', '@p', '@r')."
                    },
                    "destination": {
                        "type": "string",
                        "description": "Destino: nombre de otro jugador o coordenadas X Y Z (ej. 'juan', '100 64 -200', '~ ~10 ~')."
                    }
                },
                "required": ["target", "destination"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "give_item",
            "description": "Entrega items o bloques a un jugador específico en Minecraft Bedrock.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "Jugador destinatario (ej. 'steva', '@p', '@a', '@r')."
                    },
                    "item": {
                        "type": "string",
                        "description": "Identificador Bedrock del item (ej. 'diamond', 'netherite_sword', 'bread')."
                    },
                    "amount": {
                        "type": "integer",
                        "description": "Cantidad de unidades a entregar."
                    }
                },
                "required": ["target", "item"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_time",
            "description": "Cambia la hora o momento del día del mundo en el servidor.",
            "parameters": {
                "type": "object",
                "properties": {
                    "time_value": {
                        "type": "string",
                        "description": "Momento del día ('day', 'night', 'noon', 'midnight', 'sunrise', 'sunset') o número de ticks."
                    }
                },
                "required": ["time_value"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_weather",
            "description": "Modifica el clima atmosférico en el servidor de Minecraft Bedrock.",
            "parameters": {
                "type": "object",
                "properties": {
                    "weather_type": {
                        "type": "string",
                        "description": "Tipo de clima deseado.",
                        "enum": ["clear", "rain", "thunder"]
                    },
                    "duration": {
                        "type": "integer",
                        "description": "Duración opcional en segundos."
                    }
                },
                "required": ["weather_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_gamemode",
            "description": "Cambia el modo de juego de un jugador o de todos.",
            "parameters": {
                "type": "object",
                "properties": {
                    "gamemode": {
                        "type": "string",
                        "description": "Modo de juego.",
                        "enum": ["survival", "creative", "adventure", "spectator"]
                    },
                    "target": {
                        "type": "string",
                        "description": "Jugador objetivo (ej. 'juan', '@p', '@a')."
                    }
                },
                "required": ["gamemode"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "apply_effect",
            "description": "Aplica o remueve efectos de poción / estado a un jugador.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "Jugador al que aplicar el efecto."
                    },
                    "effect": {
                        "type": "string",
                        "description": "Nombre del efecto (ej. 'speed', 'night_vision', 'regeneration', 'clear')."
                    },
                    "seconds": {
                        "type": "integer",
                        "description": "Duración del efecto en segundos."
                    },
                    "amplifier": {
                        "type": "integer",
                        "description": "Amplificador Bedrock (0-255): nivel humano N equivale a N-1; nivel 1 = 0. Si no se pide nivel, omite este argumento.",
                        "minimum": 0,
                        "maximum": 255
                    }
                },
                "required": ["target", "effect"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "manage_player",
            "description": "Acciones de administración sobre jugadores: expulsar, dar/quitar operador o eliminar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Acción a realizar.",
                        "enum": ["kick", "op", "deop", "kill"]
                    },
                    "target": {
                        "type": "string",
                        "description": "Jugador objetivo."
                    },
                    "reason": {
                        "type": "string",
                        "description": "Motivo opcional (para expulsiones)."
                    }
                },
                "required": ["action", "target"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_gamerule",
            "description": "Ajusta las reglas de juego del servidor (gamerules).",
            "parameters": {
                "type": "object",
                "properties": {
                    "rule": {
                        "type": "string",
                        "description": "Regla de juego a modificar (ej. 'keepinventory', 'dodaylightcycle', 'pvp')."
                    },
                    "value": {
                        "type": "boolean",
                        "description": "Valor booleano true o false."
                    }
                },
                "required": ["rule", "value"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "summon_entity",
            "description": "Invoca o hace aparecer una entidad o criatura en el mundo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity": {
                        "type": "string",
                        "description": "Tipo de entidad Bedrock (ej. 'zombie', 'creeper', 'cow', 'tnt')."
                    },
                    "target_or_coords": {
                        "type": "string",
                        "description": "Coordenadas opcionales X Y Z (ej. '100 64 -200' o '~ ~1 ~'). No acepta nombres ni selectores de jugadores."
                    }
                },
                "required": ["entity"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "clear_inventory",
            "description": "Limpia o remueve items específicos del inventario de un jugador.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "Jugador objetivo (ej. 'steva', '@p', '@a')."
                    },
                    "item": {
                        "type": "string",
                        "description": "Item específico a remover (ej. 'diamond', 'dirt'). Si se omite, limpia todo el inventario."
                    },
                    "max_count": {
                        "type": "integer",
                        "description": "Cantidad máxima de items a remover. Si se omite, remueve todos."
                    }
                },
                "required": ["target"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "send_message",
            "description": "Envía un mensaje al chat del servidor (público) o un mensaje privado a un jugador.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Texto del mensaje a enviar."
                    },
                    "target": {
                        "type": "string",
                        "description": "Jugador destinatario para mensaje privado. Si se omite, se envía como mensaje público del servidor."
                    },
                    "type": {
                        "type": "string",
                        "description": "Tipo de mensaje.",
                        "enum": ["broadcast", "private"]
                    }
                },
                "required": ["message"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "manage_allowlist",
            "description": "Gestiona la lista blanca (allowlist) del servidor: agregar, quitar jugadores o activar/desactivar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Acción a realizar.",
                        "enum": ["add", "remove", "on", "off", "list"]
                    },
                    "target": {
                        "type": "string",
                        "description": "Jugador a agregar o quitar (requerido para add/remove)."
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "manage_experience",
            "description": "Otorga, quita o consulta la experiencia de un jugador.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "Jugador objetivo (ej. 'steva', '@p')."
                    },
                    "amount": {
                        "type": "integer",
                        "description": "Cantidad de experiencia (positiva para dar, negativa para quitar). Solo negativo si unit es 'levels'."
                    },
                    "unit": {
                        "type": "string",
                        "description": "Unidad de experiencia.",
                        "enum": ["points", "levels"]
                    }
                },
                "required": ["target", "amount"]
            }
        }
    }
]

DEFAULT_CANONICAL_TOOL_NAMES: Tuple[str, ...] = (
    "teleport",
    "give_item",
    "set_time",
    "send_message",
)
_TOOLS_BY_NAME: Dict[str, Dict[str, Any]] = {
    tool.get("function", {}).get("name", ""): tool for tool in BEDROCK_TOOLS
}
DEFAULT_CANONICAL_TOOLS: List[Dict[str, Any]] = [
    _TOOLS_BY_NAME[name] for name in DEFAULT_CANONICAL_TOOL_NAMES if name in _TOOLS_BY_NAME
]

SELF_TARGETS = {"@p", "@s", "a mí", "a mi", "me", "yo", "self", "sender", ""}
SELF_PROMPT_TRIGGERS = [
    r"\ba m[íi]\b",
    r"\bdame\b",
    r"\btraeme\b",
    r"\btr[áa]eme\b",
    r"\bll[ée]vame\b",
    r"\bponme\b",
    r"\bhazme\b",
    r"\bhacia m[íi]\b",
    r"\bconmigo\b",
    r"\bteletransp[óo]rtame\b",
    r"\bqu[íi]tame\b",
    r"\bp[áa]same\b",
    r"\bentr[ée]game\b",
    r"\breg[áa]lame\b",
    r"\bnecesito\b",
    r"\bquiero\b",
    r"\bdropeame\b",
    r"\bsoltame\b",
    r"\bcons[íi]gueme\b",
    r"\b[ée]chame\b",
    r"\bgive me\b",
    r"\bagr[ée]game\b",
    r"\bm[ée]teme\b",
    r"\ba[ñn][aá]deme\b",
]

# Pre-filtro de herramientas por intencion (ahorra ~4x tokens de prefill en CPU).
# El modelo v3 entrenó con 1 tool verdadera + 3 distractores: inferir con 4 se acerca
# a su distribucion de entreno y evita el mega-schema de 13. Los errores son
# asimetricos: incluir de mas solo cuesta tokens; excluir la verdadera es fatal,
# asi que las listas son generosas (con/sin acento, el regex no los unifica)
# y sin hits se devuelven las 13.
TOOL_KEYWORDS = {
    "teleport": (
        "teletransporta", "teletransporte", "teletranspórtame", "teletransportame",
        "teletransportar", "trae", "traeme", "tráeme", "lleva", "llévame", "llevame",
        "tpea", "tpeá", "tpeame", "tp", "mueve", "múeveme", "mueveme", "mover",
        "jala", "reúne", "reune", "posición", "posicion", "coordenadas",
        "hacia mi", "hacia mí", "junto a",
    ),
    "give_item": (
        "dame", "dale", "dales", "danos", "entrega", "entrégame", "entregame", "entrégale", "entregale",
        "regala", "regálame", "regalame", "regálale", "regalale",
        "necesito", "pásame", "pasame", "pásale", "pasale", "dropea", "soltame", "suéltame", "sueltame",
        "consígueme", "consigueme", "consigue", "añade", "anade", "suministra",
        "échame", "echame", "echa", "stack", "stacks", "toma", "otorga", "quiero",
    ),
    "set_time": (
        "día", "dia", "noche", "mañana", "manana", "mediodía", "mediodia",
        "medianoche", "amanecer", "amanece", "atardecer", "atardece", "anochece", "anochezca",
        "puesta de sol", "puesta del sol", "salida del sol", "hora", "ticks", "time set", "haz de",
    ),
    "set_weather": (
        "lluvia", "llueve", "llover", "llueva", "clima", "soleado",
        "despejado", "despeja", "tormenta", "rayos", "truenos", "weather",
        "cielo", "nublado",
    ),
    "set_gamemode": (
        "creativo", "supervivencia", "survival", "aventura", "espectador",
        "gamemode", "game mode", "modo",
    ),
    "apply_effect": (
        "efecto", "efectos", "poción", "pocion", "pociones", "buff", "buffs", "debuff", "debuffs",
        "aplica", "aplique", "aplicar", "aplicale", "aplícale",
        "visión", "vision", "nocturna", "visión nocturna", "vision nocturna",
        "velocidad", "speed", "lentitud", "slowness",
        "resistencia", "resistance", "fuerza", "strength", "debilidad", "weakness",
        "invisibilidad", "invisibility", "invisible",
        "regeneración", "regeneracion", "regeneration", "curación", "curacion",
        "salto", "super salto", "súper salto", "salto elevado", "jump boost",
        "veneno", "poison", "veneno fatal", "fatal poison",
        "náusea", "nausea", "ceguera", "blindness", "oscuridad", "darkness",
        "hambre", "hunger", "saturación", "saturacion", "saturation",
        "levitación", "levitacion", "levitation", "caída lenta", "caida lenta", "slow falling",
        "prisa", "haste", "fatiga", "mining fatigue",
        "absorción", "absorcion", "absorption",
        "vida instantánea", "vida instantanea", "instant health",
        "respiración acuática", "respiracion acuatica", "water breathing",
        "brillo", "glowing", "mal presagio", "bad omen", "héroe de la aldea", "heroe de la aldea",
        "wither", "descomposición", "descomposicion",
    ),
    "manage_player": (
        "expulsa", "kickea", "kick", "saca", "echa", "bota",
        "desconecta", "operador", "administrador", "admin", "deop", "mata",
        "elimina", "ejecuta", "kill", "revoca", "permisos",
    ),
    "set_gamerule": (
        "gamerule", "keepinventory", "keep inventory", "conservar inventario", "pvp",
        "ciclo", "solar", "ciclo de día y noche", "ciclo de dia y noche", "insomnio", "fuego amigo",
        "inventario", "respawn", "reaparición", "reaparicion", "drop", "drops", "dropeo", "reglas",
        "daño por caída", "daños por caída", "daño por caida", "daños por caida", "falldamage",
        "monstruos", "aparezcan monstruos", "aparición de monstruos", "aparicion de monstruos",
        "domobspawning", "random tick speed", "randomtickspeed", "tick speed",
        "explosiones de tnt", "explosión de tnt", "tntexplodes", "daño de fuego", "firedamage",
    ),
    "summon_entity": (
        "spawnea", "spawnear", "spawn", "invoca", "invocar", "aparece", "aparecer",
        "aparezca", "genera", "generar", "crea", "crear", "suelta", "summon",
    ),
    "clear_inventory": (
        "vacía", "vacia", "vaciar", "limpia", "limpiar", "borra", "borrar",
        "purga", "purgar", "quítame", "quitame", "quítale", "quitale", "remueve", "remover",
        "sácame", "sacame", "sácale", "sacale", "elimina", "eliminar", "inventario", "deshazte",
    ),
    "send_message": (
        "di", "dile", "diles", "anuncia", "anuncio", "avisa", "avísale", "avisale",
        "escribe", "escríbele", "escribele", "mensaje", "chat", "broadcast",
        "susurra", "whisper", "notifica", "notifícale", "notificale",
        "comunicado", "tell",
    ),
    "manage_allowlist": (
        "whitelist", "allowlist", "lista blanca", "acceso", "entrada",
        "autorizado", "autorizados", "permite", "permitir",
    ),
    "manage_experience": (
        "experiencia", "xp", "nivel", "niveles", "puntos", "exp",
    ),
}


def select_tools(prompt: Optional[str], top_n: Optional[int] = 4) -> List[Dict[str, Any]]:
    """Filtra BEDROCK_TOOLS a las `top_n` herramientas según pesos e intención contextual."""
    return _select_tools_impl(prompt, top_n=top_n)


# Tokens que FunctionGemma emite para campos opcionales vacíos (p. ej.
# `target_or_coords:None,type:None`). Se normalizan a None para no generar
# comandos rotos como `summon wither None`.
MISSING_TOKENS = {"none", "null", "nil", "undefined", "nan"}

# Catálogos Bedrock en memoria (extraídos de generate_dataset.py: ITEMS_DB, MOBS_DB,
# EFFECTS y GAMERULES_DATA + reglas enteras del backend). Todo identificador fuera de
# estos conjuntos genera WARNING explícito en vez de basura silenciosa en consola.
BEDROCK_GAMERULES = frozenset({
    "commandblockoutput", "commandblocksenabled", "dodaylightcycle", "dofiretick",
    "doimmediaterespawn", "doinsomnia", "domobloot", "domobspawning", "dotiledrops",
    "doweathercycle", "drowningdamage", "falldamage", "firedamage", "freezedamage",
    "keepinventory", "mobgriefing", "naturalregeneration", "pvp", "recipesunlock",
    "respawnblocksexplode", "sendcommandfeedback", "showcoordinates", "showdeathmessages",
    "tntexplodes",
    "randomtickspeed", "spawnradius", "maxcommandchainlength", "functioncommandlimit",
    "playerssleepingpercentage",
})
BEDROCK_WEATHER = frozenset({"clear", "rain", "thunder"})
BEDROCK_GAMEMODES = frozenset({"survival", "creative", "adventure", "spectator"})
BEDROCK_EFFECTS = frozenset({
    "absorption", "bad_omen", "blindness", "clear", "conduit_power", "darkness",
    "fatal_poison", "fire_resistance", "haste", "health_boost", "hero_of_the_village",
    "hunger", "instant_damage", "instant_health", "invisibility", "jump_boost", "village_hero",
    "levitation", "mining_fatigue", "nausea", "night_vision", "poison", "regeneration",
    "resistance", "saturation", "slow_falling", "slowness", "speed", "strength",
    "water_breathing", "weakness", "wither",
})
BEDROCK_PLAYER_ACTIONS = frozenset({"kick", "op", "deop", "kill"})
BEDROCK_ALLOWLIST_ACTIONS = frozenset({"add", "remove", "on", "off", "list"})
BEDROCK_ITEMS = frozenset({
    "amethyst_shard", "ancient_debris", "anvil", "apple", "arrow", "baked_potato",
    "barrel", "basalt", "beacon", "bed", "beef", "birch_log", "blackstone",
    "blast_furnace", "blue_ice", "book", "bow", "bread", "brewing_stand",
    "brick_block", "bucket", "cake", "campfire", "carrot", "cauldron",
    "chainmail_chestplate", "charcoal", "cherry_log", "chest", "chicken", "clay",
    "clock", "coal", "coal_block", "cobblestone", "command_block", "comparator",
    "compass", "cooked_beef", "cooked_chicken", "cooked_mutton", "cooked_porkchop",
    "cooked_salmon", "cookie", "copper_ingot", "cow_spawn_egg", "crafting_table",
    "creeper_spawn_egg", "crossbow", "crying_obsidian", "daylight_detector",
    "deepslate", "diamond", "diamond_axe", "diamond_block", "diamond_boots",
    "diamond_chestplate", "diamond_helmet", "diamond_hoe", "diamond_leggings",
    "diamond_pickaxe", "diamond_shovel", "diamond_sword", "dirt", "dispenser",
    "dropper", "echo_shard", "elytra", "emerald", "emerald_block", "empty_map",
    "enchanted_book", "enchanted_golden_apple", "enchanting_table", "end_stone",
    "ender_chest", "ender_eye", "ender_pearl", "experience_bottle", "firework_rocket",
    "fishing_rod", "flint_and_steel", "furnace", "glass", "glow_berries", "glowstone",
    "gold_block", "gold_ingot", "golden_apple", "golden_carrot", "golden_pickaxe",
    "golden_sword", "gravel", "honey_block", "honey_bottle", "hopper", "ice",
    "iron_axe", "iron_block", "iron_boots", "iron_chestplate", "iron_golem_spawn_egg",
    "iron_helmet", "iron_ingot", "iron_leggings", "iron_pickaxe", "iron_shovel",
    "iron_sword", "lantern", "lapis_lazuli", "lava_bucket", "lead",
    "leather_chestplate", "lever", "map", "melon_slice", "milk_bucket",
    "mossy_cobblestone", "name_tag", "netherite_axe", "netherite_block",
    "netherite_boots", "netherite_chestplate", "netherite_helmet", "netherite_hoe",
    "netherite_ingot", "netherite_leggings", "netherite_pickaxe", "netherite_scrap",
    "netherite_shovel", "netherite_sword", "netherrack", "oak_log", "oak_planks",
    "observer", "obsidian", "piston", "planks", "porkchop", "potato", "potion",
    "powder_snow_bucket", "prismarine", "purpur_block", "quartz", "rail",
    "raw_copper", "raw_gold", "raw_iron", "red_sand", "redstone", "redstone_block",
    "redstone_torch", "repeater", "respawn_anchor", "saddle", "sand", "sea_lantern",
    "shears", "shield", "shulker_box", "skeleton_spawn_egg", "slime", "smoker",
    "smooth_stone", "snow", "soul_lantern", "soul_torch", "sponge", "spruce_log",
    "spyglass", "sticky_piston", "stone", "stone_axe", "stone_bricks", "stone_pickaxe",
    "stone_sword", "sweet_berries", "target", "terracotta", "hardened_clay", "tinted_glass", "tnt",
    "torch", "totem_of_undying", "trapped_chest", "trident", "turtle_helmet",
    "villager_spawn_egg", "water_bucket", "wooden_axe", "wooden_pickaxe",
    "wooden_sword", "wool", "zombie_spawn_egg",
})
BEDROCK_ENTITIES = frozenset({
    "allay", "armadillo", "armor_stand", "axolotl", "bat", "bee", "blaze", "boat",
    "bogged", "breeze", "camel", "cat", "cave_spider", "chicken", "cow", "creeper",
    "dolphin", "donkey", "drowned", "elder_guardian", "ender_dragon", "enderman",
    "evoker", "evocation_illager", "fox", "frog", "ghast", "glow_squid", "guardian", "hoglin", "horse",
    "husk", "iron_golem", "lightning_bolt", "llama", "magma_cube", "minecart",
    "mule", "panda", "parrot", "phantom", "pig", "piglin", "piglin_brute", "pillager",
    "polar_bear", "rabbit", "ravager", "sheep", "shulker", "silverfish", "skeleton",
    "slime", "sniffer", "snow_golem", "spider", "squid", "stray", "tnt", "turtle",
    "vex", "villager", "vindicator", "wandering_trader", "warden", "witch", "wither",
    "wither_skeleton", "wolf", "zombie", "zombified_piglin", "zombie_pigman",
})

# -----------------------------------------------------------------------------
# Router de herramientas: pesos, exclusiones, combinaciones léxicas e inhibición
# -----------------------------------------------------------------------------

_EFFECT_NAMES = ({
    "velocidad", "speed", "lentitud", "slowness",
    "resistencia", "resistance", "resistencia al fuego", "fire resistance",
    "fuerza", "strength", "debilidad", "weakness",
    "invisibilidad", "invisible", "invisibility",
    "vision nocturna", "visión nocturna", "night vision", "vision", "visión", "nocturna",
    "regeneracion", "regeneración", "regeneration",
    "salto", "super salto", "súper salto", "salto elevado", "jump boost",
    "nausea", "náusea", "veneno", "poison", "veneno fatal", "fatal poison",
    "wither", "descomposicion", "descomposición",
    "ceguera", "blindness", "oscuridad", "darkness",
    "hambre", "hunger", "saturacion", "saturación", "saturation",
    "levitacion", "levitación", "levitation", "caida lenta", "caída lenta", "slow falling",
    "prisa", "prisa minera", "haste", "fatiga", "fatiga minera", "mining fatigue",
    "absorcion", "absorción", "absorption",
    "curacion", "curación", "vida instantanea", "vida instantánea", "instant health",
    "dano instantaneo", "daño instantáneo", "instant damage",
    "respiracion acuatica", "respiración acuática", "water breathing",
    "brillo", "glowing", "mal presagio", "bad omen", "heroe de la aldea", "héroe de la aldea",
    "conducto", "conduit power", "gracia del delfin", "gracia del delfín",
    "supersalto", "vida extra", "respiracion bajo el agua", "respiración bajo el agua",
} | set(BEDROCK_EFFECTS)) - {"clear"}

_EFFECT_TERMS = {
    "efecto", "efectos", "pocion", "poción", "pociones", "buff", "buffs", "debuff", "debuffs",
    "aplica", "aplique", "aplicar", "aplicale", "aplícale",
}

_REMOVAL_VERBS = {
    "clear",
    "elimina", "eliminar", "eliminame", "elimíname", "eliminale", "elimínale",
    "vacia", "vacía", "vaciar", "vaciame", "vacíame", "vaciale", "vacíale",
    "limpia", "limpiar", "limpiame", "límpiame", "limpiale", "límpiale",
    "borra", "borrar", "borrame", "bórrame", "borrale", "bórrale",
    "remueve", "remover", "remueveme", "remuéveme", "remuevele", "remuévele",
    "quitame", "quítame", "quitale", "quítale", "quita", "quitar",
    "purga", "purgar", "sacame", "sácame", "sacale", "sácale", "deshazte", "tira",
}

_SPANISH_ITEMS = {
    "diamante", "diamantes", "tierra", "antorcha", "antorchas", "madera", "roble",
    "piedra", "obsidiana", "hierro", "oro", "esmeralda", "esmeraldas", "cubeta", "cubetas",
    "cubetas de agua", "cubeta de agua", "arco", "flecha", "flechas", "espada",
    "manzana", "manzanas", "manzanas doradas", "manzana dorada",
    "zanahoria", "zanahorias", "pan", "armadura", "pico", "hacha", "pala",
    "pocion", "poción", "pociones", "botella", "botellas", "frasco", "frascos",
    "comida", "carne", "lingote", "lingotes", "casco", "pechera", "pantalones", "botas",
}

_ITEM_TERMS = (
    {"inventario", "inventarios", "objeto", "objetos", "item", "items", "ítem", "ítems",
     "cosa", "cosas", "bloque", "bloques", "pila", "pilas", "stack", "stacks"}
    | _SPANISH_ITEMS
    | set(BEDROCK_ITEMS)
    | {item + "s" for item in BEDROCK_ITEMS}
)

_XP_TERMS = {
    "experiencia", "xp", "exp", "puntos de experiencia", "puntos de xp",
    "niveles de experiencia", "niveles de xp",
}
_LEVEL_TERMS = {"nivel", "niveles", "puntos"}

_GAMERULE_COMPOUND_TERMS = {
    "conservar inventario", "keepinventory", "keep inventory", "mantener inventario",
    "fuego amigo", "ciclo de dia y noche", "ciclo de día y noche", "ciclo solar",
    "ciclo dia y noche", "ciclo de dia", "ciclo de día", "ciclo de noche", "dodaylightcycle",
    "ciclo de clima", "ciclo del clima", "ciclo climatico", "ciclo climático", "doweathercycle",
    "daño por caida", "daño por caída", "daños por caida", "daños por caída",
    "daño de caida", "daño de caída", "daños de caida", "daños de caída", "falldamage",
    "aparezcan monstruos", "aparicion de monstruos", "aparición de monstruos",
    "spawn de monstruos", "domobspawning", "generacion de criaturas", "generación de criaturas",
    "aparezcan criaturas", "random tick speed", "randomtickspeed", "tick speed",
    "explosiones de tnt", "explosión de tnt", "explosiones de dinamita", "tntexplodes",
    "daño de fuego", "daño por fuego", "firedamage", "fuego de daño",
    "daño por ahogamiento", "daño de ahogamiento", "drowningdamage",
    "daño por congelamiento", "daño de congelamiento", "freezedamage",
    "regeneracion natural", "regeneración natural", "naturalregeneration",
    "mostrar coordenadas", "muestra coordenadas", "mostrar las coordenadas", "muestra las coordenadas",
    "activa coordenadas", "activar coordenadas", "activa las coordenadas", "activar las coordenadas",
    "desactiva coordenadas", "desactivar coordenadas", "desactiva las coordenadas", "desactivar las coordenadas",
    "showcoordinates", "ver coordenadas",
    "mensajes de muerte", "mensaje de muerte", "showdeathmessages",
    "aparicion de fantasmas", "aparición de fantasmas", "insomnio", "doinsomnia",
    "saqueo de criaturas", "loot de mobs", "domobloot",
    "destruccion por criaturas", "destrucción por criaturas", "mobgriefing",
    "reaparicion inmediata", "reaparición inmediata", "doimmediaterespawn",
    "caida de bloques", "caída de bloques", "dotiledrops",
    "propagacion de fuego", "propagación de fuego", "dofiretick",
    "desbloqueo de recetas", "recipesunlock",
    "regla de juego", "reglas de juego",
    "no perder inventario", "dropeo de bloques", "drop de los mobs", "drop de mobs",
    "peleas entre jugadores", "peleas entre usuarios", "dano entre jugadores",
    "generacion de monstruos", "generación de monstruos", "ver las coordenadas",
    "respawn instantaneo", "respawn instantáneo", "coordenadas en pantalla",
    "explosiones de camas", "bloqueo de recetas",
    "mensajes de quien murio", "mensajes de quién murió",
    "fantasmas por no dormir", "phantoms por no dormir",
    "avisos de muerte", "respuesta de comandos", "spam de command blocks",
    "mensajes de bloques de comando", "visualizacion de coordenadas", "oculta las coordenadas",
    "mensajes de bloques de comandos", "salida de bloques de comandos",
    "coords de la pantalla", "cambio de clima automatico",
    "coords en pantalla", "propagacion del fuego", "aparicion de mobs",
    "paso de las horas", "feedback de comandos", "fuego estatico", "dano por caidas",
    "dano por congelacion", "inmunidad a caidas", "inmunidad al frio",
}

_GAMERULE_ALL_TERMS = _GAMERULE_COMPOUND_TERMS | {"pvp", "gamerule", "game rule", "reglas", "regla"} | set(BEDROCK_GAMERULES)

_ALLOWLIST_TERMS = {
    "whitelist", "allowlist", "lista blanca", "listablanca", "acceso", "autorizado", "autorizados",
    "lista permitida", "jugadores permitidos", "filtro de jugadores", "permite la entrada",
    "permitir la entrada", "abre el servidor a cualquiera", "cerrar el servidor a desconocidos",
}

_WEATHER_TERMS = {
    "lluvia", "llueve", "llover", "llueva", "clima", "soleado", "despejado", "despeja",
    "tormenta", "tormenta electrica", "tormenta eléctrica", "rayos", "truenos",
    "weather", "cielo", "nublado", "tempestad",
}

_TIME_TERMS = {
    "dia", "día", "noche", "manana", "mañana", "mediodia", "mediodía", "medianoche",
    "amanecer", "amanece", "atardecer", "atardece", "anochece", "anochezca",
    "puesta de sol", "puesta del sol", "salida del sol", "time set", "hora",
    "tiempo", "hora del mundo",
    "tick", "alba", "amanezca", "atardezca", "oscurece", "despierta el sol", "momento nocturno",
}

_GAMEMODE_TERMS = {
    "creativo", "supervivencia", "survival", "aventura", "espectador",
    "gamemode", "game mode", "modo creativo", "modo supervivencia", "modo aventura", "modo espectador",
    "modo normal",
}

_ENTITY_NAMES = {
    "creeper", "zombi", "zombie", "vaca", "oveja", "esqueleto", "aldeano", "enderman",
    "cerdo", "arana", "araña", "bruja", "wither", "dragon", "dragón", "slime",
    "ghast", "golem", "blaze", "rayo", "rayos",
} | set(BEDROCK_ENTITIES)

_SUMMON_VERBS = {
    "spawnea", "spawnear", "invoca", "invocar", "aparece", "aparecer", "aparezca",
    "genera", "generar", "crea", "crear", "summon", "suelta", "pon un soporte de armadura",
}

_MESSAGE_TERMS = {
    "di", "dile", "diles", "anuncia", "anuncio", "avisa", "avisale", "avísale",
    "escribe", "escribele", "escríbele", "mensaje", "mensaje privado", "chat",
    "broadcast", "susurra", "whisper", "notifica", "notificale", "notifícale",
    "comunicado", "comunica", "publica", "tell", "susurrale", "susúrrale", "decirle", "decir", "anunciar",
    "envia un mensaje", "envía un mensaje", "manda un mensaje",
}

_TELEPORT_TERMS = {
    "teletransporta", "teletransporte", "teletransportame", "teletranspórtame",
    "trae", "traeme", "tráeme", "lleva", "llevame", "llévame", "mueve", "mueveme", "múeveme",
    "tpea", "tpeame", "tp", "coordenadas", "posicion", "posición", "hacia mi", "hacia mí",
    "junto a",
    "teletransportar", "traerme", "reune", "traslada", "ubicacion", "mandame",
    "voy hacia", "a mi lado", "al lado de",
    "trasladame", "pasa a", "manda a", "vaya hacia",
}

_PLAYER_MANAGE_TERMS = {
    "expulsa", "kickea", "kick", "desconecta", "bota", "operador", "administrador", "admin",
    "deop", "op", "revoca", "permisos", "mata", "ejecuta", "kill",
    "saca", "echa", "suspende", "banea", "destruye", "manda al lobby",
}

_GIVE_VERBS = {
    "dame", "dale", "darle", "dales", "danos", "entrega", "entregame", "entrégame",
    "entregale", "entrégale", "regala", "regalame", "regálame", "regalale", "regálale",
    "pasame", "pásame", "pasale", "pásale", "necesito", "quiero",
    "consigueme", "consígueme", "consigue", "añade", "anade", "suministra",
    "dropea", "soltame", "sueltame", "suéltame", "echame", "échame", "toma",
    "otorga", "otórgale", "otorgale", "otórgame", "otorgame",
    "facilitame", "facilítame", "suministrale", "suminístrale", "suministrame", "suminístrame",
    "facilitale", "pasarle", "hazle llegar", "reparte", "mandale",
    "darme", "dropeame",
}


def _normalize_router_text(text: str) -> str:
    """Normaliza sólo el clasificador; nunca modifica nombres ni texto enviados al LLM."""
    return "".join(
        c for c in unicodedata.normalize("NFD", text.casefold())
        if not unicodedata.combining(c)
    )


def _make_pattern(words):
    sorted_w = sorted({_normalize_router_text(w) for w in words}, key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(re.escape(w) for w in sorted_w) + r")\b", re.IGNORECASE)


_pat_gamerule_compound = _make_pattern(_GAMERULE_COMPOUND_TERMS)
_pat_gamerule = _make_pattern(_GAMERULE_ALL_TERMS)
_pat_effect_names = _make_pattern(_EFFECT_NAMES)
_pat_effect_terms = _make_pattern(_EFFECT_TERMS)
_pat_removal = _make_pattern(_REMOVAL_VERBS)
_pat_items = _make_pattern(_ITEM_TERMS)
_pat_spanish_items = _make_pattern(_SPANISH_ITEMS | {"inventario", "objetos", "item", "items"})
_pat_xp = _make_pattern(_XP_TERMS)
_pat_levels = _make_pattern(_LEVEL_TERMS)
_pat_allowlist = _make_pattern(_ALLOWLIST_TERMS)
_pat_weather = _make_pattern(_WEATHER_TERMS)
_pat_time = _make_pattern(_TIME_TERMS)
_pat_gamemode = _make_pattern(_GAMEMODE_TERMS)
_pat_entities = _make_pattern(_ENTITY_NAMES)
_pat_summon_verbs = _make_pattern(_SUMMON_VERBS)
_pat_message = _make_pattern(_MESSAGE_TERMS)
_pat_teleport = _make_pattern(_TELEPORT_TERMS)
_pat_player = _make_pattern(_PLAYER_MANAGE_TERMS)
_pat_give_verbs = _make_pattern(_GIVE_VERBS)

_pat_nivel_num = re.compile(r"\bnivel(?:es)?\s*(?:\d+|[ivx]+)\b", re.IGNORECASE)
_pat_dur_seconds = re.compile(r"\b(?:segundos?|ticks?|minutos?)\b", re.IGNORECASE)
_router_coordinate = r"(?:[~^](?:-?\d+(?:\.\d+)?)?|-?\d+(?:\.\d+)?)"
_pat_coords = re.compile(r"(?<!\w)" + _router_coordinate + r"\s+" + _router_coordinate + r"\s+" + _router_coordinate + r"(?!\w)")
_pat_at_spawn = re.compile(r"\b(?:al|hacia el|en el)\s+spawn\b", re.IGNORECASE)

# Combinaciones semánticas de reglas: no son coincidencias de prompts completos.
# El objeto (inventario, fuego, criaturas...) debe ir con la acción relevante.
_pat_gamerule_semantic = re.compile(
    r"\b(?:"
    r"(?:inventario|items|cosas).{0,65}\b(?:morir|muera|mueran|muerte)"
    r"|(?:guardar?|conserva\w*|manten\w*).{0,50}\b(?:inventario|cosas).{0,30}\b(?:morir|muera|muerte)"
    r"|(?:bloques).{0,35}\b(?:suelten|caiga|caigan|drop|dropeo)"
    r"|(?:romper bloques).{0,30}\b(?:nada|items|objetos)"
    r"|(?:creepers?|crepers?|mobs|criaturas|endermans?).{0,40}\b(?:rompan|romper|destruyan|destruir|danen|muevan)"
    r"|(?:criaturas|mobs).{0,20}\bden.{0,15}\b(?:objetos|items).{0,15}\bmorir"
    r"|(?:dano|destruccion).{0,30}\b(?:terreno|criaturas)"
    r"|(?:protege|proteger).{0,35}\b(?:creepers?|mobs)"
    r"|(?:incendios?|fuego).{0,30}\b(?:extiendan|extienda|propague|propaguen|expanda|expandan)"
    r"|(?:avance|movimiento).{0,20}\bsol"
    r"|(?:pausa|deten|congela|reanuda|activa|desactiva|bloquea).{0,25}\b(?:ciclo|reloj del mundo|clima|tiempo)"
    r"|(?:clima).{0,25}\b(?:cambie|cambia|cambiar).{0,20}\b(?:solo|tiempo|automaticamente)"
    r"|(?:dinamita|tnt|camas|anclas).{0,30}\b(?:explosion|explot\w*)"
    r"|(?:regenerar|regener\w*|cure).{0,30}\bvida.{0,35}\b(?:comer|comida|barra|automaticamente)"
    r"|(?:comida).{0,30}\b(?:cure|regenere).{0,20}\bvida"
    r"|(?:corazones).{0,25}\bcuren.{0,15}\bcomida"
    r"|(?:chat).{0,30}\b(?:muere|murio|morir|muerte)"
    r"|(?:activa|desactiva|habilita|deshabilita).{0,20}\b(?:bloques de comandos?)"
    r"|(?:apaga|enciende|silencia|permite usar).{0,20}\b(?:bloques de comandos?)"
    r"|(?:tiempo|sol|reloj).{0,15}\bavance.{0,20}\bnormalmente"
    r"|(?:sol).{0,15}\b(?:mueva|moverse)"
    r"|(?:fantasmas|phantoms).{0,25}\b(?:duermen|dormir)"
    r"|(?:destruccion).{0,35}\bmobs"
    r"|(?:fuego).{0,20}\b(?:cause|haga).{0,10}\bdano"
    r"|(?:mineral).{0,15}\bpicar"
    r"|(?:lava|fuego).{0,25}\b(?:queme|quemen|dane|danen).{0,20}\bjugadores"
    r"|(?:jugadores).{0,20}\b(?:ahoguen|ahogarse|congelen)"
    r"|(?:aparicion).{0,25}\b(?:phantoms|fantasmas)"
    r"|(?:dano|danos).{0,10}\b(?:de|por|al).{0,15}\b(?:caida|ahogamiento|congelamiento|fuego)"
    r")\b",
    re.IGNORECASE,
)
_pat_router_prefix = re.compile(
    r"^(?:(?:hola|oye|admin|bot|servidor|mira|por favor|si puedes|puedes|podrias)\b[,:]?\s*)+",
    re.IGNORECASE,
)

_TOOL_PATTERNS = {
    name: re.compile(
        r"\b(?:" + "|".join(sorted((re.escape(k) for k in kws), key=len, reverse=True)) + r")\b",
        re.IGNORECASE,
    )
    for name, kws in TOOL_KEYWORDS.items()
}


def score_tools(prompt: Optional[str]) -> Dict[str, int]:
    """Calcula la relevancia ponderada de cada herramienta para un prompt dado."""
    prompt_str = _normalize_router_text(str(prompt) if prompt is not None else "").lstrip("¿¡ \t")
    prompt_str = _pat_router_prefix.sub("", prompt_str)
    scores = {t["function"]["name"]: 0 for t in BEDROCK_TOOLS}

    # El contenido de un mensaje puede mencionar cualquier comando del catálogo.
    # Una orden explícita de comunicación conserva send_message antes de puntuar el payload.
    if _pat_message.match(prompt_str) or re.match(r"(?:envia|manda|enviale|mandale)\b.{0,35}\b(?:mensaje|whisper|chat|comunicado)\b", prompt_str):
        scores["send_message"] = 30
        return scores

    # Máscara de frases gamerule compuestas para evitar colisiones léxicas (ej. tick speed, conservar inventario)
    has_gamerule_compound = bool(_pat_gamerule_compound.search(prompt_str))
    has_gamerule = has_gamerule_compound or bool(_pat_gamerule.search(prompt_str)) or bool(_pat_gamerule_semantic.search(prompt_str))
    prompt_cleaned = _pat_gamerule_compound.sub(" ", prompt_str) if has_gamerule_compound else prompt_str
    prompt_cleaned = re.sub(r"\b(cubeta|cubetas)\s+vacias?\b", r"\1", prompt_cleaned)

    has_effect_name = bool(_pat_effect_names.search(prompt_cleaned))
    has_effect_term = bool(_pat_effect_terms.search(prompt_cleaned))
    # Una poción en el inventario es un ítem, no la orden de quitar un efecto activo.
    has_effect = has_effect_name or (has_effect_term and (
        re.search(r"\b(?:efecto|efectos|buff|debuff)\b", prompt_cleaned)
        or not re.search(r"\b(?:pocion|pociones)\b", prompt_cleaned)
    ))

    has_removal = bool(_pat_removal.search(prompt_cleaned))
    has_items = bool(_pat_items.search(prompt_cleaned))
    has_item_or_inv = bool(_pat_spanish_items.search(prompt_cleaned))
    has_xp = bool(_pat_xp.search(prompt_cleaned)) and not re.search(r"\b(?:botellas?|frascos?)\s+de\s+(?:experiencia|xp)\b", prompt_cleaned)
    has_levels = bool(_pat_levels.search(prompt_cleaned))
    has_allowlist = bool(_pat_allowlist.search(prompt_cleaned))
    has_weather = bool(_pat_weather.search(prompt_cleaned))
    has_time = bool(_pat_time.search(prompt_cleaned))
    has_gamemode = bool(_pat_gamemode.search(prompt_cleaned))
    has_message = bool(_pat_message.search(prompt_cleaned))
    has_teleport = bool(_pat_teleport.search(prompt_cleaned))
    has_player = bool(_pat_player.search(prompt_cleaned))
    has_give = bool(_pat_give_verbs.search(prompt_cleaned))
    has_summon_verb = bool(_pat_summon_verbs.search(prompt_cleaned))
    has_entity = bool(_pat_entities.search(prompt_cleaned))

    # --- 1. apply_effect ---
    if has_effect:
        scores["apply_effect"] += 10
        if has_effect_name:
            scores["apply_effect"] += 5
        if _pat_nivel_num.search(prompt_cleaned):
            scores["apply_effect"] += 5
        if _pat_dur_seconds.search(prompt_cleaned):
            scores["apply_effect"] += 2
        if has_removal:
            scores["apply_effect"] += 5

    # --- 2. manage_experience ---
    if has_xp:
        scores["manage_experience"] += 15
    elif has_levels:
        if not has_effect:
            scores["manage_experience"] += 10
        else:
            scores["manage_experience"] = -10
    elif has_effect:
        scores["manage_experience"] = -10

    # --- 3. clear_inventory ---
    if has_removal:
        if has_effect:
            scores["clear_inventory"] = -10
        elif has_allowlist:
            scores["clear_inventory"] = -10
        elif has_xp or (has_levels and not has_item_or_inv):
            scores["clear_inventory"] = -10
        elif has_weather:
            scores["clear_inventory"] = -10
        elif has_gamerule:
            scores["clear_inventory"] = -10
        elif "operador" in prompt_cleaned.lower() or "admin" in prompt_cleaned.lower():
            scores["clear_inventory"] = -10
        elif "del mundo" in prompt_cleaned.lower():
            scores["clear_inventory"] = -10
        elif has_items or has_item_or_inv or "inventario" in prompt_cleaned.lower():
            scores["clear_inventory"] += 20
        else:
            scores["clear_inventory"] += 5
    elif "inventario" in prompt_cleaned.lower() and not has_gamerule:
        scores["clear_inventory"] += 5

    # --- 4. give_item ---
    if has_removal and (has_items or has_item_or_inv):
        scores["give_item"] = -10
    elif has_effect and not has_items:
        scores["give_item"] = -10
    elif (has_xp or has_levels) and not has_items:
        scores["give_item"] = -10
    elif (has_player or "operador" in prompt_cleaned.lower() or "administrador" in prompt_cleaned.lower()) and not has_items:
        scores["give_item"] = -10
    else:
        if has_give:
            scores["give_item"] += 8
        if has_items:
            scores["give_item"] += 5

    # --- 5. set_time ---
    if has_weather or has_effect or has_gamerule:
        scores["set_time"] = -10
    else:
        if has_time:
            scores["set_time"] += 10
        if "ticks" in prompt_cleaned.lower():
            scores["set_time"] += 10

    # --- 6. set_weather ---
    if "rayo" in prompt_cleaned.lower() and has_summon_verb:
        scores["set_weather"] = -10
    elif has_weather:
        scores["set_weather"] += 10
        if _pat_dur_seconds.search(prompt_cleaned):
            scores["set_weather"] += 2
    elif has_removal and ("lluvia" in prompt_cleaned.lower() or "tormenta" in prompt_cleaned.lower()):
        scores["set_weather"] += 15

    # --- 7. set_gamerule ---
    if has_gamerule:
        scores["set_gamerule"] += 15

    # --- 8. manage_allowlist ---
    if has_allowlist:
        scores["manage_allowlist"] += 15

    # --- 9. manage_player ---
    if has_player:
        scores["manage_player"] += 10
    if "elimina" in prompt_cleaned.lower():
        if "del mundo" in prompt_cleaned.lower():
            scores["manage_player"] += 15
        elif has_items or has_item_or_inv or has_allowlist or has_effect or has_xp or has_weather or has_gamerule:
            scores["manage_player"] = -10
        else:
            scores["manage_player"] += 5
    if "mata" in prompt_cleaned.lower() or "kick" in prompt_cleaned.lower() or "expulsa" in prompt_cleaned.lower():
        scores["manage_player"] += 12

    # --- 10. set_gamemode ---
    if has_gamemode:
        scores["set_gamemode"] += 12

    # --- 11. summon_entity ---
    if has_summon_verb:
        if _pat_at_spawn.search(prompt_cleaned) and not has_entity:
            pass
        else:
            scores["summon_entity"] += 8
            if has_entity:
                scores["summon_entity"] += 8
    elif has_entity and not has_teleport and not has_give:
        scores["summon_entity"] += 5

    # --- 12. send_message ---
    if has_message:
        scores["send_message"] += 10
        if "chat" in prompt_cleaned.lower() or "mensaje" in prompt_cleaned.lower():
            scores["send_message"] += 5

    # --- 13. teleport ---
    if has_teleport:
        scores["teleport"] += 10
    if _pat_coords.search(prompt_cleaned) and not has_summon_verb:
        scores["teleport"] += 5
    if _pat_at_spawn.search(prompt_cleaned) and not has_message:
        scores["teleport"] += 8
    if ("envia" in prompt_cleaned.lower() or "envía" in prompt_cleaned.lower()) and ("spawn" in prompt_cleaned.lower() or _pat_coords.search(prompt_cleaned)) and not has_message:
        scores["teleport"] += 10

    return scores


def _select_tools_impl(prompt: Optional[str], top_n: Optional[int] = 4) -> List[Dict[str, Any]]:
    """Filtra BEDROCK_TOOLS a las `top_n` con mayor puntuación de intención contextual."""
    if top_n is None:
        limit = 4
    else:
        try:
            limit = max(0, int(top_n))
        except (ValueError, TypeError):
            limit = 4
    scores = score_tools(prompt)
    scored = [(scores[tool.get("function", {}).get("name", "")], tool) for tool in BEDROCK_TOOLS]
    if limit == 0:
        return []
    if not scored or max(s for s, _ in scored) <= 0:
        # Sin evidencia, excluir 9 herramientas sería arbitrario. Sólo en este caso
        # se admite el catálogo completo (coste extra de prefill, mejor recall).
        return list(BEDROCK_TOOLS) if limit >= 4 else list(DEFAULT_CANONICAL_TOOLS[:limit])
    scored.sort(key=lambda t: t[0], reverse=True)
    top = [tool for _, tool in scored[:limit]]
    random.Random((str(prompt) if prompt is not None else "")).shuffle(top)
    return top


def _sanitize_string(val: Any) -> str:
    """Elimina saltos de línea, retornos de carro, bytes nulos y comillas para evitar inyección en consola BDS."""
    if val is None:
        return ""
    s = str(val).replace("\x00", "").replace("\r", " ").replace("\n", " ").replace('"', '').strip()
    s = re.sub(r"</?escape>", "", s).strip()
    return s.strip("'")


def format_target(target: Any) -> str:
    """Formatea el nombre del jugador o selector para comandos Bedrock."""
    if not target:
        return "@p"
    s = _sanitize_string(target)
    if not s or s.lower() in MISSING_TOKENS:
        return "@p"
    if s.startswith("@"):
        return s
    return f'"{s}"'


def is_coordinates(dest: Any) -> bool:
    """
    Detecta si un destino corresponde a coordenadas relativas o absolutas.
    - Relativas: contienen '~' o '^'.
    - Absolutas: exactamente 3 o 5 componentes numéricos separados por espacios/comas.
    - Nombres de jugador o gamertags puramente numéricos (ej. '1234') NO son coordenadas.
    """
    if dest is None:
        return False
    stripped = _sanitize_string(dest)
    if not stripped or stripped.lower() in MISSING_TOKENS:
        return False
    # Relativo o local si contiene tildes o intercalaciones
    if "~" in stripped or "^" in stripped:
        return True
    # Coordenadas absolutas: deben ser exactamente 3 o 5 números
    parts = stripped.replace(",", " ").split()
    if len(parts) in (3, 5):
        num_pat = re.compile(r"^[-+]?(?:\d+(?:\.\d+)?|\.\d+)$")
        return all(bool(num_pat.match(p)) for p in parts)
    return False


def format_destination(dest: Any) -> str:
    """Formatea el destino en teleport: coordenadas normalizadas o jugador con comillas."""
    if not dest:
        return "~ ~ ~"
    dest_str = _sanitize_string(dest)
    if not dest_str or dest_str.lower() in MISSING_TOKENS:
        return "~ ~ ~"
    if is_coordinates(dest_str):
        normalized = re.sub(r"[,]+", " ", dest_str)
        parts = normalized.strip().split()
        if len(parts) == 1:
            if parts[0] == "~":
                return "~ ~ ~"
            elif parts[0] == "^":
                return "^ ^ ^"
            elif parts[0].startswith("~") or parts[0].startswith("^"):
                return f"{parts[0]} ~ ~"
        elif len(parts) == 2 and any(p.startswith("~") or p.startswith("^") for p in parts):
            return f"{parts[0]} {parts[1]} ~"
        return " ".join(parts)
    return format_target(dest_str)


def _clean_val(v: Any) -> Any:
    """Limpia tokens <escape>, bytes nulos, normaliza ausentes (None/null/...) y castea tipos."""
    if v is None:
        return None
    if isinstance(v, str):
        v = v.replace("\x00", "")
        v = re.sub(r"</?escape>", "", v).strip()
        v_lower = v.lower()
        if v_lower in MISSING_TOKENS:
            return None
        if v_lower == "true":
            return True
        elif v_lower == "false":
            return False
        elif re.match(r"^-?\d+$", v):
            try:
                return int(v)
            except ValueError:
                pass
        elif re.match(r"^-?\d+\.\d+$", v):
            try:
                return float(v)
            except ValueError:
                pass
    return v


def parse_function_call(content: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """
    Parser robusto para llamadas de función en texto plano:
    Soporta formato canónico FunctionGemma (<escape>value<escape> y <start_function_call>...<end_function_call>),
    bloques JSON estándar y variantes de pares clave-valor con o sin comillas.
    """
    if not content:
        return None

    # Eliminar bytes nulos al inicio para prevenir fallos en decodificadores JSON y C-strings
    content = content.replace("\x00", "")

    # 1. Regex de FunctionGemma estricto o relajado
    match = re.search(r"<start_function_call>\s*call:(\w+)\s*\{(.*?)\}\s*<end_function_call>", content, re.DOTALL)
    if not match:
        match = re.search(r"call:(\w+)\s*\{(.*?)\}", content, re.DOTALL)

    if match:
        func_name = match.group(1).strip()
        raw_body = match.group(2).strip()

        # A. Normalizar <escape>...<escape> de FunctionGemma a strings JSON válidos
        def _rep_escape(m):
            inner = m.group(1).replace('"', '\\"')
            return f'"{inner}"'

        norm_body = re.sub(r"<escape>(.*?)<escape>", _rep_escape, raw_body, flags=re.DOTALL)

        # Entrecomillar claves que no tengan comillas
        quoted_keys = re.sub(r'(?:^|(?<=[\s,{]))([A-Za-z_]\w*)\s*:', r'"\1":', norm_body)

        # Intentar cargar como JSON envolviendo en { }
        # First-wins en duplicadas: el modelo emite el valor bueno primero y el default despues
        try:
            data = json.loads("{" + quoted_keys + "}", object_pairs_hook=lambda pairs: {k: _clean_val(v) for k, v in dict(reversed(pairs)).items()})
            if isinstance(data, dict):
                return func_name, data
        except Exception:
            pass

        # Si falla, probar comillas simples reemplazadas
        try:
            fixed_quotes = re.sub(r"'", '"', norm_body)
            data = json.loads("{" + fixed_quotes + "}", object_pairs_hook=lambda pairs: {k: _clean_val(v) for k, v in dict(reversed(pairs)).items()})
            if isinstance(data, dict):
                return func_name, data
        except Exception:
            pass

        # Parser regex tolerante para pares key: value (capturando <escape> completo)
        args: Dict[str, Any] = {}
        pair_pattern = re.compile(
            r'([A-Za-z_]\w*)\s*[:=]\s*(?:<escape>(.*?)<escape>|"([^"]*)"|\'([^\']*)\'|([^\s,{}]+))',
            re.DOTALL
        )
        for m in pair_pattern.finditer(raw_body):
            key = m.group(1)
            val = m.group(2) if m.group(2) is not None else (
                m.group(3) if m.group(3) is not None else (
                    m.group(4) if m.group(4) is not None else m.group(5)
                )
            )
            if val is not None:
                args.setdefault(key, _clean_val(val))  # primera ocurrencia gana (valor bueno antes que el default)
        if args:
            return func_name, args

    # 1.5. Llamada sin cerrar (modelo truncado/divagando sin <end_function_call> ni '}'):
    #      first-wins rescata la primera accion (ej. 'off' antes del divague del enum).
    unterminated = re.search(r"call:(\w+)\s*\{(.*)", content, re.DOTALL)
    if unterminated and "}" not in content[unterminated.start():]:
        func_name = unterminated.group(1).strip()
        raw_body = unterminated.group(2).strip()
        args = {}
        pair_pattern = re.compile(
            r'([A-Za-z_]\w*)\s*[:=]\s*(?:<escape>(.*?)<escape>|"([^"]*)"|\'([^\']*)\'|([^\s,{}]+))',
            re.DOTALL
        )
        for m in pair_pattern.finditer(raw_body):
            key = m.group(1)
            val = m.group(2) if m.group(2) is not None else (
                m.group(3) if m.group(3) is not None else (
                    m.group(4) if m.group(4) is not None else m.group(5)
                )
            )
            if val is not None:
                args.setdefault(key, _clean_val(val))
        if args:
            return func_name, args

    # 2. Intentar buscar un objeto JSON suelto en el texto
    json_match = re.search(r"\{.*\}", content, re.DOTALL)
    if json_match:
        try:
            obj = json.loads(json_match.group(0))
            if isinstance(obj, dict) and "name" in obj and "arguments" in obj:
                args = obj["arguments"]
                if isinstance(args, str):
                    args = json.loads(args)
                return obj["name"], {k: _clean_val(v) for k, v in args.items()}
        except Exception:
            pass

    return None


def resolve_targets(
    func_name: str,
    args: Dict[str, Any],
    prompt: str = "",
    online_players: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Si el usuario dice 'a mí', 'dame', etc. y hay exactamente un jugador online,
    auto-resuelve el objetivo a ese jugador específico sin sobreescribir terceros explícitos.
    """
    args_copy = dict(args)
    if not online_players or len(online_players) != 1:
        return args_copy

    solo_player = online_players[0]
    prompt_lower = prompt.lower()
    has_self_trigger = any(re.search(pat, prompt_lower) for pat in SELF_PROMPT_TRIGGERS)

    # 1. Target principal
    if "target" in args_copy and args_copy["target"] is not None:
        cur_target = str(args_copy["target"]).strip().lower()
        # Solo auto-resolver si el target es un pronombre de primera persona o vacío,
        # o si es un selector genérico (@p, @s) y el prompt explícitamente se refirió a 'mí'
        if cur_target in {"a mí", "a mi", "me", "yo", "self", "sender"}:
            args_copy["target"] = solo_player
        elif cur_target in {"@p", "@s", ""} and has_self_trigger:
            args_copy["target"] = solo_player
    elif has_self_trigger and func_name in (
        "give_item", "teleport", "apply_effect", "set_gamemode",
        "manage_allowlist", "clear_inventory", "manage_experience"
    ):
        args_copy["target"] = solo_player

    # 2. Destination en teleport (solo si el destino es explícitamente hacia 'mí' / self)
    if func_name == "teleport" and "destination" in args_copy and args_copy["destination"] is not None:
        cur_dest = str(args_copy["destination"]).strip().lower()
        if cur_dest in {"a mí", "a mi", "me", "yo", "self", "sender"}:
            args_copy["destination"] = solo_player
        elif cur_dest in {"@p", "@s"} and has_self_trigger:
            args_copy["destination"] = solo_player

    return args_copy


def tool_call_to_bedrock(
    func_name: str,
    args: Dict[str, Any],
    prompt: str = "",
    online_players: Optional[List[str]] = None
) -> Tuple[str, str, Optional[str]]:
    """
    Convierte una llamada a función en un comando válido de Minecraft Bedrock,
    su explicación y una posible advertencia de seguridad/límites.
    Retorna: (command, explanation, warning)
    """
    func_name = _sanitize_string(func_name).lower()
    # Normaliza literales de ausente del modelo ("None"/"null"/...) y tipos,
    # y tolera claves con mayúsculas/minúsculas.
    normalized = {str(k).lower(): _clean_val(v) for k, v in (args or {}).items()}
    resolved_args = resolve_targets(func_name, normalized, prompt=prompt, online_players=online_players)

    if func_name == "teleport":
        target = resolved_args.get("target", "@p")
        destination = resolved_args.get("destination", "~ ~ ~")
        cmd = f"tp {format_target(target)} {format_destination(destination)}"
        explanation = f"Teletransportar a {target} a {destination}."
        return cmd, explanation, None

    elif func_name == "give_item":
        target = resolved_args.get("target", "@p")
        item = _sanitize_string(resolved_args.get("item", "diamond")).lower() or "diamond"
        raw_amount = resolved_args.get("amount", 1)
        try:
            amount = int(raw_amount)
        except (ValueError, TypeError):
            amount = 1

        if amount <= 0:
            amount = 1

        cmd = f"give {format_target(target)} {item} {amount}"
        explanation = f"Entregar {amount}x {item} a {target}."

        warning = None
        if item not in BEDROCK_ITEMS:
            warning = (
                f"Ítem '{item}' fuera del catálogo Bedrock conocido; "
                "el comando podría fallar en consola. Revisa antes de ejecutar."
            )
        if amount > 32767:
            amount_warn = (
                f"La cantidad ({amount}) supera el límite máximo de Bedrock para /give (32,767) "
                f"y el tamaño normal de stack (64). El comando podría fallar o saturar el servidor."
            )
            warning = f"{warning}; {amount_warn}" if warning else amount_warn
        elif amount > 64:
            amount_warn = (
                f"La cantidad ({amount}) excede el tamaño máximo habitual de stack (64 items). "
                f"Llenará múltiples casillas del inventario del jugador."
            )
            warning = f"{warning}; {amount_warn}" if warning else amount_warn

        return cmd, explanation, warning

    elif func_name == "set_time":
        time_val = _sanitize_string(resolved_args.get("time_value", "day")).lower() or "day"
        cmd = f"time set {time_val}"
        explanation = f"Ajustar la hora del mundo a {time_val}."
        warning = None
        if time_val not in ("day", "night", "noon", "midnight", "sunrise", "sunset") and not re.fullmatch(r"-?\d+", time_val):
            warning = (
                f"Valor de hora '{time_val}' fuera de catálogo (day/night/noon/midnight/sunrise/sunset o ticks); "
                "el comando podría fallar en consola. Revisa antes de ejecutar."
            )
        return cmd, explanation, warning

    elif func_name == "set_weather":
        raw_w = _sanitize_string(resolved_args.get("weather_type", "clear")).lower()
        w_clean = re.sub(r"[^a-zA-Z]", "", raw_w) or "clear"
        weather_map = {
            "storm": "thunder",
            "tormenta": "thunder",
            "lluvia": "rain",
            "despejado": "clear",
            "sol": "clear",
            "soleado": "clear",
        }
        w_type = weather_map.get(w_clean, w_clean)
        warning = None
        if w_type not in BEDROCK_WEATHER:
            warning = (
                f"Clima '{raw_w}' fuera de catálogo Bedrock (clear/rain/thunder); "
                "se usó 'clear' por defecto. Revisa antes de ejecutar."
            )
            w_type = "clear"
        duration = resolved_args.get("duration")
        # Guardia prompt-intención: una duración inventada cambia el comportamiento
        # del comando. Si el usuario no indicó un número, se omite y la GUI lo deja
        # claro antes de cualquier aprobación humana.
        duration_warn = None
        if duration is not None and (prompt or "").strip() and not re.search(r"\d+", prompt):
            duration = None
            duration_warn = (
                "El modelo propuso una duración de clima que no pediste; "
                "se omitió. Revisa antes de ejecutar."
            )
        if duration is not None:
            try:
                dur_int = int(duration)
                cmd = f"weather {w_type} {dur_int}"
                explanation = f"Cambiar el clima a {w_type} durante {dur_int} segundos."
            except (ValueError, TypeError):
                cmd = f"weather {w_type}"
                explanation = f"Cambiar el clima a {w_type}."
        else:
            cmd = f"weather {w_type}"
            explanation = f"Cambiar el clima a {w_type}."
        if duration_warn:
            warning = f"{warning}; {duration_warn}" if warning else duration_warn
        return cmd, explanation, warning

    elif func_name == "set_gamemode":
        raw_gm = _sanitize_string(resolved_args.get("gamemode", "survival")).lower()
        gamemode = re.sub(r"[^a-zA-Z0-9]", "", raw_gm) or "survival"
        warning = None
        gamemode_aliases = {
            "creativo": "creative", "supervivencia": "survival", "aventura": "adventure",
            "espectador": "spectator",
        }
        if gamemode in gamemode_aliases:
            gamemode = gamemode_aliases[gamemode]
        if gamemode not in BEDROCK_GAMEMODES:
            warning = (
                f"Modo de juego '{raw_gm}' fuera de catálogo (survival/creative/adventure/spectator); "
                "el comando podría fallar en consola. Revisa antes de ejecutar."
            )
        target = resolved_args.get("target")
        if target:
            cmd = f"gamemode {gamemode} {format_target(target)}"
            explanation = f"Cambiar modo de juego a {gamemode} para {target}."
        else:
            cmd = f"gamemode {gamemode}"
            explanation = f"Cambiar modo de juego a {gamemode}."
        return cmd, explanation, warning

    elif func_name == "apply_effect":
        target = resolved_args.get("target", "@p")
        effect = _sanitize_string(resolved_args.get("effect", "speed")).lower() or "speed"
        warning = None
        if effect not in BEDROCK_EFFECTS:
            warning = (
                f"Efecto '{effect}' fuera del catálogo Bedrock conocido; "
                "el comando podría fallar en consola. Revisa antes de ejecutar."
            )
        if effect == "clear":
            cmd = f"effect {format_target(target)} clear"
            explanation = f"Eliminar todos los efectos activos de {target}."
            return cmd, explanation, warning

        raw_sec = resolved_args.get("seconds", 30)
        raw_amp = resolved_args.get("amplifier", 0)
        try:
            seconds = int(raw_sec)
        except (ValueError, TypeError):
            seconds = 30
        try:
            amplifier = int(raw_amp)
        except (ValueError, TypeError):
            amplifier = 0

        # Contrato Bedrock: el nivel visible N usa el amplificador N-1.
        # Corrige también las etiquetas antiguas de v2/v3 cuando hay nivel explícito.
        level_match = re.search(r"\bnivel\s*(\d+)\b", _normalize_router_text(prompt or ""))
        if level_match:
            human_level = int(level_match.group(1))
            if not 1 <= human_level <= 256:
                raise ValueError("El nivel del efecto debe estar entre 1 y 256 (amplificador Bedrock 0-255).")
            expected_amplifier = human_level - 1
            if amplifier != expected_amplifier:
                level_warn = f"Se ajustó el amplificador de {amplifier} a {expected_amplifier} para respetar el nivel {human_level} solicitado."
                warning = f"{warning}; {level_warn}" if warning else level_warn
                amplifier = expected_amplifier

        cmd = f"effect {format_target(target)} {effect} {seconds} {amplifier}"
        explanation = f"Aplicar efecto {effect} nivel {amplifier + 1} por {seconds}s a {target}."
        if amplifier < 0 or amplifier > 255:
            amp_warn = f"El amplificador ({amplifier}) está fuera del rango Bedrock (0-255)."
            warning = f"{warning}; {amp_warn}" if warning else amp_warn
        return cmd, explanation, warning

    elif func_name == "manage_player":
        raw_act = _sanitize_string(resolved_args.get("action", "kick")).lower()
        action = re.sub(r"[^a-zA-Z]", "", raw_act) or "kick"
        target = resolved_args.get("target", "@p")
        raw_reason = resolved_args.get("reason")
        reason = _sanitize_string(raw_reason) if raw_reason else None
        warning = None

        if action == "kick":
            reason_part = f" {reason}" if reason else ""
            cmd = f"kick {format_target(target)}{reason_part}"
            explanation = f"Expulsar a {target} del servidor." + (f" Motivo: {reason}" if reason else "")
            warning = f"Acción administrativa: Se desconectará forzosamente a {target}."
        elif action == "op":
            cmd = f"op {format_target(target)}"
            explanation = f"Otorgar permisos de operador a {target}."
            warning = f"Seguridad: {target} tendrá acceso administrativo total."
        elif action == "deop":
            cmd = f"deop {format_target(target)}"
            explanation = f"Revocar permisos de operador a {target}."
        elif action == "kill":
            cmd = f"kill {format_target(target)}"
            explanation = f"Eliminar a {target}."
            warning = f"Acción destructiva: Causará la muerte inmediata de {target}."
        else:
            cmd = f"{action} {format_target(target)}"
            explanation = f"Ejecutar {action} sobre {target}."
            warning = (
                f"Acción '{action}' fuera de catálogo (kick/op/deop/kill); "
                "el comando podría fallar en consola. Revisa antes de ejecutar."
            )

        return cmd, explanation, warning

    elif func_name == "set_gamerule":
        raw_rule = _sanitize_string(resolved_args.get("rule", "keepinventory"))
        rule = re.sub(r"[^a-zA-Z0-9_]", "", raw_rule).lower() or "keepinventory"
        val = resolved_args.get("value")
        warning = None
        if rule not in BEDROCK_GAMERULES:
            warning = (
                f"Regla '{rule}' fuera del catálogo Bedrock conocido; "
                "el comando podría fallar en consola. Revisa antes de ejecutar."
            )

        TRUTHY = {"true", "1", "yes", "si", "sí", "on", "enable", "activar", "activo", "verdadero"}
        FALSY = {"false", "0", "no", "off", "disable", "desactivar", "inactivo", "falso"}
        INT_RULES = {"randomtickspeed", "spawnradius", "maxcommandchainlength", "functioncommandlimit", "playerssleepingpercentage"}

        if rule in INT_RULES or (isinstance(val, int) and not isinstance(val, bool) and val > 1):
            try:
                val_int = int(val)
                val_str = str(val_int)
            except (ValueError, TypeError):
                val_str = "0"
                val_warn = f"Valor no numérico para la regla entera '{rule}'. Se asignó 0 por defecto."
                warning = f"{warning}; {val_warn}" if warning else val_warn
        elif isinstance(val, bool):
            val_str = "true" if val else "false"
        elif str(val).strip().lower() in TRUTHY:
            val_str = "true"
        elif str(val).strip().lower() in FALSY:
            val_str = "false"
        else:
            val_str = "false"
            val_warn = f"Valor booleano no reconocido o inválido '{val}' para la regla '{rule}'. Se asignó 'false' por defecto."
            warning = f"{warning}; {val_warn}" if warning else val_warn

        cmd = f"gamerule {rule} {val_str}"
        explanation = f"Ajustar regla de juego {rule} a {val_str}."
        return cmd, explanation, warning

    elif func_name == "summon_entity":
        entity = _sanitize_string(resolved_args.get("entity", "zombie")).lower() or "zombie"
        raw_coords = resolved_args.get("target_or_coords")
        coords = _sanitize_string(raw_coords) if raw_coords else None
        if coords and coords.lower() in MISSING_TOKENS:
            coords = None
        warning = None
        if entity not in BEDROCK_ENTITIES:
            warning = (
                f"Entidad '{entity}' fuera del catálogo Bedrock conocido; "
                "el comando podría fallar en consola. Revisa antes de ejecutar."
            )
        if entity in ("wither", "ender_dragon"):
            danger_warn = f"¡Alerta! Invocar '{entity}' puede provocar destrucción severa del mundo."
            warning = f"{warning}; {danger_warn}" if warning else danger_warn

        if coords:
            if is_coordinates(coords):
                coords = re.sub(r"[,]+", " ", coords)
                coords = re.sub(r"\s+", " ", coords).strip()
            else:
                raise ValueError("summon_entity requiere coordenadas X Y Z; no acepta nombres ni selectores como ubicación.")
            cmd = f"summon {entity} {coords}"
            explanation = f"Invocar {entity} en {coords}."
        else:
            cmd = f"summon {entity}"
            explanation = f"Invocar {entity} en la posición actual."
        return cmd, explanation, warning

    elif func_name == "clear_inventory":
        target = resolved_args.get("target", "@p")
        item = resolved_args.get("item")
        max_count = resolved_args.get("max_count")
        warning = None
        # Guardia prompt-intención: si el pedido trae texto pero sin cifras ni "stack",
        # un límite es alucinado (ej. max_count 0/1 con "quítame los diamantes").
        # Se ignora y se remueven todos. Con prompt vacío no se toca (llamadas API/test).
        mc_warn = None
        if max_count is not None and (prompt or "").strip():
            try:
                _mc_probe = int(max_count)
            except (ValueError, TypeError):
                _mc_probe = None
            low_p = (prompt or "").lower()
            if _mc_probe is not None and not re.search(r"\d+", prompt or "") and "stack" not in low_p:
                max_count = None
                mc_warn = (
                    "El modelo propuso un límite de cantidad que no pediste; "
                    "se ignora y se remueven todos los items. Revisa antes de ejecutar."
                )
        if item:
            item_clean = _sanitize_string(item).lower() or "air"
            if item_clean not in BEDROCK_ITEMS:
                warning = (
                    f"Ítem '{item_clean}' fuera del catálogo Bedrock conocido; "
                    "el comando podría fallar en consola. Revisa antes de ejecutar."
                )
            if mc_warn:
                warning = f"{warning}; {mc_warn}" if warning else mc_warn
            if max_count is not None:
                try:
                    mc = int(max_count)
                    cmd = f"clear {format_target(target)} {item_clean} -1 {mc}"
                    explanation = f"Remover hasta {mc}x {item_clean} del inventario de {target}."
                except (ValueError, TypeError):
                    cmd = f"clear {format_target(target)} {item_clean}"
                    explanation = f"Remover todos los {item_clean} del inventario de {target}."
            else:
                cmd = f"clear {format_target(target)} {item_clean}"
                explanation = f"Remover todos los {item_clean} del inventario de {target}."
        else:
            cmd = f"clear {format_target(target)}"
            explanation = f"Vaciar completamente el inventario de {target}."
            warning = f"Acción destructiva: Se eliminarán TODOS los items del inventario de {target}."

        return cmd, explanation, warning

    elif func_name == "send_message":
        message = _sanitize_string(resolved_args.get("message", ""))
        msg_type = _sanitize_string(resolved_args.get("type", "broadcast")).lower()
        target = resolved_args.get("target")
        warning = None
        if not message:
            warning = "Mensaje vacío; se enviará un 'say' sin texto. Revisa antes de ejecutar."

        if msg_type == "private" and target:
            cmd = f"msg {format_target(target)} {message}"
            explanation = f"Enviar mensaje privado a {target}: \"{message}\"."
        else:
            cmd = f"say {message}"
            explanation = f"Enviar mensaje público al chat: \"{message}\"."

        return cmd, explanation, warning

    elif func_name == "manage_allowlist":
        raw_act = _sanitize_string(resolved_args.get("action", "list")).lower()
        action = re.sub(r"[^a-zA-Z]", "", raw_act) or "list"
        target = resolved_args.get("target")
        warning = None

        if action in ("add", "remove"):
            if not target:
                target = "@p"
                warning = f"No se especificó jugador para 'allowlist {action}'. Se utilizó {target} por defecto."
            target_clean = _sanitize_string(target)
            cmd = f"allowlist {action} {format_target(target_clean)}"
            if action == "add":
                explanation = f"Agregar a {target_clean} a la lista blanca del servidor."
            else:
                explanation = f"Remover a {target_clean} de la lista blanca del servidor."
        elif action == "on":
            cmd = "allowlist on"
            explanation = "Activar la lista blanca del servidor. Solo jugadores en la allowlist podrán conectarse."
            warning = "Seguridad: Activar la allowlist impedirá la conexión de jugadores que no estén en la lista."
        elif action == "off":
            cmd = "allowlist off"
            explanation = "Desactivar la lista blanca del servidor. Cualquier jugador podrá conectarse."
        elif action == "list":
            cmd = "allowlist list"
            explanation = "Mostrar los jugadores en la lista blanca del servidor."
        else:
            cmd = f"allowlist {action}"
            explanation = f"Ejecutar acción '{action}' sobre la allowlist."
            warning = (
                f"Acción '{action}' fuera de catálogo (add/remove/on/off/list); "
                "el comando podría fallar en consola. Revisa antes de ejecutar."
            )

        return cmd, explanation, warning

    elif func_name == "manage_experience":
        target = resolved_args.get("target", "@p")
        raw_amount = resolved_args.get("amount", 0)
        unit = _sanitize_string(resolved_args.get("unit", "points")).lower() or "points"
        warning = None
        if unit not in ("points", "levels"):
            warning = (
                f"Unidad '{unit}' fuera de catálogo (points/levels); "
                "se trató como puntos. Revisa antes de ejecutar."
            )

        try:
            amount = int(raw_amount)
        except (ValueError, TypeError):
            amount = 0

        # Guardia prompt-intención: el signo manda según el verbo del pedido
        # ("dame 30 niveles" con amount -30 -> +30; "quítame 5" con +5 -> -5 en levels).
        # Solo actúa con intención explícita y sin conflicto; con prompt vacío no se toca.
        low_p = (prompt or "").lower()
        _give_words = ("dame", "dale", "otorga", "otor", "añade", "anade", "sube", "ponme", "ponle", "quiero", "regala")
        _remove_words = ("quitame", "quítame", "quitale", "quítale", "restame", "réstame", "restale", "réstale",
                         "bajame", "bájame", "bajale", "bájale", "sacame", "sácame", "sacale", "sácale")
        _wants_give = any(w in low_p for w in _give_words)
        _wants_remove = any(w in low_p for w in _remove_words)
        if amount < 0 and _wants_give and not _wants_remove:
            amount = abs(amount)
            _sign_warn = (
                f"El modelo propuso cantidad negativa ({amount * -1}) para un pedido de entrega; "
                f"se corrigió a +{amount}. Revisa antes de ejecutar."
            )
            warning = f"{warning}; {_sign_warn}" if warning else _sign_warn
        elif amount > 0 and unit == "levels" and _wants_remove and not _wants_give:
            amount = -amount
            _sign_warn = (
                "El modelo propuso cantidad positiva para un pedido de quitar niveles; "
                f"se corrigió a {amount}. Revisa antes de ejecutar."
            )
            warning = f"{warning}; {_sign_warn}" if warning else _sign_warn

        if unit == "levels":
            cmd = f"xp {amount}L {format_target(target)}"
            if amount >= 0:
                explanation = f"Otorgar {amount} niveles de experiencia a {target}."
            else:
                explanation = f"Quitar {abs(amount)} niveles de experiencia a {target}."
        else:
            if amount < 0:
                xp_warn = "Bedrock no permite quitar puntos de experiencia directamente con /xp. Solo niveles (con sufijo L) aceptan valores negativos."
                warning = f"{warning}; {xp_warn}" if warning else xp_warn
                amount = abs(amount)
            cmd = f"xp {amount} {format_target(target)}"
            explanation = f"Otorgar {amount} puntos de experiencia a {target}."

        return cmd, explanation, warning

    # Función no reconocida en el catálogo
    return f"say Comando no reconocido para {func_name}", f"Acción no reconocida: {func_name}", "Herramienta fuera de catálogo."


def check_lmstudio_health(base_url: str = LMSTUDIO_DEFAULT_URL) -> Tuple[bool, Optional[str]]:
    """Comprueba si LM Studio responde en el endpoint /models."""
    url = f"{base_url.rstrip('/')}/models"
    try:
        resp = requests.get(url, timeout=HEALTH_TIMEOUT_SECONDS)
        if resp.status_code == 200:
            data = resp.json()
            models = data.get("data", [])
            # Override explícito: LMSTUDIO_MODEL=qwen3-1.7b (o el que uses).
            # Sin él se mantiene el comportamiento legacy (preferir functiongemma).
            preferred = os.getenv("LMSTUDIO_MODEL", "").strip().lower()
            if preferred:
                hit = next((m.get("id") for m in models if preferred in m.get("id", "").lower()), None)
                if hit:
                    return True, hit
            model_id = next((m.get("id") for m in models if "functiongemma" in m.get("id", "").lower()), models[0].get("id") if models else "functiongemma")
            return True, model_id
        return False, f"Status code {resp.status_code}"
    except Exception as exc:
        return False, str(exc)


def propose_command(
    prompt: str,
    base_url: str = LMSTUDIO_DEFAULT_URL,
    online_players: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Envía el prompt a LM Studio y retorna la propuesta estructurada para aprobación humana.
    """
    is_online, model_info = check_lmstudio_health(base_url)
    if not is_online:
        return {
            "status": "error",
            "message": (
                f"LM Studio no está disponible en {base_url} ({model_info}). "
                "Inicia LM Studio y activa el servidor local en el puerto 1234."
            )
        }

    selected_tools = select_tools(prompt)
    message_intent = score_tools(prompt)["send_message"] > 0
    payload = {
        "model": model_info or "functiongemma",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        # Pre-filtro por intención: top-4 en vez del mega-schema de 13
        # (~4x menos tokens de prefill y exactamente como el entreno 1+3).
        "tools": selected_tools,
        # Qwen3 no-thinking finaliza sus tool-calls con <|im_end|>. Sin ese stop
        # token puede seguir generando hasta max_tokens después de una llamada válida.
        "stop": ["<|im_end|>", "<end_function_call>", "<end_of_turn>", "<start_function_response>"],
        "temperature": 0.0,  # tools deterministas: no introducir variación entre ejecuciones
        "max_tokens": 512 if message_intent else 192
    }

    try:
        resp = requests.post(
            f"{base_url.rstrip('/')}/chat/completions",
            json=payload,
            timeout=HTTP_TIMEOUT_SECONDS
        )
        if resp.status_code != 200:
            return {
                "status": "error",
                "message": f"Error {resp.status_code} desde LM Studio: {resp.text}"
            }
        data = resp.json()
    except requests.exceptions.Timeout:
        return {
            "status": "error",
            "message": f"Tiempo de espera agotado ({HTTP_TIMEOUT_SECONDS}s) al consultar LM Studio."
        }
    except Exception as exc:
        return {
            "status": "error",
            "message": f"Error de conexión con LM Studio: {exc}"
        }

    choices = data.get("choices", [])
    if not choices:
        return {
            "status": "error",
            "message": "LM Studio devolvió una lista vacía de opciones."
        }

    if choices[0].get("finish_reason") == "length":
        return {
            "status": "error",
            "message": "La respuesta del modelo quedó truncada; no se generó una propuesta ejecutable."
        }

    msg = choices[0].get("message", {})
    tool_calls = msg.get("tool_calls")
    content = msg.get("content", "")

    func_name = None
    args: Dict[str, Any] = {}

    # Caso 1: Tool calls estructurados en el formato OpenAI. Robusto ante
    # respuestas malformadas de LM Studio (tool_calls con null/cadenas,
    # function no-dict, arguments que no producen dict): antes una respuesta
    # rara causaba un 500 con traceback en /api/ai/propose (2026-09-25).
    if tool_calls and isinstance(tool_calls, list):
        try:
            tc = tool_calls[0]
            fn = tc.get("function", {}) if isinstance(tc, dict) else {}
            if not isinstance(fn, dict):
                fn = {}
            func_name = fn.get("name")
            raw_args = fn.get("arguments", {})
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args)
                except Exception:
                    args = {}
            elif isinstance(raw_args, dict):
                args = raw_args
            else:
                args = {}
            if not isinstance(args, dict):
                args = {}
        except Exception:
            func_name, args = None, {}

    # Caso 2: Parsing regex de salida cruda de FunctionGemma en el content
    if not func_name and content:
        parsed = parse_function_call(content)
        if parsed:
            func_name, args = parsed

    if not func_name:
        return {
            "status": "error",
            "message": content.strip() if isinstance(content, str) and content.strip() else "El modelo no generó una llamada de función interpretable. Salida: [vacía]"
        }

    try:
        cmd, explanation, warning = tool_call_to_bedrock(
            func_name,
            args,
            prompt=prompt,
            online_players=online_players
        )
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    return {
        "status": "ok",
        "proposed_command": cmd,
        "explanation": explanation,
        "function": func_name,
        "args": args,
        "warning": warning
    }
