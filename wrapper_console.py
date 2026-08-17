"""Patrones y parsers puros del log de Bedrock Dedicated Server."""

import re


# Strings ingleses que BDS imprime en el log. Si Mojang cambia el formato,
# la deteccion falla silenciosamente: se pierden jugadores y save query.
BDS_PLAYER_CONNECTED = "Player connected:"
BDS_PLAYER_DISCONNECTED = "Player disconnected:"
BDS_SAVE_READY = "Data saved. Files are now ready to be copied."
BDS_PLAYERS_LIST_HEAD = "players online:"
_RE_PLAYER_CONNECT = re.compile(
    r"^Player\s+connected\s*:\s*(.+?),\s*xuid\s*:\s*(\d+)",
    re.IGNORECASE,
)
_RE_PLAYER_DISCONNECT = re.compile(
    r"^Player\s+disconnected\s*:\s*(.+?),\s*xuid\s*:\s*(\d+)",
    re.IGNORECASE,
)
_RE_PLAYERS_LIST = re.compile(r"^There are (\d+)/\d+ players online:(.*)")
_RE_VERSION = re.compile(r"Version:\s*(\d+\.\d+\.\d+\.\d+)")


def _strip_log_prefix(line):
    """Elimina prefijos estandar de timestamp/nivel de log de BDS."""
    if not line:
        return ""
    return re.sub(
        r'^(?:(?:\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}:\d{3} '
        r'(?:INFO|WARN|ERROR|DEBUG|LOG)\]|\[(?:INFO|WARN|ERROR|DEBUG|LOG)\]) +)+',
        '',
        line,
    )


def parse_save_query_files(line):
    """Extrae pares (ruta_relativa, bytes) de una linea de save query."""
    stripped = _strip_log_prefix(line).strip()
    if not stripped or stripped.startswith("<") or ":" not in stripped:
        return []

    parsed = []
    for rel_path, size_str in re.findall(r"([^,\r\n]+?):(\d+)", stripped):
        clean_rel = rel_path.strip()
        if clean_rel:
            parsed.append((clean_rel, int(size_str)))
    return parsed
