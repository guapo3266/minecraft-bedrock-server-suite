# -*- coding: utf-8 -*-
"""Regresiones de la ronda de revision 2026-09-11.

Cada test reproduce un hallazgo verificado contra el codigo fuente y exige
el comportamiento corregido. Los hallazgos descartados (falsos positivos)
no tienen test: el comportamiento correcto ya existia.
"""
import builtins
import multiprocessing
import os
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_backup
import server_wrapper as sw
import wrapper_state as wstate
import server_gui_server as gui
import gui_backend.supervisor as supervisor
import gui_backend.services.bds_update as bds_update
from gui_backend.state import manager
from server_properties import read_value

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════
def _fake_env(monkeypatch, tmp_path):
    """Mundo y backups falsos (mismo patron que el resto de la suite)."""
    fake_world = os.path.join(str(tmp_path), "world")
    fake_bkp = os.path.join(str(tmp_path), "backups")
    os.makedirs(fake_world)
    os.makedirs(fake_bkp)
    monkeypatch.setattr(auto_backup, "WORLD_DIR", fake_world)
    monkeypatch.setattr(auto_backup, "BACKUP_DIR", fake_bkp)
    monkeypatch.setattr(auto_backup, "BASE_DIR", str(tmp_path))
    return fake_world, fake_bkp


def _reset_manager_state():
    gui.manager.is_running = False
    gui.manager.start_time = None
    gui.manager.wrapper_process = None
    gui.manager.update_in_progress = False
    gui.manager.backup_in_progress = False
    gui.manager.players_online.clear()
    gui.manager.wrapper_exit_event.set()
    gui.manager.server_stopped_event.set()
    gui.manager.events_alive = False


class _StdinRoto:
    def write(self, s):
        raise BrokenPipeError("tuberia rota")

    def flush(self):
        pass


class _StdinGraba:
    def __init__(self):
        self.lines = []

    def write(self, s):
        self.lines.append(s)

    def flush(self):
        pass


class _FakeProc:
    def __init__(self, roto=False):
        self.stdin = _StdinRoto() if roto else _StdinGraba()

    def poll(self):
        return None


# ═══════════════════════════════════════════════════════════════════════
# A1: restaurar un ZIP sin mundo no debe destruir el mundo activo
# ═══════════════════════════════════════════════════════════════════════
def test_restore_zip_vacio_aborta_y_preserva_mundo(monkeypatch, tmp_path):
    """Un ZIP sin entradas (o sin level.dat) pasa testzip/expansion, pero el
    guard de level.dat ya no se salta con world_infos vacio: el staging vacio
    no se instala como mundo y el .bak del mundo real no se pierde."""
    fake_world, fake_bkp = _fake_env(monkeypatch, tmp_path)
    with open(os.path.join(fake_world, "level.dat"), "wb") as f:
        f.write(b"WORLD-ORIGINAL")

    zip_vacio = os.path.join(fake_bkp, "auto_backup_test_vacio_1_1_1_abc.zip")
    with zipfile.ZipFile(zip_vacio, "w"):
        pass

    with pytest.raises(RuntimeError, match="level.dat"):
        auto_backup.restore_backup(os.path.basename(zip_vacio))

    with open(os.path.join(fake_world, "level.dat"), "rb") as f:
        assert f.read() == b"WORLD-ORIGINAL"
    residuos = [n for n in os.listdir(os.path.dirname(fake_world))
                if ".restore_staging_" in n or ".bak_" in n]
    assert residuos == [], residuos


