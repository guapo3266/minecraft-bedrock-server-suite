# -*- coding: utf-8 -*-
"""Canal de eventos NDJSON wrapper->GUI: emisor, lector, aplicador y gate.

Todo en tmp (env WRAPPER_EVENTS_FILE / KNOWN_PLAYERS_PATH parcheados); el
data/ real nunca se toca.
"""
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server_wrapper as sw
import server_gui_server as gui
import gui_backend.config as config
import gui_backend.supervisor as supervisor


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
    gui.manager.events_alive = False
    gui.manager.events_file = None


@pytest.fixture
def events_env(monkeypatch, tmp_path):
    """Canal del wrapper + registro de jugadores aislados en tmp."""
    path = os.path.join(str(tmp_path), "ev.ndjson")
    monkeypatch.setenv("WRAPPER_EVENTS_FILE", path)
    monkeypatch.setattr(supervisor, "KNOWN_PLAYERS_PATH",
                        os.path.join(str(tmp_path), "known_players.json"))
    sw._reset_events_for_tests()
    _reset_manager_state()
    gui.manager.installed_version = None
    yield path
    sw._reset_events_for_tests()
    _reset_manager_state()
    sw.players_online.clear()


def _read_events(path):
    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


# ═══════════════════════════════════════════════════════════════════════
# Emisor del wrapper
# ═══════════════════════════════════════════════════════════════════════
def test_emit_event_escribe_ndjson_valido(events_env):
    sw._emit_event("wrapper_started", pid=123, initial_backup=True)
    sw._emit_event("player_connected", name="Alice", xuid="111")
    events = _read_events(events_env)
    assert [e["event"] for e in events] == ["wrapper_started", "player_connected"]
    assert events[0]["pid"] == 123 and events[0]["initial_backup"] is True
    assert "ts" in events[0]
    assert events[1] == {"ts": events[1]["ts"], "event": "player_connected", "name": "Alice", "xuid": "111"}


def test_emit_event_falla_en_silencio(monkeypatch, tmp_path):
    # El "directorio" es un archivo: open falla siempre; _emit_event no lanza
    bloqueador = tmp_path / "bloqueador"
    bloqueador.write_text("x")
    monkeypatch.setenv("WRAPPER_EVENTS_FILE", str(bloqueador / "ev.ndjson"))
    sw._reset_events_for_tests()
    sw._emit_event("algo")  # no debe lanzar
    sw._emit_event("otro")  # y reintenta sin morir


def test_rotate_old_events(events_env, tmp_path):
    os.makedirs(os.path.dirname(events_env), exist_ok=True)
    viejo = os.path.join(str(tmp_path), "be_viejo.ndjson")
    nuevo = os.path.join(str(tmp_path), "be_nuevo.ndjson")
    for p in (viejo, nuevo):
        with open(p, "w") as f:
            f.write("{}\n")
    old_ts = time.time() - 8 * 86400
    os.utime(viejo, (old_ts, old_ts))
    monkeypatch_inner = pytest.MonkeyPatch()
    monkeypatch_inner.setattr(sw, "EVENTS_DIR", str(tmp_path))
    try:
        sw._rotate_old_events()
    finally:
        monkeypatch_inner.undo()
    assert not os.path.exists(viejo)
    assert os.path.exists(nuevo)


# ═══════════════════════════════════════════════════════════════════════
# Emisión desde read_stdout (lineas reales de BDS)
# ═══════════════════════════════════════════════════════════════════════
class _FakeServerProc:
    def __init__(self, lines):
        self.stdout = _FakeReader(lines)


class _FakeReader:
    def __init__(self, lines):
        self._lines = list(lines)

    def readline(self):
        return self._lines.pop(0) if self._lines else ""


def test_read_stdout_emite_eventos_de_jugadores_y_version(events_env):
    sw.server_process = _FakeServerProc([
        "Version: 1.26.33.2\n",
        "[INFO] Player connected: Alice, xuid: 111\n",
        "[INFO] <Impostor> Player connected: Malo, xuid: 666\n",
        "[INFO] Player disconnected: Alice, xuid: 111\n",
        "",
    ])
    try:
        sw.read_stdout()
    finally:
        sw.server_process = None
        sw.players_online.clear()

    events = _read_events(events_env)
    names = [(e["event"], e.get("name")) for e in events]
    assert names == [
        ("version_captured", None),
        ("player_connected", "Alice"),
        ("player_disconnected", "Alice"),
    ]
    conn = events[1]
    assert conn["xuid"] == "111"
    assert events[0]["version"] == "1.26.33.2"
    # El chat suplantado no genero evento (gate anti-spoofing aguas arriba)
    assert all(e.get("name") != "Malo" for e in events)


