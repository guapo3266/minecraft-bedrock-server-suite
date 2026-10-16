# -*- coding: utf-8 -*-
"""Ronda de fixes 2026-09-25 (auditoria de practicidad y seguridad de
mundos/archivos). Blindan los contratos nuevos de esta ronda:

- H1: timeouts de backup escalados con el tamano (nunca por debajo del base).
- H4: fsync del ZIP publicado y del staging antes del swap del restore.
- H6: GUI y CLI recuperan residuos interrumpidos antes de restaurar.
- H7: ningun backup se publica sin level.dat (tampoco el tradicional).
- H9: verificacion post-swap antes de descartar el .bak del mundo previo.
"""
import os
import threading
import zipfile

import pytest

import auto_backup as ab
import restore_core
import server_gui_server as gui
import wrapper_backup as wb
import wrapper_state as wstate
from gui_backend.state import manager


# ── H1: timeouts escalados con el tamano ────────────────────────────

def test_scaled_backup_timeout_sec_piso_escala_y_tope():
    base = wstate.WORKER_COMPRESSION_TIMEOUT_SEC
    gb = 1024 ** 3
    assert wstate.scaled_backup_timeout_sec(0, base) == base
    assert wstate.scaled_backup_timeout_sec(None, base) == base
    assert wstate.scaled_backup_timeout_sec(-5, base) == base
    assert wstate.scaled_backup_timeout_sec(100, base) == base  # piso historico
    assert wstate.scaled_backup_timeout_sec(1 * gb, base) == base + wstate.BACKUP_TIMEOUT_SEC_PER_GB
    assert wstate.scaled_backup_timeout_sec(4 * gb, base) == base + 4 * wstate.BACKUP_TIMEOUT_SEC_PER_GB
    assert wstate.scaled_backup_timeout_sec(1000 * gb, base) == wstate.BACKUP_TIMEOUT_MAX_SEC


def test_scaled_backup_timeout_sec_respeta_base_propia():
    gb = 1024 ** 3
    final = wstate.FINAL_BACKUP_TIMEOUT_SEC
    assert wstate.scaled_backup_timeout_sec(2 * gb, final) == final + 2 * wstate.BACKUP_TIMEOUT_SEC_PER_GB


