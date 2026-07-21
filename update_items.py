import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

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

# 1. Modify item JSONs
def modify_item(data):
    components = data["minecraft:item"]["components"]
    # Remove use animation and modifiers
    components.pop("minecraft:use_animation", None)
    components.pop("minecraft:use_modifiers", None)

update_json_file(os.path.join(BASE_DIR, "behavior_packs/guardian_robot_BP/items/guardian_activator.json"), modify_item)
update_json_file(os.path.join(BASE_DIR, "behavior_packs/guardian_robot_BP/items/guardian_controller.json"), modify_item)

# 2. Modify BP Manifest
def modify_bp_manifest(data):
    data["header"]["version"] = [1, 0, 5]
    for module in data.get("modules", []):
        if module["type"] == "script":
            module["version"] = [1, 0, 5]
    for dep in data.get("dependencies", []):
        if dep.get("uuid") == "9f075d4a-bc12-4c2c-8d14-6fa6b12a2b74":
            dep["version"] = [1, 0, 5]

update_json_file(os.path.join(BASE_DIR, "behavior_packs/guardian_robot_BP/manifest.json"), modify_bp_manifest)

# 3. Modify RP Manifest
def modify_rp_manifest(data):
    data["header"]["version"] = [1, 0, 5]
    for module in data.get("modules", []):
        if module["type"] == "resources":
            module["version"] = [1, 0, 5]

update_json_file(os.path.join(BASE_DIR, "resource_packs/guardian_robot_RP/manifest.json"), modify_rp_manifest)

# 4. Modify World JSONs
def modify_world_bp(data):
    for pack in data:
        if pack["pack_id"] == "8f075d4a-bc12-4c2c-8d14-6fa6b12a2b72":
            pack["version"] = [1, 0, 5]

update_json_file(os.path.join(BASE_DIR, "worlds/Bedrock level/world_behavior_packs.json"), modify_world_bp)

def modify_world_rp(data):
    for pack in data:
        if pack["pack_id"] == "9f075d4a-bc12-4c2c-8d14-6fa6b12a2b74":
            pack["version"] = [1, 0, 5]

update_json_file(os.path.join(BASE_DIR, "worlds/Bedrock level/world_resource_packs.json"), modify_world_rp)