# ═══════════════════════════════════════════════════════════════════════
# Aplicador de eventos (GUI)
# ═══════════════════════════════════════════════════════════════════════
def test_apply_event_wrapper_started_activa_canal(events_env):
    assert gui.manager.events_alive is False
    supervisor._apply_event({"event": "wrapper_started", "pid": 1})
    assert gui.manager.events_alive is True


def test_apply_event_version_y_stop(events_env):
    gui.manager.server_stopped_event.clear()
    supervisor._apply_event({"event": "version_captured", "version": "1.26.40.8"})
    supervisor._apply_event({"event": "server_stopped", "returncode": 0})
    assert gui.manager.installed_version == "1.26.40.8"
    assert gui.manager.server_stopped_event.is_set()


def test_apply_event_jugadores_mutan_estado_y_sinks(events_env):
    sinks = []
    gui.manager.player_event_sinks.append(lambda n, x, on: sinks.append((n, x, on)))
    try:
        supervisor._apply_event({"event": "player_connected", "name": "Alice", "xuid": "111"})
        assert "Alice" in gui.manager.players_online
        assert gui.manager.players_xuid["Alice"] == "111"
        supervisor._apply_event({"event": "player_disconnected", "name": "Alice"})
        assert "Alice" not in gui.manager.players_online
        assert sinks == [("Alice", "111", True), ("Alice", None, False)]
        # registro persistido
        assert supervisor.load_known_players()["Alice"]["xuid"] == "111"
    finally:
        gui.manager.player_event_sinks.clear()


def test_apply_event_flags_de_backup(events_env):
    supervisor._apply_event({"event": "backup_compress_started", "files": 10})
    assert gui.manager.backup_in_progress is True
    supervisor._apply_event({"event": "backup_ok", "zip": "x.zip"})
    assert gui.manager.backup_in_progress is False
    assert gui.manager.last_backup_time != "Ninguno"
    gui.manager.backup_in_progress = True
    supervisor._apply_event({"event": "backup_finished", "outcome": "timeout"})
    assert gui.manager.backup_in_progress is False


def test_apply_event_ignora_desconocidos_y_datos_basura(events_env):
    supervisor._apply_event({"event": "futuro_desconocido"})
    supervisor._apply_event({"sin": "event"})
    supervisor._apply_event({"event": "player_connected", "name": ""})  # sin nombre
    assert gui.manager.players_online == set()
    assert gui.manager.events_alive is False


# ═══════════════════════════════════════════════════════════════════════
# Lector (_tail_events) end-to-end sobre fixture
# ═══════════════════════════════════════════════════════════════════════
def test_tail_events_consume_fixture_completo(events_env):
    with open(events_env, "w", encoding="utf-8") as f:
        f.write(json.dumps({"event": "wrapper_started", "pid": 1}) + "\n")
        f.write("{corrupto\n")  # tolerada
        f.write(json.dumps({"event": "version_captured", "version": "1.26.33.2"}) + "\n")
        f.write(json.dumps({"event": "player_connected", "name": "Alice", "xuid": "111"}) + "\n")
        f.write(json.dumps({"event": "server_stopped", "returncode": 0}) + "\n")
    # exit set antes de leer: consume todo lo disponible y termina
    gui.manager.wrapper_exit_event.set()
    supervisor._tail_events(events_env)
    assert gui.manager.events_alive is True
    assert gui.manager.installed_version == "1.26.33.2"
    assert "Alice" in gui.manager.players_online
    assert gui.manager.server_stopped_event.is_set()


def test_tail_events_archivo_ausente_termina(events_env):
    gui.manager.wrapper_exit_event.set()
    supervisor._tail_events(os.path.join(os.path.dirname(events_env), "no_existe.ndjson"))
    # sin archivo y wrapper muerto: termina sin efectos
    assert gui.manager.events_alive is False


# ═══════════════════════════════════════════════════════════════════════
# Gate: eventos autoritativos silencian el parseo de stdout
# ═══════════════════════════════════════════════════════════════════════
class _CanalVivoReader:
    """Simula el orden real: el lector del canal proceso wrapper_started ANTES
    de que la primera linea de stdout llegue a run_wrapper_thread (el wrapper
    escribe el evento antes de arrancar BDS)."""

    def __init__(self, lines):
        self._lines = list(lines)

    def readline(self):
        if not self._lines:
            return ""
        gui.manager.events_alive = True
        return self._lines.pop(0)


class _FakeWrapperProc:
    def __init__(self, lines, reader_cls=_FakeReader):
        self.stdout = reader_cls(lines)

    def wait(self):
        return 0


def _run_wrapper_with_lines(lines):
    gui.manager.wrapper_exit_event.clear()
    gui.manager.server_stopped_event.clear()
    supervisor.run_wrapper_thread(_FakeWrapperProc(lines))