def test_estimate_backup_total_bytes_cuenta_mundo_y_packs(tmp_path, monkeypatch):
    mundo = tmp_path / "worlds" / "Mundo"
    (mundo / "db").mkdir(parents=True)
    (mundo / "level.dat").write_bytes(b"L" * 100)
    (mundo / "db" / "a.ldb").write_bytes(b"D" * 50)
    packs = tmp_path / "resource_packs" / "Pack"
    packs.mkdir(parents=True)
    (packs / "manifest.json").write_bytes(b"M" * 25)
    monkeypatch.setattr(ab, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(ab, "get_world_dir", lambda base_dir=None: str(mundo))

    assert ab.estimate_backup_total_bytes() == 175


def test_estimate_backup_total_bytes_tolera_errores(monkeypatch):
    def _boom():
        raise OSError("sin acceso")

    monkeypatch.setattr(ab, "get_world_dir", _boom)
    assert ab.estimate_backup_total_bytes() == 0


def test_worker_timeout_se_escala_con_el_snapshot(monkeypatch):
    """execute_backup_worker espera al worker con timeout proporcional al
    snapshot: un snapshot de 4 GB no puede usar el 120s fijo (H1)."""
    vistos = {}

    class FakeCompProc:
        def is_alive(self):
            return False

        def join(self, timeout=None):
            vistos["timeout"] = timeout

        def kill(self):
            pass

        def wait(self, timeout=None):
            return 0

    fake = FakeCompProc()
    monkeypatch.setattr(wb.subprocess, "Popen", lambda *a, **k: object())
    monkeypatch.setattr(wb, "_WorkerProcess", lambda proc: fake)

    gb = 1024 ** 3
    wb.execute_backup_worker(file_snapshot=[("db/a.ldb", 4 * gb)], cancel_event=None)

    esperado = wstate.scaled_backup_timeout_sec(4 * gb, wstate.WORKER_COMPRESSION_TIMEOUT_SEC)
    assert vistos["timeout"] == esperado
    assert esperado > wstate.WORKER_COMPRESSION_TIMEOUT_SEC


# ── H4: fsync antes de publicar el ZIP ──────────────────────────────

def test_create_backup_fsync_antes_de_publicar(tmp_path, monkeypatch):
    mundo = tmp_path / "worlds" / "Mundo"
    mundo.mkdir(parents=True)
    (mundo / "level.dat").write_bytes(b"L" * 10)
    bkp = tmp_path / "backups"
    bkp.mkdir()
    monkeypatch.setattr(ab, "get_world_dir", lambda base_dir=None: str(mundo))
    monkeypatch.setattr(ab, "get_backup_dir", lambda base_dir=None: str(bkp))

    llamadas = {"n": 0}
    real_fsync = os.fsync

    def _fsync_cuenta(fd):
        llamadas["n"] += 1
        return real_fsync(fd)

    monkeypatch.setattr(ab.os, "fsync", _fsync_cuenta)

    result = ab.create_backup("test")

    assert result, "el backup de prueba debio publicarse"
    assert llamadas["n"] >= 1, "el ZIP debe persistirse (fsync) antes de publicarse"


# ── H7: ningun backup se publica sin level.dat ──────────────────────

def test_backup_traditional_sin_level_dat_no_publica(tmp_path, monkeypatch, capsys):
    mundo = tmp_path / "worlds" / "Mundo"
    (mundo / "db").mkdir(parents=True)
    (mundo / "db" / "CURRENT").write_bytes(b"x")
    bkp = tmp_path / "backups"
    bkp.mkdir()
    monkeypatch.setattr(ab, "get_world_dir", lambda base_dir=None: str(mundo))
    monkeypatch.setattr(ab, "get_backup_dir", lambda base_dir=None: str(bkp))

    result = ab.create_backup("test")

    assert result is False
    assert not list(bkp.glob("*.zip")), "no debe publicarse un ZIP sin level.dat (irrestaurable)"
    out = capsys.readouterr().out
    assert "level.dat" in out


# ── H9: verificacion post-swap antes de descartar el .bak ───────────

def test_restore_post_swap_sin_level_dat_hace_rollback(tmp_path, monkeypatch):
    base = tmp_path / "inst"
    mundo = base / "worlds" / "Mundo"
    mundo.mkdir(parents=True)
    (mundo / "level.dat").write_bytes(b"VIEJO")
    (mundo / "otro.txt").write_bytes(b"VIEJO2")

    zpath = tmp_path / "backup.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("level.dat", b"NUEVO")
        zf.writestr("otro.txt", b"NUEVO2")

    real_exists = os.path.exists

    def _exists_miente(path):
        # Simula un swap que dejo el mundo activo sin level.dat. Solo miente
        # sobre el mundo activo (nunca el staging ni los resguardos).
        if os.path.normcase(str(path)) == os.path.normcase(str(mundo / "level.dat")):
            return False
        return real_exists(path)

    monkeypatch.setattr(restore_core.os.path, "exists", _exists_miente)

    with pytest.raises(RuntimeError):
        restore_core.restore_from_zip(str(zpath), str(base), str(mundo))

    assert (mundo / "level.dat").read_bytes() == b"VIEJO", "el rollback no restauró el mundo previo"
    assert (mundo / "otro.txt").read_bytes() == b"VIEJO2"


# ── H6: recuperar residuos antes de restaurar (GUI y CLI) ───────────

def test_restore_backup_gui_recupera_residuos_previos(tmp_path, monkeypatch):
    bkp = tmp_path / "backups"
    bkp.mkdir()
    zpath = bkp / "auto_backup_x.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("level.dat", b"N")

    monkeypatch.setattr(ab, "get_backup_dir", lambda base_dir=None: str(bkp))
    monkeypatch.setattr(ab, "get_world_dir", lambda base_dir=None: str(tmp_path / "worlds" / "Mundo"))

    llamadas = {"n": 0}

    def _recover():
        llamadas["n"] += 1
        return []

    monkeypatch.setattr(ab, "recover_interrupted_restores", _recover)
    monkeypatch.setattr(ab.restore_core, "restore_from_zip", lambda *a, **k: str(zpath))

    assert ab.restore_backup("auto_backup_x.zip") == str(zpath)
    assert llamadas["n"] == 1, "la GUI debe recuperar residuos antes de restaurar"


def test_restore_cli_recupera_residuos_previos(tmp_path, monkeypatch):
    import restore_backup as rb

    bkp = tmp_path / "backups"
    bkp.mkdir()
    zpath = bkp / "auto_backup_x.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("level.dat", b"N")

    monkeypatch.setattr(rb, "BACKUP_DIR", str(bkp))
    monkeypatch.setattr(rb, "_server_is_running", lambda: False)
    monkeypatch.setattr(rb, "get_world_dir", lambda base_dir=None: str(tmp_path / "worlds" / "Mundo"))

    llamadas = {"n": 0}

    def _recover():
        llamadas["n"] += 1
        return []

    monkeypatch.setattr(ab, "recover_interrupted_restores", _recover)
    monkeypatch.setattr(rb.restore_core, "restore_from_zip", lambda *a, **k: str(zpath))
    respuestas = iter(["1", "SI", ""])
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(respuestas, ""))

    rb.list_and_restore()

    assert llamadas["n"] == 1, "la CLI debe recuperar residuos antes de restaurar"


