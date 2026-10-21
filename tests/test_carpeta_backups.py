# -*- coding: utf-8 -*-
"""Carpeta de backups configurable (2026-10-20): backup_location, GUI y CLI.

Sin ajuste rige la ruta historica (H3). Con ajuste, los backups van a
<raiz>\\<servidor>; dentro de la instalacion solo bajo backups\\ (guardada
relativa). Todo sobre instalaciones en tmp_path: nunca la real.
"""
import json
import os
import re
import shutil
import zipfile

import pytest

import auto_backup
from gui_backend import backup_location as bl
import restore_backup

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _instalacion(tmp_path, nombre="Srv"):
    base = tmp_path / "a" / "b" / nombre
    mundo = base / "worlds" / "W"
    mundo.mkdir(parents=True)
    (mundo / "level.dat").write_bytes(b"LEVEL")
    (base / "server.properties").write_text("level-name=W\n", encoding="utf-8")
    return str(base)


def _ajuste(base):
    with open(bl.settings_path(base), encoding="utf-8") as fh:
        return json.load(fh)


def _junction(link, target):
    import _winapi
    _winapi.CreateJunction(str(target), str(link))


# ── Resolucion ───────────────────────────────────────────────────────────
def test_sin_ajuste_es_la_ruta_historica(tmp_path):
    base = _instalacion(tmp_path)
    esperado = os.path.abspath(os.path.join(
        base, "..", "..", "Backups_Minecraft", "auto_backups", "Srv"))

    assert bl.resolve_backup_dir(base) == esperado
    info = bl.describe(base)
    assert info["backup_dir"] == esperado
    assert info["default_backup_dir"] == esperado
    assert info["custom"] is False and info["setting_error"] is None


def test_raiz_absoluta_usa_la_subcarpeta_del_servidor(tmp_path):
    base = _instalacion(tmp_path)
    raiz = str(tmp_path / "Externo" / "Backups")

    destino = bl.save_root(base, raiz)

    assert destino == os.path.join(raiz, "Srv")
    assert os.path.isdir(destino)
    assert os.listdir(destino) == []  # la prueba de escritura no deja rastro
    assert bl.resolve_backup_dir(base) == destino
    assert _ajuste(base) == {"backup_root": raiz}
    info = bl.describe(base)
    assert info["custom"] is True and info["portable"] is False and info["exists"] is True


def test_dos_instalaciones_con_la_misma_raiz_no_comparten_carpeta(tmp_path):
    a = _instalacion(tmp_path / "x", "ServidorA")
    b = _instalacion(tmp_path / "y", "ServidorB")
    raiz = str(tmp_path / "Comun")

    assert bl.save_root(a, raiz) != bl.save_root(b, raiz)


def test_raiz_bajo_backups_se_guarda_relativa_y_viaja_con_la_instalacion(tmp_path):
    base = _instalacion(tmp_path)
    destino = bl.save_root(base, os.path.join(base, "backups", "zips"))

    assert _ajuste(base) == {"backup_root": os.path.join("backups", "zips")}
    assert destino == os.path.join(base, "backups", "zips", "Srv")
    assert bl.describe(base)["portable"] is True

    movida = tmp_path / "otro_disco" / "Srv"
    shutil.copytree(base, movida)
    assert bl.resolve_backup_dir(str(movida)) == os.path.join(str(movida), "backups", "zips", "Srv")


@pytest.mark.parametrize("ruta, codigo", [
    ("relativa", "not_absolute"),
    ("C:relativa", "not_absolute"),
    ("\\carpeta", "not_absolute"),
    ("\\\\?\\C:\\x", "invalid_path"),
    ("\\\\.\\C:\\x", "invalid_path"),
    ("D:\\a\\..\\b", "invalid_path"),
    ("D:\\CON\\x", "invalid_path"),
    ("D:\\nul.txt", "invalid_path"),
    ("D:\\punto.", "invalid_path"),
    ("D:\\espacio \\x", "invalid_path"),
    ("D:\\db\\a.ldb:stream", "invalid_path"),
    ("D:\\a|b", "invalid_path"),
    ("D:\\a\x01b", "invalid_path"),
    ("D:\\" + "x" * 200, "too_long"),
])
def test_rutas_mal_formadas(tmp_path, ruta, codigo):
    base = _instalacion(tmp_path)
    with pytest.raises(bl.InvalidBackupRoot) as exc:
        bl.save_root(base, ruta)
    assert exc.value.code == codigo
    assert not os.path.exists(bl.settings_path(base))


