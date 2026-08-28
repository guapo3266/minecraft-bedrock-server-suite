# -*- coding: utf-8 -*-
"""Regresiones de la review 2026-08-28 (H1-H7), todas reproducidas primero con
scripts reales y fixeadas despues (ver informe de la review).

Cada test falla contra el codigo PRE-fix y pasa contra el POST-fix:
  H1  wrapper_events: en modo standalone (sin WRAPPER_EVENTS_FILE) los eventos
      iban a UN ARCHIVO NUEVO POR EVENTO (la ruta se recomponia con timestamp+
      nonce en cada _emit_event). Fix: sufijo estable cacheado por proceso.
  H2  server_wrapper (guard de arranque): abortaba por EXISTENCIA del mutex
      (already_exists), no por adquisicion. Fix: solo acquire con doble intento.
  H3  auto_backup.get_world_dir / create_backup: el global WORLD_DIR calculado
      al importar podia quedar stale en procesos largos (GUI) y el heuristic
      monkeypatch-safe lo trataba como patch -> backup del mundo EQUIVOCADO y
      arcnames '../' en modo snapshot. Fix: distinguir patch de staleness con
      _IMPORT_TIME_WORLD_DIR y resolver rutas al inicio de create_backup.
  H4  router WS: 'stop' por WebSocket no marcaba manager.stop_requested (a
      diferencia de /api/command) -> el watchdog con auto_restart_on_crash
      re-lanzaba el servidor parado deliberadamente. Fix: marcar el flag por
      linea (tambien cubre multi-linea 'list\nstop').
  H5  zip_safety: _quarantine_and_restore/_extract_pack_entry duplicadas entre
      auto_backup y restore_backup DIVERGIERON (los markers de restaurable no
      eran la misma lista en GUI y CLI). Fix: fuente unica + alias.
  H6  wrapper_backup.execute_backup_worker: la rama de excepcion general dejaba
      bw_snap_*.json huerfano en %TEMP%. Fix: limpieza incondicional en finally.
  H7  properties: server-name aceptaba \n (inyeccion de lineas arbitrarias en
      server.properties) y enteros no canonicos (' 12 '); y server_wrapper
      re-exportaba el scalar MUTABLE last_daily_backup_date como copia stale.
"""
import asyncio
import json
import os
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_backup
import restore_backup
import wrapper_backup
import wrapper_events
import zip_safety
import gui_backend.services.backups as backups_service
from gui_backend.services import properties as props_service


# ═══════════════════════════════════════════════════════════════════════
# H1 — un archivo de eventos por proceso en modo standalone
# ═══════════════════════════════════════════════════════════════════════
def test_events_standalone_un_archivo_por_proceso(monkeypatch, tmp_path):
    """Sin WRAPPER_EVENTS_FILE (iniciar_servidor.bat), N eventos -> 1 archivo
    con N lineas. Pre-fix: N archivos de 1 linea (ruta aleatoria por emit)."""
    monkeypatch.delenv("WRAPPER_EVENTS_FILE", raising=False)
    evdir = tmp_path / "ev"
    evdir.mkdir()
    monkeypatch.setattr(wrapper_events, "EVENTS_DIR", str(evdir))
    wrapper_events._reset_events_for_tests()
    try:
        for i in range(5):
            wrapper_events._emit_event("player_connected", name="P%d" % i, xuid=str(i))
        files = list(evdir.iterdir())
        assert len(files) == 1, (
            "standalone creo %d archivos de eventos (esperado 1): %s"
            % (len(files), [f.name for f in files])
        )
        lineas = [ln for ln in files[0].read_text(encoding="utf-8").splitlines() if ln]
        assert len(lineas) == 5
        assert [json.loads(ln)["event"] for ln in lineas] == ["player_connected"] * 5
    finally:
        wrapper_events._reset_events_for_tests()


def test_events_reset_for_tests_limpia_cache_standalone(monkeypatch, tmp_path):
    """El reset de tests debe descartar el sufijo cacheado: dos 'boots'
    simulados (reset en medio) usan archivos distintos, no el mismo handle."""
    monkeypatch.delenv("WRAPPER_EVENTS_FILE", raising=False)
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir(); b.mkdir()
    wrapper_events._reset_events_for_tests()
    monkeypatch.setattr(wrapper_events, "EVENTS_DIR", str(a))
    wrapper_events._emit_event("x")
    wrapper_events._reset_events_for_tests()
    monkeypatch.setattr(wrapper_events, "EVENTS_DIR", str(b))
    wrapper_events._emit_event("y")
    try:
        assert len(list(a.iterdir())) == 1
        assert len(list(b.iterdir())) == 1, "el segundo boot reutilizo el path del primero"
    finally:
        wrapper_events._reset_events_for_tests()