# ── Hardening de nombres de backup ──────────────────────────────────

def test_is_safe_backup_name_rechaza_alias_y_acepta_normales():
    from zip_safety import is_safe_backup_name

    assert is_safe_backup_name("auto_backup_TEST_auto_2026-09-25_00-00-00_abc123.zip") is True
    assert is_safe_backup_name("x.ZIP") is True
    assert is_safe_backup_name("") is False
    assert is_safe_backup_name("..") is False
    assert is_safe_backup_name("foo.zip.") is False
    assert is_safe_backup_name("foo.zip ") is False
    assert is_safe_backup_name("sin_extension") is False
    assert is_safe_backup_name("a/b.zip") is False
    assert is_safe_backup_name("C:\\x.zip") is False
    assert is_safe_backup_name("x.zip\x00") is False
    assert is_safe_backup_name(None) is False


# ═══════════════════════════════════════════════════════════════════════
# Fase B — GUI backend (seguridad de red local, watchdog, marcadores)
# ═══════════════════════════════════════════════════════════════════════

class _FakeStdout:
    def __init__(self, lines):
        self._lines = list(lines)

    def readline(self):
        return self._lines.pop(0) if self._lines else ""


class _FakeProcStdout:
    def __init__(self, lines):
        self.stdout = _FakeStdout(lines)

    def wait(self):
        return 0


class _EventContador:
    """Cuenta set(): distingue el marcador del respaldo del finally de sesion."""

    def __init__(self):
        self.sets = 0

    def set(self):
        self.sets += 1

    def is_set(self):
        return self.sets > 0

    def clear(self):
        pass

    def wait(self, timeout=None):
        return True


def test_marcador_bds_stopped_anclado_ignora_gamertag(monkeypatch):
    """Un gamertag 'BDS stopped' en una linea de evento de jugador (no chat)
    no debe setear server_stopped_event: el marcador va anclado al inicio de
    la linea (2026-09-25). El finally de la sesion siempre suma 1 set."""
    import gui_backend.supervisor as supervisor

    monkeypatch.setattr(manager, "add_log", lambda *a, **k: None)
    monkeypatch.setattr(manager, "update_status", lambda: None)
    monkeypatch.setattr(manager, "events_file", None)
    monkeypatch.setattr(manager, "events_alive", False)
    monkeypatch.setattr(manager, "installed_version", None)
    monkeypatch.setattr(manager, "is_running", False)
    monkeypatch.setattr(manager, "wrapper_process", None)
    monkeypatch.setattr(manager, "wrapper_exit_event", threading.Event())
    monkeypatch.setattr(manager, "players_online", set())
    monkeypatch.setattr(manager, "backup_in_progress", False)
    contador = _EventContador()
    monkeypatch.setattr(manager, "server_stopped_event", contador)

    proc = _FakeProcStdout(["Player connected: BDS stopped:12345, xuid:999\n", ""])
    supervisor.run_wrapper_thread(proc)

    assert contador.sets == 1, "un gamertag spoofeando el marcador seteo el evento"
    assert manager.is_running is False


def test_marcador_bds_stopped_real_sigue_funcionando(monkeypatch):
    """El marcador legitimo del wrapper sigue seteando el evento (respaldo
    del finally + marcador = 2 sets)."""
    import gui_backend.supervisor as supervisor

    monkeypatch.setattr(manager, "add_log", lambda *a, **k: None)
    monkeypatch.setattr(manager, "update_status", lambda: None)
    monkeypatch.setattr(manager, "events_file", None)
    monkeypatch.setattr(manager, "events_alive", False)
    monkeypatch.setattr(manager, "installed_version", None)
    monkeypatch.setattr(manager, "is_running", False)
    monkeypatch.setattr(manager, "wrapper_process", None)
    monkeypatch.setattr(manager, "wrapper_exit_event", threading.Event())
    monkeypatch.setattr(manager, "players_online", set())
    monkeypatch.setattr(manager, "backup_in_progress", False)
    contador = _EventContador()
    monkeypatch.setattr(manager, "server_stopped_event", contador)

    proc = _FakeProcStdout([
        "[Wrapper] BDS stopped. Starting final shutdown cleanup...\n",
        "[Wrapper] BDS detenido. Iniciando limpieza final de cierre...\n",
        "",
    ])
    supervisor.run_wrapper_thread(proc)

    assert contador.sets == 3, "el marcador legitimo (ES/EN) dejo de setear el evento"