def test_restore_zip_solo_packs_aborta_y_preserva_mundo(monkeypatch, tmp_path):
    """ZIP con solo server_resource_packs/ (cero entradas de mundo): mismo
    guard. Antes instalaba el staging vacio como mundo y borraba el .bak."""
    fake_world, fake_bkp = _fake_env(monkeypatch, tmp_path)
    with open(os.path.join(fake_world, "level.dat"), "wb") as f:
        f.write(b"WORLD-ORIGINAL")

    zip_packs = os.path.join(fake_bkp, "auto_backup_test_packs_1_1_1_def.zip")
    with zipfile.ZipFile(zip_packs, "w") as zf:
        zf.writestr("server_resource_packs/foo.txt", b"x")

    with pytest.raises(RuntimeError, match="level.dat"):
        auto_backup.restore_backup(os.path.basename(zip_packs))

    with open(os.path.join(fake_world, "level.dat"), "rb") as f:
        assert f.read() == b"WORLD-ORIGINAL"


def test_restore_zip_valido_sigue_funcionando_y_sin_dir_entry_en_mundo(monkeypatch, tmp_path):
    """Regresion propia del guard nuevo: un backup valido de mundo restaura
    igual; y las entradas de directorio server_* (solo zips de terceros) ya
    no clasifican como mundo (no dejan carpeta espuria dentro del mundo)."""
    fake_world, fake_bkp = _fake_env(monkeypatch, tmp_path)
    with open(os.path.join(fake_world, "level.dat"), "wb") as f:
        f.write(b"WORLD-ORIGINAL")
    result = auto_backup.create_backup("ronda11")
    assert result, "el backup de prueba debio completarse"

    zip_mixto = os.path.join(fake_bkp, "auto_backup_test_mixto_1_1_1_999.zip")
    with zipfile.ZipFile(zip_mixto, "w") as zf:
        zf.writestr("level.dat", b"RESTAURADO")
        zf.writestr("db/", b"")  # dir entry del mundo: se extrae igual
        zf.writestr("server_resource_packs/", b"")  # dir entry de pack: se ignora

    restaurado = auto_backup.restore_backup(os.path.basename(zip_mixto))
    assert restaurado == zip_mixto
    with open(os.path.join(fake_world, "level.dat"), "rb") as f:
        assert f.read() == b"RESTAURADO"
    assert not os.path.exists(os.path.join(fake_world, "server_resource_packs"))


def test_guard_level_dat_presente_en_ambos_restores():
    """Anti-drift: el guard exige level.dat SIEMPRE (sin `world_infos and`)
    en auto_backup y en el CLI restore_backup."""
    for rel in ("auto_backup.py", "restore_backup.py"):
        src = Path(os.path.join(BASE_DIR, rel)).read_text(encoding="utf-8")
        assert 'if not os.path.exists(os.path.join(world_staging, "level.dat")):' in src, rel
        assert "world_infos and not os.path.exists" not in src, rel


# ═══════════════════════════════════════════════════════════════════════
# M2: server.properties no-UTF-8 no tumba el arranque del wrapper
# ═══════════════════════════════════════════════════════════════════════
def test_read_value_tolerante_a_properties_cp1252(tmp_path):
    """Un editor ANSI deja bytes no-UTF-8 (la ñ de cp1252 = 0xF1). Antes el
    decode estricto lanzaba UnicodeDecodeError desde el import de auto_backup
    y el wrapper no arrancaba. Ahora la linea corrupta se salta y el resto
    parsea."""
    props = os.path.join(str(tmp_path), "server.properties")
    with open(props, "wb") as f:
        f.write(b"level-name=Mundo\xf1o\nbackup-inicio=false\n")

    assert read_value(props, "backup-inicio") == "false"
    assert read_value(props, "motd") is None
    # la linea corrupta no se puede decodificar: la clave no se ve (None)
    assert read_value(props, "level-name") is None
    # y el nombre del mundo cae al default sin lanzar
    assert auto_backup.get_world_name(str(tmp_path)) == "Bedrock level"


def test_read_value_utf8_normal_sigue_funcionando(tmp_path):
    props = os.path.join(str(tmp_path), "server.properties")
    with open(props, "wb") as f:
        f.write("# comentario\nlevel-name = Mi Mundo\n".encode("utf-8"))
    assert read_value(props, "level-name") == "Mi Mundo"


