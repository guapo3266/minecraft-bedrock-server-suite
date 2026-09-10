# -*- coding: utf-8 -*-
"""classify_log_line: coloreado/estado del log del wrapper.

Fija la prioridad de las ramas (chat, jugadores, backup, error) y el gate
anti-spoofing de lineas de chat.
"""
import pytest

from gui_backend import supervisor


@pytest.mark.parametrize("line,esperado", [
    ("<Ana> hola", "info"),
    ("<Ana> Player connected: falso, xuid: 9", "info"),  # anti-spoofing: chat gana
    ("Player connected: Ana, xuid: 12345", "join"),
    ("[2026-09-10 04:00:00:123 INFO] Player connected: Ana, xuid: 12345", "join"),
    ("Player disconnected: Ana, xuid: 12345", "leave"),
    ("Starting compression in a separate process (subprocess)...", "backup"),
    ("[Wrapper] Backup finalizado", "backup"),
    ("save query", "backup"),
    ("[ERROR] algo fallo", "error"),
    ("WARN: cuidado", "error"),
    ("[Wrapper] Excepcion inesperada", "error"),
    ("linea normal del servidor", "info"),
])
def test_classify_log_line(line, esperado):
    assert supervisor.classify_log_line(line) == esperado