def test_csrf_lan_solo_acepta_el_host_de_la_gui(monkeypatch):
    """En modo LAN el Origin con IP privada solo vale si es la IP de esta GUI
    (coincide con el Host del request): una pagina servida por otro
    dispositivo de la LAN no puede hacer CSRF ni por POST ni por WS."""
    from gui_backend import security as sec

    monkeypatch.setenv("GUI_ALLOW_LAN", "1")
    # Mismo host que el request (la GUI en 192.168.1.70) -> aceptado
    assert sec._is_allowed_origin(
        "http://192.168.1.70:8000", expected_port=8000, expected_host="192.168.1.70"
    ) is True
    # Otro dispositivo de la LAN (pagina maliciosa en 192.168.1.50) -> rechazado
    assert sec._is_allowed_origin(
        "http://192.168.1.50:8000", expected_port=8000, expected_host="192.168.1.70"
    ) is False
    # Hostname externo nunca pasa (tampoco re-bindeado)
    assert sec._is_allowed_origin(
        "http://evil.com:8000", expected_port=8000, expected_host="evil.com"
    ) is False
    # Compat: sin expected_host se conserva el comportamiento historico
    assert sec._is_allowed_origin("http://192.168.1.70:8000", expected_port=8000) is True

    monkeypatch.delenv("GUI_ALLOW_LAN", raising=False)
    assert sec._is_allowed_origin(
        "http://192.168.1.70:8000", expected_port=8000, expected_host="192.168.1.70"
    ) is False, "sin GUI_ALLOW_LAN ninguna IP privada debe pasar"


def test_host_header_anti_dns_rebinding(monkeypatch):
    """S1b: el Host debe ser uno por el que se accede a la GUI; un hostname
    re-bindeado (evil.com -> 127.0.0.1) se rechaza."""
    from fastapi import HTTPException

    from gui_backend import security as sec

    assert sec._es_host_permitido("127.0.0.1") is True
    assert sec._es_host_permitido("localhost") is True
    assert sec._es_host_permitido("evil.com") is False
    assert sec._es_host_permitido(None) is False

    monkeypatch.setenv("GUI_ALLOW_LAN", "1")
    assert sec._es_host_permitido("192.168.1.70") is True
    monkeypatch.delenv("GUI_ALLOW_LAN", raising=False)
    assert sec._es_host_permitido("192.168.1.70") is False

    # Host explicito para tests/otros nombres (fixture de conftest fija "testserver")
    monkeypatch.setenv("GUI_ALLOWED_HOSTS", "mi-pc")
    assert sec._es_host_permitido("mi-pc") is True

    class _ReqFalso:
        def __init__(self, host):
            self.headers = {"host": host}

    with pytest.raises(HTTPException) as ei:
        sec._ensure_valid_host_header(_ReqFalso("evil.com:8000"))
    assert ei.value.status_code == 403
    sec._ensure_valid_host_header(_ReqFalso("127.0.0.1:8000"))  # no lanza