# ═══════════════════════════════════════════════════════════════════════
# M1: el watchdog de backup no aborta durante la recoleccion activa
# ═══════════════════════════════════════════════════════════════════════
_CAMPOS = (
    "backup_in_progress", "backup_dispatched", "watchdog_fired",
    "save_query_ready_seen", "last_backup_completed_time", "save_hold_timestamp",
    "last_save_snapshot", "last_snapshot_update_time", "snapshot_retry_at",
    "snapshot_retry_count", "expecting_list_names", "server_process",
    "shutting_down", "backup_cancel_event", "active_compress_process",
)


class _ProcesoVivo:
    def poll(self):
        return None


@pytest.fixture
def scheduler_env(tmp_path, monkeypatch):
    previo = {c: getattr(wstate, c) for c in _CAMPOS}
    previo_players = set(wstate.players_online)
    monkeypatch.setattr(
        sw.wrapper_schedule, "SCHEDULE_CONFIG_PATH", str(tmp_path / "no_existe.json")
    )
    wstate.players_online.clear()
    with wstate.state_lock:
        wstate.backup_in_progress = False
        wstate.backup_dispatched = False
        wstate.watchdog_fired = False
        wstate.save_query_ready_seen = False
        wstate.last_backup_completed_time = time.time()
        wstate.save_hold_timestamp = 0.0
        wstate.last_save_snapshot = []
        wstate.last_snapshot_update_time = 0.0
        wstate.snapshot_retry_at = 0.0
        wstate.snapshot_retry_count = 0
        wstate.expecting_list_names = False
        wstate.server_process = _ProcesoVivo()
        wstate.shutting_down = False
        wstate.backup_cancel_event = None
        wstate.active_compress_process = None
    yield
    wstate.players_online.clear()
    wstate.players_online.update(previo_players)
    with wstate.state_lock:
        for campo, valor in previo.items():
            setattr(wstate, campo, valor)


def _una_iteracion(monkeypatch):
    llamadas = {"sleep": 0}

    def _sleep(_segundos):
        llamadas["sleep"] += 1
        if llamadas["sleep"] >= 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(sw.time, "sleep", _sleep)
    with pytest.raises(KeyboardInterrupt):
        sw.backup_scheduler()


def test_holding_con_recoleccion_activa_no_dispara_watchdog(scheduler_env, monkeypatch):
    """BDS respondio (ready) y hay archivos en el snapshot, pero el listado
    sigue llegando (silencio < 5s) y el save hold fue hace 61s. El watchdog
    viejo abortaba cada ciclo con el diagnostico falso de 'no respondio';
    ahora la recoleccion activa NO se aborta."""
    comandos = []
    monkeypatch.setattr(sw, "send_command", comandos.append)
    with wstate.state_lock:
        wstate.backup_in_progress = True
        wstate.backup_dispatched = False
        wstate.save_query_ready_seen = True
        wstate.last_save_snapshot = [("level.dat", 10)]
        wstate.last_snapshot_update_time = time.time() - 2  # silencio < 5s
        wstate.save_hold_timestamp = time.time() - 61       # hold hace 61s

    _una_iteracion(monkeypatch)

    assert "save resume" not in comandos, comandos
    with wstate.state_lock:
        assert wstate.backup_in_progress is True
        assert wstate.backup_dispatched is False
        assert wstate.watchdog_fired is False


def test_holding_respuesta_sin_archivos_dispara_watchdog(scheduler_env, monkeypatch):
    """Caso (b): 'Data saved...' llego PERO el snapshot quedo vacio y lleva
    61s sin avanzar: recoleccion estancada de verdad -> resume forzado."""
    comandos = []
    monkeypatch.setattr(sw, "send_command", comandos.append)
    with wstate.state_lock:
        wstate.backup_in_progress = True
        wstate.backup_dispatched = False
        wstate.save_query_ready_seen = True
        wstate.last_save_snapshot = []
        wstate.last_snapshot_update_time = time.time() - 61
        wstate.save_hold_timestamp = time.time() - 61

    _una_iteracion(monkeypatch)

    assert "save resume" in comandos, comandos
    with wstate.state_lock:
        assert wstate.backup_in_progress is False
        assert wstate.watchdog_fired is True


