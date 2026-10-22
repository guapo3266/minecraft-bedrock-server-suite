# -*- coding: utf-8 -*-
"""tools/update_items_v2.py: se corre en un arbol falso (subproceso) y se
verifica que actualiza los JSON del pack/mundo sin dejar temporales."""
import json
import os
import shutil
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _preparar_arbol(tmp_path, script="update_items_v2.py"):
    bp = tmp_path / "behavior_packs" / "guardian_robot_BP"
    (bp / "scripts").mkdir(parents=True)
    (bp / "items").mkdir()
    (bp / "manifest.json").write_text(json.dumps({
        "header": {"version": [1, 0, 0]},
        "modules": [{"type": "script", "version": [1, 0, 0]}],
        "dependencies": [
            {"uuid": "9f075d4a-bc12-4c2c-8d14-6fa6b12a2b74", "version": [1, 0, 0]},
        ],
    }), encoding="utf-8")
    for item in ("guardian_activator", "guardian_controller"):
        (bp / "items" / f"{item}.json").write_text(
            json.dumps({"minecraft:item": {"components": {}}}), encoding="utf-8")

    rp = tmp_path / "resource_packs" / "guardian_robot_RP"
    rp.mkdir(parents=True)
    (rp / "manifest.json").write_text(json.dumps({
        "header": {"version": [1, 0, 0]},
        "modules": [{"type": "resources", "version": [1, 0, 0]}],
    }), encoding="utf-8")

    world = tmp_path / "worlds" / "Bedrock level"
    world.mkdir(parents=True)
    (world / "world_behavior_packs.json").write_text(json.dumps([
        {"pack_id": "8f075d4a-bc12-4c2c-8d14-6fa6b12a2b72", "version": [1, 0, 0]},
    ]), encoding="utf-8")
    (world / "world_resource_packs.json").write_text(json.dumps([
        {"pack_id": "9f075d4a-bc12-4c2c-8d14-6fa6b12a2b74", "version": [1, 0, 0]},
    ]), encoding="utf-8")

    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    # update_items.py es un alias de la v2: la necesita al lado.
    for nombre in {script, "update_items_v2.py"}:
        shutil.copyfile(os.path.join(BASE_DIR, "tools", nombre), tools_dir / nombre)
    return tmp_path


def test_update_items_v2_actualiza_y_no_deja_temporales(tmp_path):
    root = _preparar_arbol(tmp_path)

    r = subprocess.run(
        [sys.executable, str(root / "tools" / "update_items_v2.py")],
        capture_output=True, text=True, timeout=60,
    )

    assert r.returncode == 0, r.stderr
    bp = root / "behavior_packs" / "guardian_robot_BP"
    manifiesto = json.loads((bp / "manifest.json").read_text(encoding="utf-8"))
    assert manifiesto["header"]["version"] == [1, 0, 6]
    activador = json.loads((bp / "items" / "guardian_activator.json").read_text(encoding="utf-8"))
    assert activador["minecraft:item"]["components"]["minecraft:custom_components"] == [
        "custom:guardian_activator_behavior"
    ]
    mundo = json.loads(
        (root / "worlds" / "Bedrock level" / "world_behavior_packs.json").read_text(encoding="utf-8")
    )
    assert mundo[0]["version"] == [1, 0, 6]
    main_js = (bp / "scripts" / "main.js").read_text(encoding="utf-8")
    assert "registerCustomComponent" in main_js

    temporales = list(root.rglob("*.tmp_*"))
    assert temporales == [], f"temporales sin limpiar: {temporales}"


def test_update_items_v1_es_alias_de_v2_y_no_baja_la_version(tmp_path):
    """update_items.py (1.0.5) ya no reescribe por su cuenta: ejecutarlo despues
    de la v2 bajaba los packs de 1.0.6 a 1.0.5 sin respaldo (2026-10-21). Ahora
    es un alias: aplica tambien el paso de la 1.0.5 (quitar use_animation)."""
    root = _preparar_arbol(tmp_path, script="update_items.py")
    item_path = root / "behavior_packs" / "guardian_robot_BP" / "items" / "guardian_activator.json"
    data = json.loads(item_path.read_text(encoding="utf-8"))
    data["minecraft:item"]["components"]["minecraft:use_animation"] = "eat"
    item_path.write_text(json.dumps(data), encoding="utf-8")

    for script in ("update_items_v2.py", "update_items.py"):
        r = subprocess.run(
            [sys.executable, str(root / "tools" / script)],
            capture_output=True, text=True, timeout=60,
        )
        assert r.returncode == 0, r.stdout + r.stderr

    item = json.loads(item_path.read_text(encoding="utf-8"))
    componentes = item["minecraft:item"]["components"]
    assert "minecraft:use_animation" not in componentes
    assert componentes["minecraft:custom_components"] == ["custom:guardian_activator_behavior"]
    manifiesto = json.loads(
        (root / "behavior_packs" / "guardian_robot_BP" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifiesto["header"]["version"] == [1, 0, 6]
    assert list(root.rglob("*.tmp_*")) == []


def test_update_items_v2_respalda_main_js_editado(tmp_path):
    """main.js se sobrescribia sin respaldo y se perdian los cambios hechos a mano."""
    root = _preparar_arbol(tmp_path)
    scripts = root / "behavior_packs" / "guardian_robot_BP" / "scripts"
    (scripts / "main.js").write_text("// editado a mano\n", encoding="utf-8")

    r = subprocess.run([sys.executable, str(root / "tools" / "update_items_v2.py")],
                       capture_output=True, text=True, timeout=60)

    assert r.returncode == 0, r.stdout + r.stderr
    respaldos = [p for p in scripts.iterdir() if p.name.startswith("main.js.respaldo_")]
    assert len(respaldos) == 1
    assert respaldos[0].read_text(encoding="utf-8") == "// editado a mano\n"
    assert "registerCustomComponent" in (scripts / "main.js").read_text(encoding="utf-8")


def test_update_items_v2_sin_el_addon_sale_con_error_claro(tmp_path):
    """Sin behavior_packs/guardian_robot_BP moria con FileNotFoundError (traceback)."""
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    shutil.copyfile(os.path.join(BASE_DIR, "tools", "update_items_v2.py"), tools_dir / "update_items_v2.py")

    r = subprocess.run([sys.executable, str(tools_dir / "update_items_v2.py")],
                       capture_output=True, text=True, timeout=60)

    assert r.returncode == 1
    assert "Traceback" not in r.stderr
    assert "guardian_robot_BP" in r.stdout
    assert not (tmp_path / "behavior_packs").exists()