def test_gate_con_eventos_vivos_el_parseo_no_duplica(events_env):
    # Canal vivo: las lineas de stdout NO mutan jugadores ni version
    gui.manager.installed_version = None
    gui.manager.wrapper_exit_event.clear()
    gui.manager.server_stopped_event.clear()
    supervisor.run_wrapper_thread(_FakeWrapperProc(
        [
            "[INFO] Player connected: Alice, xuid: 111\n",
            "[INFO] Version: 9.9.9.9\n",
            "",
        ],
        reader_cls=_CanalVivoReader,
    ))
    assert gui.manager.installed_version is None  # el gate evito la captura
    # el gate evito el registro: known_players vacio (record nunca corrio)
    assert supervisor.load_known_players() == {}


def test_fallback_sin_canal_el_parseo_registra(events_env):
    # Canal muerto (wrapper viejo): el parseo de stdout sigue autoritativo
    gui.manager.events_alive = False
    gui.manager.wrapper_exit_event.clear()
    _run_wrapper_with_lines(["[INFO] Player connected: Alice, xuid: 111\n", ""])
    registry = supervisor.load_known_players()
    assert "Alice" in registry  # el camino regex registro al jugador


def test_fallback_version_ignora_lineas_de_chat(events_env):
    """Regresion (H-01): la captura de version por stdout (fallback sin canal)
    debe aplicar el mismo gate anti-spoofing que el wrapper — una linea de
    chat <Jugador> que contenga 'Version: X' no puede fijar installed_version
    (afectaria a /api/check_update)."""
    gui.manager.events_alive = False
    gui.manager.wrapper_exit_event.clear()
    gui.manager.installed_version = None
    _run_wrapper_with_lines([
        "<Alex> Version: 9.9.9.9\n",
        "[INFO] Version: 1.26.33.2\n",
        "",
    ])
    assert gui.manager.installed_version == "1.26.33.2"


def test_finalize_de_hilo_viejo_no_pisa_sesion_nueva(events_env):
    """Regresion (carrera de sesiones): si un start gana la carrera mientras
    el hilo lector de la sesion anterior esta cerrando (finally), ese finally
    NO debe pisar el estado de la sesion nueva. Antes dejaba wrapper_process=None
    y marcaba los eventos de salida como seteados: la GUI perdia el control de
    un wrapper vivo y los guards de update/restore creian el servidor detenido."""
    import threading as _threading

    release = _threading.Event()

    class _BlockingReader:
        def readline(self):
            release.wait(5)
            return ""

    class _BlockingProc:
        stdout = _BlockingReader()

        def wait(self):
            return 0

    old_proc = _BlockingProc()
    t = _threading.Thread(target=supervisor.run_wrapper_thread, args=(old_proc,), daemon=True)
    t.start()
    deadline = time.time() + 5
    while gui.manager.wrapper_process is not old_proc and time.time() < deadline:
        time.sleep(0.02)
    assert gui.manager.wrapper_process is old_proc  # el hilo tomo la sesion

    # Un start concurrente "gana" la sesion mientras el hilo viejo aun lee
    new_proc = _BlockingProc()
    gui.manager.wrapper_process = new_proc
    gui.manager.is_running = True
    gui.manager.wrapper_exit_event.clear()
    gui.manager.server_stopped_event.clear()

    release.set()  # el hilo viejo ve EOF y entra en su finally
    t.join(5)
    assert not t.is_alive()

    # El finally del hilo viejo no piso la sesion nueva
    assert gui.manager.wrapper_process is new_proc
    assert gui.manager.is_running is True
    assert gui.manager.wrapper_exit_event.is_set() is False
    assert gui.manager.server_stopped_event.is_set() is False


# ═══════════════════════════════════════════════════════════════════════
# Spawn: env del canal sin efectos en disco
# ═══════════════════════════════════════════════════════════════════════
def test_spawn_pasa_env_de_eventos_sin_crear_dirs(monkeypatch, tmp_path):
    captured = {}

    class _FakeProc:
        pass

    def fake_popen(*args, **kwargs):
        captured.update(kwargs)
        return _FakeProc()

    monkeypatch.setattr(supervisor.subprocess, "Popen", fake_popen)
    # BASE_DIR a tmp: el data/wrapper_events REAL puede existir (el servidor
    # vivo emite eventos); el assert debe ser sobre la base del test.
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))
    _reset_manager_state()
    proc = supervisor._spawn_wrapper_process()
    assert isinstance(proc, _FakeProc)
    env = captured["env"]
    events_path = env.get("WRAPPER_EVENTS_FILE", "")
    assert "wrapper_events" in events_path.replace("\\", "/")
    assert events_path == gui.manager.events_file
    # SIN efectos en disco: el directorio lo crea el wrapper, no el spawn
    assert not os.path.exists(os.path.join(str(tmp_path), "data", "wrapper_events"))
    _reset_manager_state()