@pytest.mark.parametrize("relativa, codigo", [
    (".", "inside_installation"),
    ("worlds", "inside_installation"),
    (os.path.join("worlds", "W"), "inside_installation"),
    ("resource_packs", "inside_installation"),
    ("data", "inside_installation"),
    ("..", "contains_installation"),
])
def test_dentro_de_la_instalacion_solo_backups(tmp_path, relativa, codigo):
    base = _instalacion(tmp_path)
    with pytest.raises(bl.InvalidBackupRoot) as exc:
        bl.save_root(base, os.path.normpath(os.path.join(base, relativa)))
    assert exc.value.code == codigo


def test_no_acepta_tipos_que_no_son_texto(tmp_path):
    base = _instalacion(tmp_path)
    for valor in (5, ["D:\\x"], {"a": 1}, True):
        with pytest.raises(bl.InvalidBackupRoot) as exc:
            bl.save_root(base, valor)
        assert exc.value.code == "invalid_path"


def test_un_archivo_en_lugar_de_la_carpeta(tmp_path):
    base = _instalacion(tmp_path)
    raiz = tmp_path / "Externo"
    raiz.mkdir()
    (raiz / "Srv").write_bytes(b"no soy una carpeta")

    with pytest.raises(bl.InvalidBackupRoot) as exc:
        bl.save_root(base, str(raiz))
    assert exc.value.code == "not_a_directory"


def test_carpeta_no_escribible(tmp_path, monkeypatch):
    base = _instalacion(tmp_path)

    def _sin_permiso(*_a, **_k):
        raise PermissionError("acceso denegado")

    monkeypatch.setattr(bl.os, "makedirs", _sin_permiso)
    with pytest.raises(bl.InvalidBackupRoot) as exc:
        bl.save_root(base, str(tmp_path / "Protegida"))
    assert exc.value.code == "not_writable"
    assert not os.path.exists(bl.settings_path(base))


def test_vacio_o_la_predeterminada_vuelven_al_default(tmp_path):
    base = _instalacion(tmp_path)
    bl.save_root(base, str(tmp_path / "Externo"))
    default = bl.describe(base)["default_backup_dir"]

    for valor in ("", "   ", None, bl.default_root(base), bl.default_root(base).upper() + "\\"):
        bl.save_root(base, str(tmp_path / "Externo"))
        assert bl.save_root(base, valor) == default
        assert _ajuste(base) == {"backup_root": None}
        assert bl.describe(base)["custom"] is False


@pytest.mark.parametrize("contenido, codigo", [
    ("{", "unreadable_setting"),
    (json.dumps({"backup_root": "worlds"}), "inside_installation"),
    (json.dumps({"backup_root": "backups\\..\\worlds"}), "invalid_path"),
    (json.dumps({"backup_root": 5}), "invalid_path"),
    (json.dumps({"backup_root": "D:\\CON"}), "invalid_path"),
])
def test_ajuste_ilegible_o_invalido_usa_el_default(tmp_path, contenido, codigo):
    base = _instalacion(tmp_path)
    os.makedirs(os.path.dirname(bl.settings_path(base)))
    with open(bl.settings_path(base), "w", encoding="utf-8") as fh:
        fh.write(contenido)

    info = bl.describe(base)
    assert info["custom"] is False
    assert info["setting_error"] == codigo
    assert bl.resolve_backup_dir(base) == info["default_backup_dir"]


@pytest.fixture
def junctions():
    if os.name != "nt":
        pytest.skip("junctions de Windows")
    creadas = []
    yield creadas
    for link in creadas:
        os.rmdir(link)  # quita la junction, no su destino


