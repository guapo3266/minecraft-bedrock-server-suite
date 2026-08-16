"""Vista de jugadores: registro propio + permissions.json + allowlist.json (lectura).

Las mutaciones de permisos y allowlist se hacen con comandos de consola de
BDS (op/deop, allowlist add/remove) via /api/command: BDS escribe sus
archivos, resuelve el xuid y aplica al vuelo. Este modulo nunca los escribe.
"""

import json
import os

from gui_backend import config
from gui_backend.supervisor import load_known_players

PERMISSIONS_PATH = os.path.join(config.BASE_DIR, "permissions.json")
ALLOWLIST_PATH = os.path.join(config.BASE_DIR, "allowlist.json")

VALID_PERMISSIONS = ("operator", "member", "visitor")


def _read_json_list(path):
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, list) else []
    except (OSError, ValueError):
        return []


def _permission_by_xuid():
    perms = {}
    for entry in _read_json_list(PERMISSIONS_PATH):
        if isinstance(entry, dict) and entry.get("xuid") is not None:
            perm = str(entry.get("permission", "")).lower()
            if perm in VALID_PERMISSIONS:
                perms[str(entry["xuid"])] = perm
    return perms


def _allowlisted_names_and_xuids():
    names, xuids = set(), set()
    for entry in _read_json_list(ALLOWLIST_PATH):
        if not isinstance(entry, dict):
            continue
        if entry.get("name"):
            names.add(str(entry["name"]))
        if entry.get("xuid"):
            xuids.add(str(entry["xuid"]))
    return names, xuids


def _allow_list_enabled():
    try:
        with open(config.PROPS_PATH, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("allow-list="):
                    return stripped.split("=", 1)[1].strip().lower() == "true"
    except OSError:
        pass
    return False


def build_players_view(online_players):
    """Ensambla la vista de GET /api/players (nunca lanza; archivos ausentes
    o corruptos se leen como vacios)."""
    known = load_known_players()
    perms = _permission_by_xuid()
    al_names, al_xuids = _allowlisted_names_and_xuids()
    online = list(online_players)
    online_set = set(online)

    entries = []
    for name, info in known.items():
        info = info if isinstance(info, dict) else {}
        xuid = str(info.get("xuid") or "")
        entries.append({
            "name": name,
            "xuid": xuid,
            "permission": perms.get(xuid, "default") if xuid else "default",
            "allowlisted": name in al_names or (bool(xuid) and xuid in al_xuids),
            "first_seen": info.get("first_seen", ""),
            "last_seen": info.get("last_seen", ""),
            "online": name in online_set,
        })
    # Online sin registro todavia (p. ej. registro recien creado a mano)
    for name in online:
        if name not in known:
            entries.append({
                "name": name, "xuid": "", "permission": "default",
                "allowlisted": False, "first_seen": "", "last_seen": "",
                "online": True,
            })
    entries.sort(key=lambda e: (not e["online"], e["name"].lower()))
    return {
        "online": online,
        "known": entries,
        "allow_list_enabled": _allow_list_enabled(),
    }