def test_command_stop_no_parte_por_separadores_de_control(monkeypatch):
    """POST /api/command: un 'stop' escondido tras un separador de control
    (\\v, \\f, \\x1c-\\x1e, \\x85, \\u2028...) no marca stop_requested: el
    wrapper solo parte por \\r\\n y ese comando no lo detiene (2026-09-25)."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    class _StdinGraba:
        def __init__(self):
            self.lines = []

        def write(self, s):
            self.lines.append(s)

        def flush(self):
            pass

    class _FakeProc:
        def __init__(self):
            self.stdin = _StdinGraba()

        def poll(self):
            return None

    gui.manager.is_running = True
    gui.manager.wrapper_process = _FakeProc()
    gui.manager.stop_requested = False
    try:
        with TestClient(gui.app, client=("127.0.0.1", 50000)) as c:
            r = c.post("/api/command", json={"command": "say hi\x0bstop"})
            assert r.json().get("status") == "ok", r.text
            assert gui.manager.stop_requested is False, "un stop con \\x0b no debe marcar el flag"
            # el caso legitimo sigue marcando
            r2 = c.post("/api/command", json={"command": "list\nstop"})
            assert r2.json().get("status") == "ok", r2.text
            assert gui.manager.stop_requested is True
    finally:
        gui.manager.is_running = False
        gui.manager.wrapper_process = None
        gui.manager.stop_requested = True


def test_watchdog_tope_de_reintentos(monkeypatch):
    """Tras WATCHDOG_MAX_CRASH_RESTARTS re-arranques fallidos seguidos el
    watchdog deja de reintentar (y avisa una sola vez); se rehabilita cuando
    el servidor se mantiene estable."""
    from gui_backend import config
    import gui_backend.services.watchdog as wd

    monkeypatch.setattr(config, "WATCHDOG_MAX_CRASH_RESTARTS", 2)
    monkeypatch.setattr(wd, "crash_restarts", 0)
    monkeypatch.setattr(wd, "_crash_restart_cap_notified", False)
    monkeypatch.setattr(wd, "last_crash_restart_at", 0.0)
    monkeypatch.setattr(wd, "_backoff_sec", lambda failures: 0)
    monkeypatch.setattr(manager, "is_running", False)
    monkeypatch.setattr(manager, "stop_requested", False)
    monkeypatch.setattr(manager, "start_time", None)
    logs = []
    monkeypatch.setattr(manager, "add_log", lambda text, tipo="info": logs.append(text))
    llamadas = {"n": 0}

    def _fallo():
        llamadas["n"] += 1
        return ("error", "fallo simulado")

    monkeypatch.setattr(wd.lifecycle_service, "start_wrapper", _fallo)

    for i in range(6):
        wd._tick_crash_restart(now=1000.0 + i)

    assert llamadas["n"] == 2, "tras el tope no debe reintentar mas"
    assert sum("Tope" in t or "cap" in t for t in logs) == 1, "el aviso del tope debe salir una sola vez"

    # Estabilidad del servidor -> contador y aviso se reinician
    monkeypatch.setattr(manager, "is_running", True)
    monkeypatch.setattr(manager, "start_time", 1.0)
    wd._tick_crash_restart(now=100000.0)
    assert wd.crash_restarts == 0
    assert wd._crash_restart_cap_notified is False


def test_ai_tool_calls_malformados_no_lanzan(monkeypatch):
    """Una respuesta rara de LM Studio (tool_calls con null/cadenas o
    arguments no-dict) devuelve un envelope de error, nunca una excepcion
    que se traduzca en un 500 (2026-09-25)."""
    from gui_backend.services import ai_assistant as ai

    class _Resp:
        status_code = 200
        text = ""

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    monkeypatch.setattr(ai, "check_lmstudio_health", lambda base_url: (True, "modelo-test"))

    for tool_calls in ([None], ["cadena"], [{"function": "no-dict"}], [{"function": {"name": "set_time", "arguments": ["lista"]}}]):
        monkeypatch.setattr(ai.requests, "post", lambda *a, **k: _Resp({
            "choices": [{"message": {"tool_calls": tool_calls, "content": ""}}],
        }))
        resultado = ai.propose_command("haz de dia")
        assert isinstance(resultado, dict) and "status" in resultado, resultado
        assert resultado["status"] in ("ok", "error"), resultado


def test_restart_guard_de_reentrada(monkeypatch):
    """POST /api/action/restart con un restart ya en vuelo responde busy en
    vez de apilar otro hilo de restart_wrapper (2026-09-25)."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from gui_backend.routers import actions as actions_router

    monkeypatch.setattr(manager, "restart_in_progress", False)
    monkeypatch.setattr(manager, "update_in_progress", False)
    libera = threading.Event()

    def _restart_lento():
        libera.wait(timeout=5)

    monkeypatch.setattr(actions_router.lifecycle_service, "restart_wrapper", _restart_lento)
    try:
        with TestClient(gui.app, client=("127.0.0.1", 50000)) as c:
            r1 = c.post("/api/action/restart")
            assert r1.json().get("status") == "restarting", r1.text
            r2 = c.post("/api/action/restart")
            assert r2.json().get("status") == "busy", r2.text
    finally:
        libera.set()
        gui.manager.restart_in_progress = False