def test_junction_hacia_worlds_no_cuela_los_backups(tmp_path, junctions):
    base = _instalacion(tmp_path)
    link = tmp_path / "Parece_externa"
    _junction(link, os.path.join(base, "worlds"))
    junctions.append(link)

    with pytest.raises(bl.InvalidBackupRoot) as exc:
        bl.save_root(base, str(link))
    assert exc.value.code == "inside_installation"


def test_subcarpeta_del_servidor_como_junction_no_cuela_los_backups(tmp_path, junctions):
    base = _instalacion(tmp_path)
    os.makedirs(os.path.join(base, "backups"))
    link = os.path.join(base, "backups", "Srv")
    _junction(link, os.path.join(base, "worlds"))
    junctions.append(link)

    with pytest.raises(bl.InvalidBackupRoot) as exc:
        bl.save_root(base, os.path.join(base, "backups"))
    assert exc.value.code == "inside_installation"


# ── Consumidores: auto_backup (wrapper y GUI) y la CLI ─────────────────────
def test_get_backup_dir_toma_el_cambio_en_caliente(tmp_path, monkeypatch):
    base = _instalacion(tmp_path)
    monkeypatch.setattr(auto_backup, "BASE_DIR", base)
    antes = auto_backup.get_backup_dir()
    assert antes == bl.describe(base)["default_backup_dir"]

    nueva = bl.save_root(base, str(tmp_path / "Externo"))

    assert auto_backup.get_backup_dir() == nueva


def test_un_global_parcheado_sigue_mandando(tmp_path, monkeypatch):
    base = _instalacion(tmp_path)
    bl.save_root(base, str(tmp_path / "Externo"))
    monkeypatch.setattr(auto_backup, "BASE_DIR", base)
    monkeypatch.setattr(auto_backup, "BACKUP_DIR", str(tmp_path / "parche"))

    assert auto_backup.get_backup_dir() == str(tmp_path / "parche")


def test_la_cli_usa_la_misma_carpeta(tmp_path, monkeypatch):
    base = _instalacion(tmp_path)
    nueva = bl.save_root(base, str(tmp_path / "Externo"))
    monkeypatch.setattr(restore_backup, "BASE_DIR", base)
    monkeypatch.setattr(auto_backup, "BASE_DIR", base)

    assert restore_backup.get_backup_dir() == nueva == auto_backup.get_backup_dir()


def test_create_backup_escribe_en_la_carpeta_elegida(tmp_path, monkeypatch):
    base = _instalacion(tmp_path)
    nueva = bl.save_root(base, str(tmp_path / "Externo"))
    monkeypatch.setattr(auto_backup, "BASE_DIR", base)
    monkeypatch.setattr(auto_backup, "get_world_dir", lambda base_dir=None: os.path.join(base, "worlds", "W"))

    auto_backup.create_backup("manual")

    zips = [n for n in os.listdir(nueva) if n.endswith(".zip")]
    assert len(zips) == 1, os.listdir(nueva)
    with zipfile.ZipFile(os.path.join(nueva, zips[0])) as zf:
        assert "level.dat" in zf.namelist()
    assert not os.path.exists(bl.describe(base)["default_backup_dir"])


# ── API de la GUI ─────────────────────────────────────────────────────────
@pytest.fixture
def api(tmp_path, monkeypatch):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    import server_gui_server as sgs
    from gui_backend.state import manager

    base = _instalacion(tmp_path)
    monkeypatch.setattr(auto_backup, "BASE_DIR", base)
    monkeypatch.setattr(manager, "is_running", False)
    monkeypatch.setattr(manager, "backup_in_progress", False)
    client = TestClient(sgs.app, client=("127.0.0.1", 50000), raise_server_exceptions=False)
    return client, base, manager


def test_api_get_describe_la_carpeta(api):
    client, base, _manager = api
    r = client.get("/api/backups/location")
    assert r.status_code == 200
    assert r.json() == bl.describe(base)


