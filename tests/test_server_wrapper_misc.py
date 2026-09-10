# -*- coding: utf-8 -*-
"""Unitarios sueltos del wrapper: send_command, read_stdout con error y backup final."""


import server_wrapper as sw
import wrapper_state as wstate


class _StdinRoto:
    def write(self, _s):
        raise BrokenPipeError("tuberia rota")

    def flush(self):
        pass


class _StdoutRoto:
    def __init__(self):
        self.llamadas = 0

    def readline(self):
        self.llamadas += 1
        if self.llamadas == 1:
            raise OSError("lectura rota")
        return ""


# ── send_command ──────────────────────────────────────────────────────
def test_send_command_sin_proceso_no_lanza(monkeypatch):
    monkeypatch.setattr(wstate, "server_process", None)
    sw.send_command("list")  # no debe lanzar


def test_send_command_con_stdin_roto_no_lanza(monkeypatch):
    class _Proc:
        stdin = _StdinRoto()

        def poll(self):
            return None

    monkeypatch.setattr(wstate, "server_process", _Proc())
    sw.send_command("list")  # no debe lanzar


def test_send_command_escribe_comando_nueva_linea(monkeypatch):
    escrituras = []

    class _Stdin:
        def write(self, s):
            escrituras.append(s)

        def flush(self):
            pass

    class _Proc:
        stdin = _Stdin()

        def poll(self):
            return None

    monkeypatch.setattr(wstate, "server_process", _Proc())
    sw.send_command("say hola")

    assert escrituras == ["say hola\n"]


# ── read_stdout con excepcion ─────────────────────────────────────────
def test_read_stdout_sobrevive_a_error_de_lectura(monkeypatch, capsys):
    class _Proc:
        stdout = _StdoutRoto()

    monkeypatch.setattr(wstate, "server_process", _Proc())
    sw.read_stdout()  # la excepcion se loguea y el EOF posterior corta el loop

    salida = capsys.readouterr().out
    assert "Error en read_stdout" in salida or "Error in read_stdout" in salida


# ── execute_final_backup ──────────────────────────────────────────────
def test_execute_final_backup_sin_zip_avisa(monkeypatch, capsys):
    monkeypatch.setattr(sw.auto_backup, "create_backup", lambda *a, **k: False)

    sw.execute_final_backup("cierre")

    salida = capsys.readouterr().out.lower()
    assert "no produjo un zip válido" in salida or "did not produce a valid zip" in salida


def test_execute_final_backup_con_excepcion_avisa(monkeypatch, capsys):
    def _boom(*_a, **_k):
        raise RuntimeError("boom del cierre")

    monkeypatch.setattr(sw.auto_backup, "create_backup", _boom)

    sw.execute_final_backup("cierre")

    salida = capsys.readouterr().out.lower()
    assert "falló el backup final" in salida or "final backup failed" in salida