# ═══════════════════════════════════════════════════════════════════════
# M4: el tail de eventos no queda atrapado si la sesion cambio
# ═══════════════════════════════════════════════════════════════════════
def test_tail_events_termina_si_la_sesion_caduco(monkeypatch, tmp_path):
    """Con restart rapido, el finally del hilo viejo setea wrapper_exit_event
    pero el spawn nuevo lo limpia: si el poll del tail viejo caia entre medias
    quedaba leyendo el .ndjson muerto para siempre (hilo + handle). Ahora el
    tail termina cuando manager.events_file apunta a OTRO canal."""
    path_viejo = os.path.join(str(tmp_path), "viejo.ndjson")
    with open(path_viejo, "w", encoding="utf-8"):
        pass
    monkeypatch.setattr(manager, "events_file", os.path.join(str(tmp_path), "nuevo.ndjson"))
    monkeypatch.setattr(manager, "wrapper_exit_event", threading.Event())  # clear

    t = threading.Thread(target=supervisor._tail_events, args=(path_viejo,), daemon=True)
    t.start()
    t.join(timeout=2)
    assert not t.is_alive(), "el tail quedo atrapado en el canal de una sesion muerta"


# ═══════════════════════════════════════════════════════════════════════
# M5: el marcador "BDS stopped" lleva gate anti-spoofing
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


def _aislar_manager(monkeypatch):
    monkeypatch.setattr(manager, "add_log", lambda *a, **k: None)
    monkeypatch.setattr(manager, "update_status", lambda: None)
    monkeypatch.setattr(manager, "events_file", None)
    monkeypatch.setattr(manager, "events_alive", False)
    monkeypatch.setattr(manager, "installed_version", None)
    monkeypatch.setattr(manager, "is_running", False)
    monkeypatch.setattr(manager, "wrapper_process", None)
    monkeypatch.setattr(manager, "wrapper_exit_event", threading.Event())
    monkeypatch.setattr(manager, "server_stopped_event", threading.Event())
    monkeypatch.setattr(manager, "players_online", set())
    monkeypatch.setattr(manager, "backup_in_progress", False)


class _EventContador:
    """Cuenta set(): distingue el marcador del respaldo que el finally de la
    sesion emite SIEMPRE al cerrar (1 set extra en cada corrida)."""

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


def test_marcador_bds_stopped_ignora_chat(monkeypatch):
    """Un jugador escribiendo 'BDS stopped' en el chat (<Jugador> ...) no
    setea server_stopped_event por via del marcador. El finally de la sesion
    siempre emite 1 set de respaldo al cerrar; con solo el chat en el log, el
    total debe quedar exactamente en ese 1."""
    _aislar_manager(monkeypatch)
    contador = _EventContador()
    monkeypatch.setattr(manager, "server_stopped_event", contador)
    proc = _FakeProcStdout(["<Steve> el BDS stopped jaja\n", ""])
    supervisor.run_wrapper_thread(proc)
    assert contador.sets == 1, "el chat seteo el evento ademas del respaldo del finally"
    assert manager.is_running is False  # la sesion si cerro


def test_marcador_bds_stopped_real_sigue_funcionando(monkeypatch):
    """El marcador legitimo del wrapper (sin prefijo de chat) setea el
    evento: respaldo del finally (1) + marcador (2)."""
    _aislar_manager(monkeypatch)
    contador = _EventContador()
    monkeypatch.setattr(manager, "server_stopped_event", contador)
    proc = _FakeProcStdout([
        "[Wrapper] BDS stopped. Starting final shutdown cleanup...\n",
        "",
    ])
    supervisor.run_wrapper_thread(proc)
    assert contador.sets == 2, "el marcador legitimo dejo de setear el evento"