# ═══════════════════════════════════════════════════════════════════════
# H2 — guard de arranque del wrapper SOLO por adquisicion
# ═══════════════════════════════════════════════════════════════════════
def test_arranque_wrapper_no_aborta_por_existencia():
    """Anti-drift textual: el guard de __main__ debe decidir SOLO por el fallo
    de acquire(). Regresion (incidente de las dos GUIs): una sonda ajena deja
    el objeto mutex abierto un instante sin retenerlo; con already_exists en
    el guard, el wrapper abortaba su propio arranque apesar de poder adquirir.
    """
    src = open(os.path.join(os.path.dirname(__file__), "..", "server_wrapper.py"),
               encoding="utf-8").read()
    main_block = src.split('if __name__ == "__main__":')[1]
    assert "wrapper_mutex.already_exists" not in main_block, (
        "el guard de arranque volvio a decidir por-existencia (usar solo acquire)"
    )
    assert "wrapper_mutex.acquire(timeout_ms=100)" in main_block
    # y el mensaje de aborto debe seguir existiendo (contracto de UX)
    assert "An instance of the wrapper is already running" in main_block


def test_named_mutex_abierto_sin_adquirir_no_bloquea_arranque():
    """Comportamiento semantico que justifica H2: un segundo NamedMutex sobre
    el mismo nombre PUEDE adquirir si el primero solo abrio el handle (patrón
    sonda) y no lo retiene; solo un titular que retiene bloquea el acquire.
    El retenedor corre en OTRO hilo: los mutex de Windows son reentrantes por
    hilo y en el mismo hilo siempre adquiririan."""
    import threading
    import windows_process_guard as wpg
    name = "BDS_Wrapper_H2_regression_test"
    a = wpg.NamedMutex(name)          # abre el objeto SIN adquirir (sonda)
    b = wpg.NamedMutex(name)          # lo que haria el guard del wrapper
    try:
        assert b.already_exists is True, "precondicion: el objeto ya existe"
        assert b.acquire(timeout_ms=100) is True, (
            "no se puede adquirir un mutex solo ABIERTO: si esto falla, el "
            "guard por-existencia era el unico filtro y habia que quitarlo"
        )
        b.release()
    finally:
        a.close(); b.close()
    # control: un retenedor real (otro hilo) si bloquea
    acquired = threading.Event()
    release = threading.Event()

    def holder():
        m = wpg.NamedMutex(name)
        m.acquire(timeout_ms=100)
        acquired.set()
        release.wait(timeout=5)
        m.release(); m.close()

    t = threading.Thread(target=holder)
    t.start()
    assert acquired.wait(timeout=2), "el holder no adquirio"
    try:
        d = wpg.NamedMutex(name)
        try:
            assert d.acquire(timeout_ms=100) is False, (
                "el acquire debe fallar ante un titular real reteniendo"
            )
        finally:
            d.close()
    finally:
        release.set()
        t.join(timeout=5)


# ═══════════════════════════════════════════════════════════════════════
# H3 — mundo resuelto al vuelo; sin arcnames '../'
# ═══════════════════════════════════════════════════════════════════════
@pytest.fixture
def fake_install(tmp_path, monkeypatch):
    """Instalacion falsa: properties apunta a CustomWorld; el global WORLD_DIR
    del 'import' queda STALE en el default (escenario GUI longinqua)."""
    base = tmp_path / "inst"
    worlds = base / "worlds"
    stale = worlds / "Bedrock level"
    real = worlds / "CustomWorld"
    (real / "db").mkdir(parents=True)
    stale.mkdir(parents=True)
    (base / "server.properties").write_text("level-name=CustomWorld\n", encoding="utf-8")
    (real / "level.dat").write_bytes(b"LEVEL-REAL")
    (real / "db" / "CURRENT").write_bytes(b"MANIFEST-0")
    (stale / "basura.dat").write_bytes(b"stale")
    monkeypatch.setattr(auto_backup, "BASE_DIR", str(base))
    monkeypatch.setattr(auto_backup, "SERVER_NAME", "T")
    monkeypatch.setattr(auto_backup, "BACKUP_DIR", str(base / "bks"))
    monkeypatch.setattr(auto_backup, "_IMPORT_TIME_WORLD_DIR", str(stale))
    monkeypatch.setattr(auto_backup, "WORLD_DIR", str(stale))
    return base