def test_api_post_cambia_la_carpeta_y_el_listado_la_sigue(api, tmp_path):
    client, base, _manager = api
    vieja = bl.resolve_backup_dir(base)
    os.makedirs(vieja)
    for i in range(2):
        with zipfile.ZipFile(os.path.join(vieja, f"auto_backup_Srv_x_{i}.zip"), "w") as zf:
            zf.writestr("level.dat", b"X")
    raiz = str(tmp_path / "Externo")

    r = client.post("/api/backups/location", json={"root": raiz})

    assert r.status_code == 200, r.text
    data = r.json()
    nueva = os.path.join(raiz, "Srv")
    assert data["location"]["backup_dir"] == nueva
    assert data["previous_backup_dir"] == vieja
    assert data["left_behind"] == 2
    assert client.get("/api/backups").json()["backups"] == []

    with zipfile.ZipFile(os.path.join(nueva, "auto_backup_Srv_y.zip"), "w") as zf:
        zf.writestr("level.dat", b"Y")
    assert [b["filename"] for b in client.get("/api/backups").json()["backups"]] == ["auto_backup_Srv_y.zip"]
    assert client.get("/api/backups/auto_backup_Srv_y.zip/download").status_code == 200

    r = client.post("/api/backups/location", json={"root": None})
    assert r.status_code == 200
    assert r.json()["location"]["backup_dir"] == vieja
    assert r.json()["left_behind"] == 1


def test_api_post_ruta_invalida_da_el_codigo(api):
    client, base, _manager = api
    r = client.post("/api/backups/location", json={"root": os.path.join(base, "worlds")})
    assert r.status_code == 400
    assert r.json()["detail"] == "inside_installation"
    assert bl.describe(base)["custom"] is False


@pytest.mark.parametrize("body", [[], "D:\\x", 5])
def test_api_post_cuerpo_que_no_es_objeto(api, body):
    client, _base, _manager = api
    assert client.post("/api/backups/location", json=body).status_code == 400


def test_api_post_rechaza_con_backup_en_curso(api, tmp_path, monkeypatch):
    client, base, manager = api
    monkeypatch.setattr(manager, "backup_in_progress", True)
    r = client.post("/api/backups/location", json={"root": str(tmp_path / "Externo")})
    assert r.status_code == 409 and r.json()["detail"] == "backup_in_progress"
    assert not os.path.exists(bl.settings_path(base))


def test_api_post_rechaza_con_otra_operacion_en_curso(api, tmp_path):
    client, base, manager = api
    assert manager.op_lock.acquire(blocking=False)
    try:
        r = client.post("/api/backups/location", json={"root": str(tmp_path / "Externo")})
    finally:
        manager.op_lock.release()
    assert r.status_code == 409 and r.json()["detail"] == "busy"
    assert not os.path.exists(bl.settings_path(base))


# ── Anti-drift ────────────────────────────────────────────────────────────
def _codigos_de_la_api():
    with open(os.path.join(RAIZ, "gui_backend", "backup_location.py"), encoding="utf-8") as fh:
        propios = set(re.findall(r'InvalidBackupRoot\("([a-z_]+)"\)', fh.read()))
    with open(os.path.join(RAIZ, "gui_backend", "services", "backups.py"), encoding="utf-8") as fh:
        servicio = set(re.findall(r'detail="([a-z_]+)"', fh.read()))
    return propios | servicio


def test_la_gui_conoce_todos_los_codigos_de_error():
    with open(os.path.join(RAIZ, "gui_frontend", "src", "backupLocationLogic.js"), encoding="utf-8") as fh:
        js = fh.read()
    lista = re.search(r"BACKUP_LOCATION_ERRORS = \[(.*?)\]", js, re.S).group(1)
    en_la_gui = set(re.findall(r"'([a-z_]+)'", lista))
    codigos = _codigos_de_la_api()

    assert {"invalid_path", "busy", "backup_in_progress"} <= codigos
    assert codigos == en_la_gui


def test_el_script_del_antivirus_lee_el_mismo_ajuste():
    with open(os.path.join(RAIZ, "tools", "setup_defender_exclusions.ps1"), encoding="utf-8") as fh:
        ps1 = fh.read()
    assert "data\\backup_location.json" in ps1
    assert f"$location.{bl.SETTING_KEY}" in ps1
