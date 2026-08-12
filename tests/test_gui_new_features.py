# -*- coding: utf-8 -*-
"""
Tests de los endpoints nuevos de la GUI: editor de server.properties,
verificacion de integridad de backups y metrica de disco.
"""
import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
import server_gui_server as sgs


@pytest.fixture
def props_client(monkeypatch, tmp_path):
    """Cliente con PROPS_PATH apuntando a un server.properties temporal."""
    props = tmp_path / "server.properties"
    props.write_text(
        "# Comentario de ejemplo que debe preservarse\n"
        "server-name=Servidor de Prueba\n"
        "# gamemode=creative\n"
        "gamemode=survival\n"
        "difficulty=normal\n"
        "max-players=20\n"
        "server-port=19132\n"
        "# allow-cheats=false\n"
        "online-mode=true\n"
        "\n"
        "# ultima linea\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sgs, "PROPS_PATH", str(props))
    with TestClient(sgs.app, client=("127.0.0.1", 50000)) as c:
        yield c, props


# ── GET ─────────────────────────────────────────────────────────────
def test_props_get_devuelve_solo_claves_activas(props_client):
    c, _ = props_client
    j = c.get("/api/server_properties").json()
    assert j["fields"]["gamemode"] == "survival"
    assert j["fields"]["server-name"] == "Servidor de Prueba"
    assert j["fields"]["max-players"] == "20"
    assert "allow-cheats" not in j["fields"], "clave comentada no debe listarse"
    assert isinstance(j["server_running"], bool)


# ── POST: validacion ─────────────────────────────────────────────────
@pytest.mark.parametrize("values", [
    {"gamemode": "supervivencia"},
    {"max-players": "0"},
    {"max-players": "1000"},
    {"server-port": "99999"},
    {"view-distance": "3"},
    {"allow-cheats": "si"},
    {"campo-inexistente": "x"},
])
def test_props_post_rechaza_invalidos(props_client, values):
    c, _ = props_client
    r = c.post("/api/server_properties", json={"values": values})
    assert r.status_code == 400, values


def test_props_post_rechaza_no_dict_y_no_texto(props_client):
    c, _ = props_client
    assert c.post("/api/server_properties", json={"values": []}).status_code == 400
    assert c.post("/api/server_properties", json={"values": {"max-players": 20}}).status_code == 400
    assert c.post("/api/server_properties", json={}).status_code == 400


# ── POST: escritura que preserva el archivo ──────────────────────────
def test_props_post_actualiza_y_preserva_resto(props_client):
    c, props = props_client
    r = c.post("/api/server_properties", json={
        "values": {"gamemode": "creative", "max-players": "30", "allow-cheats": "true"}
    })
    assert r.status_code == 200
    assert r.json()["restart_required"] is True
    texto = props.read_text(encoding="utf-8")
    # actualizadas en su sitio
    assert "gamemode=creative" in texto
    assert "max-players=30" in texto
    # la clave comentada se anade al final (activandola)
    assert "allow-cheats=true" in texto
    # comentarios y claves ajenas preservados
    assert "# Comentario de ejemplo que debe preservarse" in texto
    assert "online-mode=true" in texto
    assert "server-port=19132" in texto
    # la linea comentada original sigue ahi
    assert "# allow-cheats=false" in texto


def test_props_post_idempotente(props_client):
    c, props = props_client
    body = {"values": {"difficulty": "hard"}}
    assert c.post("/api/server_properties", json=body).status_code == 200
    assert c.post("/api/server_properties", json=body).status_code == 200
    assert props.read_text(encoding="utf-8").count("difficulty=hard") == 1


# ── verify ───────────────────────────────────────────────────────────
@pytest.fixture
def verify_client(monkeypatch, tmp_path):
    (tmp_path / "ok.zip").write_bytes(b"PK")
    (tmp_path / "no_zip.zip").write_bytes(b"")
    with zipfile.ZipFile(tmp_path / "ok_real.zip", "w") as zf:
        zf.writestr("level.dat", b"BUENOS DATOS" * 100)
    # zip corrupto: cabecera valida, CRC roto
    zpath = tmp_path / "corrupto.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("db/CURRENT", b"MANIFEST" * 10)
    raw = zpath.read_bytes()
    zpath.write_bytes(raw[:-1])  # truncar -> testzip falla
    monkeypatch.setattr(sgs.auto_backup, "BACKUP_DIR", str(tmp_path))
    with TestClient(sgs.app, client=("127.0.0.1", 50000)) as c:
        yield c


def test_verify_ok(verify_client):
    c = verify_client
    r = c.post("/api/backups/ok_real.zip/verify")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_verify_corrupto(verify_client):
    c = verify_client
    r = c.post("/api/backups/corrupto.zip/verify")
    assert r.status_code == 200
    assert r.json()["status"] == "corrupt"
    assert r.json()["entry"]


def test_verify_no_existe_y_traversal(verify_client):
    c = verify_client
    assert c.post("/api/backups/noexiste.zip/verify").status_code == 404
    assert c.post("/api/backups/..%2Fserver_gui_server.py/verify").status_code == 404
    assert c.post("/api/backups/sub%2Fdir.zip/verify").status_code == 404


# ── disco en las metricas ────────────────────────────────────────────
def test_hardware_metrics_incluye_disco():
    h = sgs.get_hardware_metrics()
    for k in ("disk_total_gb", "disk_free_gb", "disk_used_pct"):
        assert k in h, f"falta {k}"
        assert isinstance(h[k], (int, float))
    assert h["disk_free_gb"] > 0
    assert 0 <= h["disk_used_pct"] <= 100
