"""Contenido del ZIP de la suite frente a las instalaciones publicadas (2026-10-21).

Al preparar 2.2.0, el ZIP salió sin backup_location.py: el empaquetador solo
incluye lo que acepta suite_release.managed_path y ese módulo raíz no estaba en
ROOT_FILES, así que la suite no habría arrancado. Añadirlo a la lista no basta:
una instalación 2.1.x valida la actualización con SU propia lista
(extract_package/validate_manifest) y rechaza el ZIP entero si trae un archivo
raíz que no conoce. El código nuevo va en gui_backend/, que esas versiones ya
aceptan.
"""

import ast
import glob
import os

import suite_release

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Listas de suite_release.py en 2.1.0 y 2.1.1 (idénticas). Las instalaciones
# con esas versiones solo aceptan estos nombres en la raíz y en tools/.
ROOT_FILES_2_1 = frozenset("""addon_inventory.py addon_inventory_cli.py auto_backup.py
backup_worker.py console_lang.py restore_backup.py restore_core.py server_gui_server.py
server_properties.py server_wrapper.py suite_version.py suite_release.py suite_updater.py
windows_process_guard.py wrapper_backup.py wrapper_console.py wrapper_events.py
wrapper_schedule.py wrapper_state.py zip_safety.py iniciar_gui.bat iniciar_gui_lan.bat
iniciar_servidor.bat configurar_antivirus.bat configurar_firewall.bat Recuperar_suite.bat
requirements.txt version.json server.properties.example README.md CHANGELOG.md LICENSE
LEEME_WINDOWS.txt suite_release_manifest.json""".split())
TOOL_FILES_2_1 = frozenset("""bds_first_run.py enable_beta_apis.py enable_beta_apis_v2.py
update_items.py update_items_v2.py verify_backups.py setup_defender_exclusions.ps1""".split())


def _rel(path):
    return os.path.relpath(path, RAIZ).replace(os.sep, "/")


def _modulos_del_paquete():
    candidatos = (glob.glob(os.path.join(RAIZ, "*.py"))
                  + glob.glob(os.path.join(RAIZ, "gui_backend", "**", "*.py"), recursive=True)
                  + glob.glob(os.path.join(RAIZ, "tools", "*.py")))
    return sorted(rel for rel in map(_rel, candidatos) if suite_release.managed_path(rel))


def _importados(rel):
    with open(os.path.join(RAIZ, rel), encoding="utf-8") as fh:
        arbol = ast.parse(fh.read(), rel)
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            yield from (alias.name for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0 and nodo.module:
            yield nodo.module
            yield from (f"{nodo.module}.{alias.name}" for alias in nodo.names)


def test_el_zip_incluye_todo_modulo_que_importa_el_programa():
    faltan = set()
    for rel in _modulos_del_paquete():
        carpeta = os.path.dirname(rel)
        for nombre in _importados(rel):
            ruta = nombre.replace(".", "/") + ".py"
            # Los scripts de tools/ también importan a sus vecinos.
            for candidato in {ruta, f"{carpeta}/{ruta}" if carpeta else ruta}:
                if os.path.isfile(os.path.join(RAIZ, candidato)) and not suite_release.managed_path(candidato):
                    faltan.add(f"{candidato} (importado desde {rel})")
    assert not faltan, f"El ZIP no incluiría estos módulos: {sorted(faltan)}"


def test_las_instalaciones_2_1_aceptan_los_archivos_del_zip():
    nuevos = (suite_release.ROOT_FILES - ROOT_FILES_2_1) | {
        "tools/" + name for name in suite_release.TOOL_FILES - TOOL_FILES_2_1}
    assert not nuevos, (
        f"2.1.x rechazaría la actualización entera por {sorted(nuevos)}: "
        "poner el código nuevo en gui_backend/")


def test_el_modulo_de_la_carpeta_de_backups_viaja_en_el_zip():
    assert "gui_backend/backup_location.py" in _modulos_del_paquete()
    assert not os.path.exists(os.path.join(RAIZ, "backup_location.py"))