# ═══════════════════════════════════════════════════════════════════════
# M6: Ctrl+C espera el mismo tope que la ruta normal de stop
# ═══════════════════════════════════════════════════════════════════════
def test_ctrl_c_usa_el_tope_bds_stop_timeout():
    src = Path(os.path.join(BASE_DIR, "server_wrapper.py")).read_text(encoding="utf-8")
    assert "wstate.server_process.wait(timeout=wstate.BDS_STOP_TIMEOUT_SEC)" in src
    assert "timeout=15)" not in src, "el wait de 15s del Ctrl+C sobrevivio"


# ═══════════════════════════════════════════════════════════════════════
# BAJA-10: PermissionError en copia caliente es desync (reintento), no fatal
# ═══════════════════════════════════════════════════════════════════════
def test_permissionerror_en_copia_caliente_es_snapshot_desync(monkeypatch, tmp_path):
    """El antivirus retiene un archivo un instante -> PermissionError. Antes
    abortaba el ciclo sin reintento; ahora se clasifica como desync del
    snapshot (un nuevo save query puede arreglarlo)."""
    fake_world, _fake_bkp = _fake_env(monkeypatch, tmp_path)
    with open(os.path.join(fake_world, "level.dat"), "wb") as f:
        f.write(b"L" * 10)
    grande = os.path.join(fake_world, "grande.bin")
    with open(grande, "wb") as f:
        f.write(b"G" * 100)
    size = os.path.getsize(grande)

    real_open = builtins.open

    def fake_open(p, mode="r", *a, **k):
        if os.path.abspath(str(p)) == os.path.abspath(grande) and "b" in str(mode):
            raise PermissionError(13, "bloqueado por antivirus (simulado)")
        return real_open(p, mode, *a, **k)

    monkeypatch.setattr(builtins, "open", fake_open)
    with pytest.raises(auto_backup.SnapshotDesyncError):
        auto_backup.create_backup("perm", file_snapshot=[
            ("level.dat", 10), ("grande.bin", size),
        ])


# ═══════════════════════════════════════════════════════════════════════
# M7: junctions/symlinks no se empaquetan (lado backup)
# ═══════════════════════════════════════════════════════════════════════
@pytest.mark.skipif(os.name != "nt", reason="junctions de Windows")
def test_junction_dentro_del_mundo_no_se_empaqueta(monkeypatch, tmp_path):
    """Una junction dentro de worlds/<mundo>/ apuntando a una carpeta externa
    no mete contenido externo en el ZIP (el guard realpath solo cubria el
    modo snapshot; los os.walk seguian junctions)."""
    fake_world, _fake_bkp = _fake_env(monkeypatch, tmp_path)
    secreto = os.path.join(str(tmp_path), "secreto")
    os.makedirs(secreto)
    with open(os.path.join(secreto, "dato.txt"), "w") as f:
        f.write("x")
    enlace = os.path.join(fake_world, "enlace")
    r = subprocess.run(
        ["cmd", "/c", "mklink", "/J", enlace, secreto],
        capture_output=True,
    )
    if r.returncode != 0:
        pytest.skip("mklink /J no disponible: %s" % r.stderr.decode(errors="replace"))
    try:
        with open(os.path.join(fake_world, "level.dat"), "wb") as f:
            f.write(b"L" * 10)
        result = auto_backup.create_backup("junc")
        assert result, "el backup debio completarse"
        with zipfile.ZipFile(result) as zf:
            names = zf.namelist()
        assert "level.dat" in names
        assert not any(n.startswith("enlace/") for n in names), names
    finally:
        # quitar el junction ANTES de que tmp_path haga su rmtree
        try:
            os.rmdir(enlace)  # borra el enlace, no el destino
        except OSError:
            pass