def test_get_world_dir_relee_properties_sin_patch(fake_install):
    """Sin monkeypatch (global == valor de import): un proceso largo debe ver
    el mundo ACTUAL de server.properties, no el del import (H3a)."""
    got = auto_backup.get_world_dir()
    assert got.endswith(os.path.join("worlds", "CustomWorld")), (
        "get_world_dir devolvio el global stale: %s" % got
    )


def test_get_world_dir_respetona_el_parche_de_tests(tmp_path, monkeypatch):
    """Con monkeypatch (global != valor de import): respetar el parche —
    convencion de toda la suite (_setup_env apunta WORLD_DIR a un path sin
    Relacion con properties)."""
    patched = str(tmp_path / "otro_mundo")
    monkeypatch.setattr(auto_backup, "WORLD_DIR", patched)
    assert auto_backup.get_world_dir() == patched


def test_backup_snapshot_sin_arcnames_escape(fake_install):
    """H3b end-to-end: con el global stale == default, create_backup en modo
    snapshot no debe producir entradas '../' (ZIP irrecuperable: _is_safe_
    zip_entry las rechazaria en restauracion)."""
    real = fake_install / "worlds" / "CustomWorld"
    snap = [
        ["level.dat", (real / "level.dat").stat().st_size],
        ["db/CURRENT", (real / "db" / "CURRENT").stat().st_size],
    ]
    zip_path = auto_backup.create_backup("hot", file_snapshot=snap)
    assert zip_path and os.path.isfile(zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        assert not any(n.startswith("..") or "/../" in n for n in names), names
        assert sorted(names) == ["db/CURRENT", "level.dat"], names
        assert zf.read("level.dat") == b"LEVEL-REAL"


def test_backup_frio_usa_mundo_actual_y_no_el_viejo(fake_install):
    """H3a end-to-end (backup tradicional de la GUI): el ZIP debe contener el
    mundo que dice server.properties, no el folder stale del import."""
    zip_path = auto_backup.create_backup("frio", file_snapshot=None)
    assert zip_path
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    assert "level.dat" in names, (
        "el backup frio empaqueto el mundo viejo (stale): %s" % names
    )
    assert not any("basura" in n for n in names), names


# ═══════════════════════════════════════════════════════════════════════
# H4 — 'stop' por WebSocket marca stop_requested (anti re-lanzador)
# ═══════════════════════════════════════════════════════════════════════
class _WsH4:
    """WebSocket falso minimo para el router real (estilo test_websocket_router)."""

    class _Cliente:
        host = "127.0.0.1"

    def __init__(self, entrantes):
        self.client = self._Cliente()
        self.headers = {"host": "127.0.0.1:8000"}
        self.url = type("U", (), {"port": 8000, "scheme": "ws"})()
        self.query_params = {}
        self._entrantes = list(entrantes)

    async def accept(self):
        pass

    async def close(self, code=1000):
        pass

    async def send_json(self, payload):
        pass

    async def receive_text(self):
        if not self._entrantes:
            raise RuntimeError("cliente desconectado")
        return self._entrantes.pop(0)


def _run_ws_command(entrante_json, monkeypatch, tmp_path):
    from gui_backend.routers.websocket import websocket_endpoint
    from gui_backend.state import manager

    stdin_data = []
    proc = type("P", (), {
        "stdin": type("S", (), {
            "write": lambda self, s: stdin_data.append(s),
            "flush": lambda self: None,
        })(),
        "poll": lambda self: None,
    })()
    monkeypatch.setattr(manager, "wrapper_process", proc)
    monkeypatch.setattr(manager, "is_running", True)
    monkeypatch.setattr(manager, "stop_requested", False)
    ws = _WsH4([json.dumps(entrante_json)])
    with pytest.raises(Exception, match="cliente desconectado"):
        asyncio.run(websocket_endpoint(ws))
    return stdin_data, manager


def test_ws_stop_command_marca_stop_requested(monkeypatch, tmp_path):
    stdin_data, manager = _run_ws_command(
        {"type": "command", "command": "stop"}, monkeypatch, tmp_path)
    assert stdin_data == ["stop\n"]
    assert manager.stop_requested is True, (
        "stop via WS sin stop_requested: el watchdog con auto_restart_on_crash "
        "re-lanzaria el servidor parado deliberadamente (H4)"
    )


def test_ws_comando_no_stop_no_toca_stop_requested(monkeypatch, tmp_path):
    _, manager = _run_ws_command(
        {"type": "command", "command": "list"}, monkeypatch, tmp_path)
    assert manager.stop_requested is False


def test_ws_stop_multilinea_marca_stop_requested(monkeypatch, tmp_path):
    """'list\nstop' en un solo mensaje apaga el wrapper (read_stdin lo procesa
    linea a linea): el flag debe marcarse igual."""
    _, manager = _run_ws_command(
        {"type": "command", "command": "list\nstop"}, monkeypatch, tmp_path)
    assert manager.stop_requested is True


# ═══════════════════════════════════════════════════════════════════════
# H5 — fuentes unicas anti-drift
# ═══════════════════════════════════════════════════════════════════════
def test_funciones_restauracion_identidad_alias():
    """Misma identidad que el contrato de _is_safe_zip_entry/_pack_dest: la
    logica de cuarentena/extract vive en zip_safety y ambos modulos son alias."""
    assert auto_backup._quarantine_and_restore is zip_safety._quarantine_and_restore
    assert restore_backup._quarantine_and_restore is zip_safety._quarantine_and_restore
    assert auto_backup._extract_pack_entry is zip_safety._extract_pack_entry
    assert restore_backup._extract_pack_entry is zip_safety._extract_pack_entry


def test_corrupt_markers_consenso_guicli_rotacion():
    """GUI, CLI y rotacion comparten la lista canonica: lo que la GUI oculta
    para restaurar lo oculta la CLI (drift H5: cierre_crash visible solo CLI)."""
    assert zip_safety.CORRUPT_MARKERS == (
        "_CORRUPTO", "_EXCEDIDO", "_CRASH", "_crash",
    )
    assert auto_backup.CORRUPT_MARKERS is zip_safety.CORRUPT_MARKERS
    assert restore_backup._CORRUPT_MARKERS == zip_safety.CORRUPT_MARKERS
    assert backups_service._CORRUPT_MARKERS == zip_safety.CORRUPT_MARKERS


def test_listas_guicli_coinciden_mismo_directorio(tmp_path):
    """Mismo directorio, misma vista: antes la GUI ocultaba el cierre_crash y
    la CLI lo listaba."""
    for name in (
        "auto_backup_T_auto_2026-08-28_111111_aaa.zip",
        "auto_backup_T_cierre_crash_2026-08-28_111111_bbb.zip",
        "auto_backup_T_p_CORRUPTO_2026-08-28_111111_ccc.zip",
        "auto_backup_T_ok_2026-08-28_111111_ddd.zip",
    ):
        (tmp_path / name).write_bytes(b"x")
    gui = sorted(os.path.basename(p) for p in backups_service._list_backup_files(str(tmp_path)))
    cli = sorted(os.path.basename(p) for p in restore_backup._list_backup_files(str(tmp_path)))
    assert gui == cli == [
        "auto_backup_T_auto_2026-08-28_111111_aaa.zip",
        "auto_backup_T_ok_2026-08-28_111111_ddd.zip",
    ]


# ═══════════════════════════════════════════════════════════════════════
# H6 — excepcion inesperada del worker no deja temporales en %TEMP%
# ═══════════════════════════════════════════════════════════════════════
def test_excepcion_worker_limpia_temporales(monkeypatch, tmp_path):
    import wrapper_state as wstate

    tmp = tmp_path / "temp"
    tmp.mkdir()
    monkeypatch.setenv("TEMP", str(tmp))
    monkeypatch.setattr(auto_backup, "BACKUP_DIR", str(tmp_path / "bks"))
    monkeypatch.setattr(wrapper_backup, "_send_command", lambda cmd: None)
    monkeypatch.setattr(wrapper_events, "_emit_event", lambda *a, **k: None)

    class BoomProc:
        """Popen 'exitoso' cuyo poll()/wait() revientan: cae en el except
        general (el unico camino que pre-fix NO limpiaba)."""
        def __init__(self, *a, **k):
            pass

        def poll(self):
            raise RuntimeError("boom simulado")

        def wait(self, timeout=None):
            raise RuntimeError("boom simulado")

    monkeypatch.setattr(wrapper_backup.subprocess, "Popen", BoomProc)
    prev = (wstate.backup_in_progress, wstate.backup_dispatched, wstate.watchdog_fired,
            wstate.save_query_ready_seen, wstate.backup_cancel_event,
            wstate.snapshot_retry_count, wstate.snapshot_retry_at,
            wstate.active_compress_process)
    try:
        wrapper_backup.execute_backup_worker([["level.dat", 10]], cancel_event=None)
        leftovers = sorted(os.listdir(str(tmp)))
        assert leftovers == [], (
            "excepcion general dejo temporales huerfanos en %%TEMP%%: %s" % leftovers
        )
    finally:
        (wstate.backup_in_progress, wstate.backup_dispatched, wstate.watchdog_fired,
         wstate.save_query_ready_seen, wstate.backup_cancel_event,
         wstate.snapshot_retry_count, wstate.snapshot_retry_at,
         wstate.active_compress_process) = prev


def test_fin_de_ciclo_sigue_incondicional_en_finally():
    """El marcador bilingue del fin del ciclo (contrato IPC fallback) sigue
    emitiendose en el finally DESPUES de anadir alli la limpieza de temporales
    (la limpieza no debe poder saltarse el print/emit, ni viceversa)."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "wrapper_backup.py"),
               encoding="utf-8").read()
    worker = src.split("def execute_backup_worker")[1]
    fin = worker.split("finally:")[1]
    assert '"[Worker] Backup finalizado"' in fin and '"[Worker] Backup finished"' in fin, (
        "el print bilingue debe permanecer en el finally (fallback IPC H3)"
    )
    assert "backup_finished" in fin and "_snap_path" in fin and "os.remove" in fin, (
        "el finally debe emitir el marcador Y limpiar los temporales (H6)"
    )
    assert fin.index("backup_finished") < fin.index("_snap_path"), (
        "la limpieza va DESPUES del marcador: un fallo borrando archivos jamas "
        "puede tragarse el fin incondicional del ciclo"
    )


# ═══════════════════════════════════════════════════════════════════════
# H7 — validacion de server.properties y bindings de la fachada
# ═══════════════════════════════════════════════════════════════════════
def test_validate_rechaza_saltos_de_linea_inyectables():
    """server-name con \n escribia lineas ARBITRARIAS en server.properties
    (fuera de la lista de campos editables)."""
    ok, detalle = props_service._validate_props(
        {"server-name": "Hacked\nserver-port=1\ngamemode=creative"})
    assert ok is False and "control" in detalle


def test_validate_rechaza_enteros_no_canonicos():
    for bad in (" 12 ", "+12", "012"):
        ok, _ = props_service._validate_props({"max-players": bad})
        assert ok is False, bad
    ok, _ = props_service._validate_props({"max-players": "12"})
    assert ok is True


def test_validate_aceita_valores_normales():
    ok, detalle = props_service._validate_props(
        {"server-name": "Mi Servidor", "max-players": "20", "gamemode": "survival"})
    assert ok is True, detalle


def test_fachada_no_reexporta_scalares_mutables():
    """`from x import nombre` fija una COPIA del binding al importar: la
    fachada no debe re-exportar escalares mutables (trampa para edits/tests;
    el patron operativo es wrapper_schedule.X / wstate.X)."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "server_wrapper.py"),
               encoding="utf-8").read()
    assert "\n    last_daily_backup_date,\n" not in src, (
        "re-export stale de un escalar mutable: usar wrapper_schedule.X"
    )
    # y el codigo de produccion debe seguir usandolo SIEMPRE con prefijo
    body = src.split("def backup_scheduler")[1]
    assert "wrapper_schedule.last_daily_backup_date" in body
    assert " last_daily_backup_date" not in body.replace(
        "wrapper_schedule.last_daily_backup_date", "")


def test_cierre_crash_comparte_lock_y_tope_del_cierre_normal():
    """El backup de emergencia por crash debe usar el MISMO dominio de lock y
    wait timeout que el de cierre normal (pre-fix: lambda sin external_lock)."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "server_wrapper.py"),
               encoding="utf-8").read()
    assert 'threading.Thread(target=execute_final_backup, args=("cierre_crash",)' in src
    assert 'auto_backup.create_backup("cierre_crash")' not in src
