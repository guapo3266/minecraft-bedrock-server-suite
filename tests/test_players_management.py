# -*- coding: utf-8 -*-
"""Gestion de jugadores: xuid en regexes, registro known_players y GET /api/players.

Las mutaciones de permisos/allowlist NO se testean aqui a proposito: las hace
BDS con sus comandos de consola (op/deop/allowlist) via /api/command, que ya
esta cubierto por la suite. El backend solo LEE esos archivos.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server_wrapper as sw
import server_gui_server as gui
import gui_backend.config as config
import gui_backend.supervisor as supervisor
import gui_backend.services.players as players_service


def _reset_manager_state():
    gui.manager.is_running = False
    gui.manager.start_time = None
    gui.manager.wrapper_process = None
    gui.manager.update_in_progress = False
    gui.manager.backup_in_progress = False
    gui.manager.players_online.clear()
    gui.manager.players_xuid.clear()
    gui.manager.wrapper_exit_event.set()
    gui.manager.server_stopped_event.set()


def _patch_paths(monkeypatch, tmp_path):
    known = os.path.join(str(tmp_path), "known_players.json")
    perms = os.path.join(str(tmp_path), "permissions.json")
    allow = os.path.join(str(tmp_path), "allowlist.json")
    props = os.path.join(str(tmp_path), "server.properties")
    monkeypatch.setattr(supervisor, "KNOWN_PLAYERS_PATH", known)
    monkeypatch.setattr(players_service, "PERMISSIONS_PATH", perms)
    monkeypatch.setattr(players_service, "ALLOWLIST_PATH", allow)
    monkeypatch.setattr(config, "PROPS_PATH", props)
    return known, perms, allow, props


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


# ═══════════════════════════════════════════════════════════════════════
# Regexes: nombre (group 1) + xuid (group 2), con y sin espacio
# ═══════════════════════════════════════════════════════════════════════
def test_regex_conect_captura_nombre_y_xuid():
    m = sw._RE_PLAYER_CONNECT.search("Player connected: Bob, xuid: 12345")
    assert m and m.group(1).strip() == "Bob"
    assert m.group(2) == "12345"


def test_regex_conect_xuid_sin_espacio():
    m = sw._RE_PLAYER_CONNECT.search("Player connected: Bob, xuid:12345678901234567")
    assert m and m.group(1).strip() == "Bob"
    assert m.group(2) == "12345678901234567"


def test_regex_desconect_captura_nombre_y_xuid():
    m = sw._RE_PLAYER_DISCONNECT.search("Player disconnected: Bob, xuid: 12345")
    assert m and m.group(1).strip() == "Bob"
    assert m.group(2) == "12345"


def test_chat_no_matchea_regexes():
    # Anti-spoofing: una linea de chat nunca es evento de jugador (H-01)
    chat = "<Griefer> Player disconnected: Steve, xuid: 12345"
    assert not sw._RE_PLAYER_CONNECT.search(chat)
    assert not sw._RE_PLAYER_DISCONNECT.search(chat)


# ═══════════════════════════════════════════════════════════════════════
# Registro known_players.json
# ═══════════════════════════════════════════════════════════════════════
def test_record_player_event_crea_actualiza(monkeypatch, tmp_path):
    known, _, _, _ = _patch_paths(monkeypatch, tmp_path)
    supervisor.record_player_event("Alice", "111")
    with open(known, encoding="utf-8") as f:
        entry = json.load(f)["Alice"]
    assert entry["xuid"] == "111"
    assert entry["first_seen"] and entry["last_seen"]

    supervisor.record_player_event("Alice", "222")  # xuid cambia, first_seen no
    with open(known, encoding="utf-8") as f:
        entry = json.load(f)["Alice"]
    assert entry["xuid"] == "222"
    assert entry["first_seen"]  # preservado
    # atomico: sin .tmp remanentes
    assert not [p for p in os.listdir(str(tmp_path)) if ".tmp_" in p]


def test_load_known_players_tolerante(monkeypatch, tmp_path):
    known, _, _, _ = _patch_paths(monkeypatch, tmp_path)
    assert supervisor.load_known_players() == {}  # ausente
    with open(known, "w", encoding="utf-8") as f:
        f.write("{corrupto")
    assert supervisor.load_known_players() == {}  # corrupto
    supervisor.record_player_event("Bob", "999")  # reconstruye sobre corrupto
    assert supervisor.load_known_players()["Bob"]["xuid"] == "999"


# ═══════════════════════════════════════════════════════════════════════
# Vista: merge registro + permissions.json + allowlist.json
# ═══════════════════════════════════════════════════════════════════════
def test_build_players_view_merge(monkeypatch, tmp_path):
    known, perms, allow, props = _patch_paths(monkeypatch, tmp_path)
    _write_json(known, {
        "Alice": {"xuid": "111", "first_seen": "2026-08-01 10:00:00", "last_seen": "2026-08-16 11:00:00"},
        "Bob": {"xuid": "222", "first_seen": "2026-08-02 10:00:00", "last_seen": "2026-08-15 11:00:00"},
    })
    _write_json(perms, [{"permission": "operator", "xuid": "111"}])
    _write_json(allow, [{"name": "Alice", "xuid": "111", "ignoresPlayerLimit": False}])
    with open(props, "w", encoding="utf-8") as f:
        f.write("allow-list=true\nmax-players=20\n")

    view = players_service.build_players_view(["Alice"])
    by_name = {e["name"]: e for e in view["known"]}
    assert by_name["Alice"]["permission"] == "operator"
    assert by_name["Alice"]["allowlisted"] is True
    assert by_name["Alice"]["online"] is True
    assert by_name["Bob"]["permission"] == "default"
    assert by_name["Bob"]["allowlisted"] is False
    assert by_name["Bob"]["online"] is False
    # online primero en el orden
    assert view["known"][0]["name"] == "Alice"
    assert view["allow_list_enabled"] is True
    assert view["online"] == ["Alice"]


def test_build_players_view_archivos_ausentes(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)  # nada escrito
    view = players_service.build_players_view(["Zoe"])
    # Zoe esta online sin registro: aparece con defaults
    assert view["known"] == [{
        "name": "Zoe", "xuid": "", "permission": "default", "allowlisted": False,
        "first_seen": "", "last_seen": "", "online": True,
    }]
    assert view["allow_list_enabled"] is False


def test_build_players_view_ignora_permisos_invalidos(monkeypatch, tmp_path):
    known, perms, _, _ = _patch_paths(monkeypatch, tmp_path)
    _write_json(known, {"Alice": {"xuid": "111"}})
    _write_json(perms, [
        {"permission": "wizard", "xuid": "111"},   # nivel inexistente -> ignorado
        {"permission": "member"},                   # sin xuid -> ignorado
    ])
    view = players_service.build_players_view([])
    assert view["known"][0]["permission"] == "default"


# ═══════════════════════════════════════════════════════════════════════
# Endpoint GET /api/players
# ═══════════════════════════════════════════════════════════════════════
def test_get_players_endpoint(monkeypatch, tmp_path):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    known, perms, allow, props = _patch_paths(monkeypatch, tmp_path)
    _write_json(known, {"Alice": {"xuid": "111", "last_seen": "x"}})
    _write_json(perms, [{"permission": "operator", "xuid": "111"}])

    _reset_manager_state()
    gui.manager.players_online.add("Alice")
    client = TestClient(gui.app, client=("127.0.0.1", 50000))
    r = client.get("/api/players")
    assert r.status_code == 200
    data = r.json()
    assert data["online"] == ["Alice"]
    assert data["server_running"] is False
    entry = next(e for e in data["known"] if e["name"] == "Alice")
    assert entry["permission"] == "operator"


# ═══════════════════════════════════════════════════════════════════════
# Pipeline GUI: run_wrapper_thread registra xuid y persiste
# ═══════════════════════════════════════════════════════════════════════
class _FakeStdout:
    def __init__(self, lines):
        self._lines = list(lines)

    def readline(self):
        return self._lines.pop(0) if self._lines else ""


class _FakeProc:
    def __init__(self, lines):
        self.stdout = _FakeStdout(lines)

    def wait(self):
        return 0


def test_run_wrapper_thread_registra_xuid(monkeypatch, tmp_path):
    known, _, _, _ = _patch_paths(monkeypatch, tmp_path)
    _reset_manager_state()
    lines = [
        "[INFO] Player connected: Alice, xuid: 111",
        "[INFO] <Impostor> Player connected: Malo, xuid: 666",  # chat: ignorado
        "[INFO] Player disconnected: Alice, xuid: 111",
        "",
    ]
    supervisor.run_wrapper_thread(_FakeProc(lines))

    assert gui.manager.players_xuid.get("Alice") == "111"
    assert "Malo" not in gui.manager.players_xuid  # el gate de chat lo descarto
    registry = supervisor.load_known_players()
    assert registry["Alice"]["xuid"] == "111"
    # players_online se limpia en el finally del hilo (wrapper terminado)
    assert gui.manager.players_online == set()