# ═══════════════════════════════════════════════════════════════════════
# BAJA-3/4: limpieza tras kill del worker acotada y sin pisar backups ajenos
# ═══════════════════════════════════════════════════════════════════════
def test_kill_worker_limpieza_omitida_si_otro_backup_retiene_mutex(monkeypatch, tmp_path):
    """La limpieza de .tmp tras el kill va tras el NamedMutex no bloqueante:
    si otro backup (cold de la GUI) esta en curso, no se borra SU .tmp."""
    fake_bkp = os.path.join(str(tmp_path), "backups")
    os.makedirs(fake_bkp)
    orphan = os.path.join(fake_bkp, "auto_backup_x.zip.tmp")
    with open(orphan, "wb") as f:
        f.write(b"de otro backup")

    import server_wrapper as swmod
    monkeypatch.setattr(swmod.auto_backup, "BACKUP_DIR", fake_bkp)

    class _MutexOcupado:
        def acquire(self, timeout_ms=0):
            return False

        def release(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(swmod.wpg, "NamedMutex", _MutexOcupado)

    class _FakeProc:
        def is_alive(self):
            return True

        def kill(self):
            pass

        def join(self, timeout=None):
            pass

    fp = _FakeProc()
    monkeypatch.setattr(wstate, "active_compress_process", fp)
    monkeypatch.setattr(wstate, "backup_ipc_lock", multiprocessing.Lock())

    swmod.wrapper_backup._force_kill_compress_process(fp)
    assert os.path.exists(orphan), "se borro el .tmp de un backup ajeno en curso"


def test_ipc_mutex_early_return_cierra_handle():
    """BAJA-4: el early-return por mutex ocupado en create_backup cierra el
    handle del NamedMutex (antes filtraba uno por llamada)."""
    src = Path(os.path.join(BASE_DIR, "auto_backup.py")).read_text(encoding="utf-8")
    marcador = "if not ipc_mutex.acquire(timeout_ms=timeout_ms):"
    i = src.index(marcador)
    bloque = src[i:i + 400]
    assert "ipc_mutex.close()" in bloque


# ═══════════════════════════════════════════════════════════════════════
# BAJA-5: la descarga BDS valida el HTTP antes de guardar el zip
# ═══════════════════════════════════════════════════════════════════════
def test_descarga_bds_http_404_aborta(monkeypatch):
    class _Resp404:
        status_code = 404
        headers = {}

        def iter_content(self, chunk_size=8192):
            return iter((b"<html>not found</html>",))

    monkeypatch.setattr(
        bds_update, "_fetch_latest_bedrock_download",
        lambda: ("http://example/bedrock.zip", "1.0.0"),
    )
    monkeypatch.setattr(bds_update.requests, "get", lambda *a, **k: _Resp404())
    logs = []
    ok, version = bds_update._download_and_install_bds(tag="[T]", log_fn=lambda m, t: logs.append(m))
    assert ok is False and version is None
    assert any("HTTP 404" in m for m in logs), logs
    assert not os.path.exists(os.path.join(bds_update.config.BASE_DIR, "bds_update.zip"))


# ═══════════════════════════════════════════════════════════════════════
# O1: stop_requested solo tras ENTREGAR el comando (consola HTTP y WS)
# ═══════════════════════════════════════════════════════════════════════
def test_command_stdin_roto_devuelve_error_y_no_marca_flag(monkeypatch, tmp_path):
    """Mirror de test_stop_stdin_roto_devuelve_500_y_no_marca_flag para
    POST /api/command: el write falla -> status error y stop_requested False
    (si no, el watchdog quedaria inhibido con el servidor vivo)."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    _reset_manager_state()
    gui.manager.is_running = True
    gui.manager.wrapper_process = _FakeProc(roto=True)
    gui.manager.stop_requested = False
    try:
        with TestClient(gui.app, client=("127.0.0.1", 50000)) as c:
            r = c.post("/api/command", json={"command": "stop"})
            assert r.json().get("status") == "error", r.text
            assert gui.manager.stop_requested is False
            # un comando normal con stdin roto tampoco marca nada
            r2 = c.post("/api/command", json={"command": "list"})
            assert r2.json().get("status") == "error", r2.text
            assert gui.manager.stop_requested is False
    finally:
        _reset_manager_state()


def test_ws_stdin_roto_loguea_error_y_no_marca_flag(monkeypatch):
    """Mirror WS: el comando no desaparece en silencio (BAJA-1) y un 'stop'
    con stdin roto no marca stop_requested (gap O1)."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    _reset_manager_state()
    logs = []
    monkeypatch.setattr(manager, "add_log", lambda text, tipo="info": logs.append((text, tipo)))
    monkeypatch.setattr(manager, "update_status", lambda: None)
    gui.manager.is_running = True
    gui.manager.wrapper_process = _FakeProc(roto=True)
    gui.manager.stop_requested = False
    try:
        with TestClient(gui.app, client=("127.0.0.1", 50000)) as c:
            with c.websocket_connect("/ws") as ws:
                init = ws.receive_json()
                assert init["type"] == "init"
                ws.send_json({"type": "command", "command": "stop"})
                ws.send_json({"type": "ping"})
                # el pong llega despues de que el comando fue procesado
                # (el endpoint procesa los mensajes en orden)
                assert ws.receive_json()["type"] == "pong"
    except Exception:
        # el cierre del cliente provoca WebSocketDisconnect dentro del
        # endpoint; el comando ya fue procesado antes del pong
        pass
    finally:
        _reset_manager_state()

    assert gui.manager.stop_requested is False
    assert any("Error enviando comando" in t or "Error sending command" in t for t, _ in logs), logs[-5:]


def test_command_stdin_sano_marca_flag_tras_entregar(monkeypatch, tmp_path):
    """El happy path sigue marcando stop_requested (solo cambia el ORDEN)."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    _reset_manager_state()
    gui.manager.is_running = True
    gui.manager.wrapper_process = _FakeProc(roto=False)
    gui.manager.stop_requested = False
    try:
        with TestClient(gui.app, client=("127.0.0.1", 50000)) as c:
            r = c.post("/api/command", json={"command": "stop  "})
            assert r.json().get("status") == "ok", r.text
            assert gui.manager.stop_requested is True
            assert "stop\n" in gui.manager.wrapper_process.stdin.lines
    finally:
        _reset_manager_state()


# ═══════════════════════════════════════════════════════════════════════
# M3: enable_beta_apis_v2 resguarda el level.dat antes de reescribirlo
# ═══════════════════════════════════════════════════════════════════════
def test_enable_beta_apis_resguardo_previo():
    src = Path(os.path.join(BASE_DIR, "tools", "enable_beta_apis_v2.py")).read_text(encoding="utf-8")
    assert "shutil.copy2" in src
    assert ".respaldo_" in src
    # el sufijo NO puede ser .bak_: recover_interrupted_restores renombra
    # todo *.bak_* de worlds/ como huerfano en el arranque del wrapper
    assert '".bak_"' not in src and '.bak_"' not in src


# ═══════════════════════════════════════════════════════════════════════
# Frontend clasico (BAJA-6): 409 visible y terminal acotada (chequeo texto)
# ═══════════════════════════════════════════════════════════════════════
def test_web_clasica_reporta_http_y_acota_terminal():
    src = Path(os.path.join(BASE_DIR, "web", "app.js")).read_text(encoding="utf-8")
    trigger = src.split("async function triggerAction")[1].split("btnStart.addEventListener")[0]
    assert "res.ok" in trigger
    assert "data.detail" in trigger
    assert "MAX_LOG_ENTRIES" in src
