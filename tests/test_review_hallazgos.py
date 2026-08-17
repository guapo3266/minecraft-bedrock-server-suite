# -*- coding: utf-8 -*-
"""Verificacion REAL de hallazgos de revision (2026-08-03).

Cada test reproduce el escenario con el codigo real de la app; solo se
sustituyen E/S externas (red, reloj, esperas de proceso) cuando el escenario
lo exige. Los tests documentan el COMPORTAMIENTO ACTUAL observado:
- Los que confirman un defecto dejan una assertion que FALLA si el defecto
  se corrige (regresion hacia la correccion).
- Los que descartan un hallazgo afirman el comportamiento correcto.

Escenarios E2E con servidor real (BDS) estan marcados @pytest.mark.e2e y se
saltan si no hay bedrock_server.exe.
"""
import datetime
import glob
import io
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_backup
import wrapper_backup
import wrapper_state as wstate
import server_gui_server as gui
import gui_backend.config as config
import gui_backend.supervisor as supervisor
import gui_backend.services.bds_update as bds_update

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR_REAL = auto_backup.BACKUP_DIR


# ═══════════════════════════════════════════════════════════════════════
# Fixtures / helpers
# ═══════════════════════════════════════════════════════════════════════
def _fake_env(monkeypatch, tmp_path):
    """Mundo y directorio de backups falsos (mismo patron que el resto de la suite)."""
    fake_world = os.path.join(str(tmp_path), "world")
    fake_bkp = os.path.join(str(tmp_path), "backups")
    os.makedirs(fake_world)
    os.makedirs(fake_bkp)
    monkeypatch.setattr(auto_backup, "WORLD_DIR", fake_world)
    monkeypatch.setattr(auto_backup, "BACKUP_DIR", fake_bkp)
    monkeypatch.setattr(auto_backup, "BASE_DIR", str(tmp_path))
    return fake_world, fake_bkp


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def _reset_manager_state():
    gui.manager.is_running = False
    gui.manager.start_time = None
    gui.manager.wrapper_process = None
    gui.manager.update_in_progress = False
    gui.manager.backup_in_progress = False
    gui.manager.players_online.clear()
    gui.manager.wrapper_exit_event.set()
    gui.manager.server_stopped_event.set()


# ═══════════════════════════════════════════════════════════════════════
# F1 / G4: /api/check_update — la version instalada nunca se conoce
# ═══════════════════════════════════════════════════════════════════════
def test_release_notes_actual_no_contiene_version():
    """El release-notes.txt real no tiene version: sin la captura del log de
    BDS (FIX F1), la version instalada quedaria desconocida (None), nunca un
    fallback fijo 1.21.0.0."""
    p = os.path.join(BASE_DIR, "release-notes.txt")
    if not os.path.exists(p) or not os.path.exists(os.path.join(BASE_DIR, "bedrock_server.exe")):
        # H3: el repo desnudo (sin instalacion de servidor) no tiene estos
        # artefactos; el test aplica solo donde BDS esta instalado.
        pytest.skip("requiere instalacion de servidor (release-notes.txt y bedrock_server.exe)")
    content = open(p, encoding="utf-8", errors="replace").read()
    assert not __import__("re").search(r"\d+\.\d+\.\d+\.\d+", content), (
        "si release-notes.txt tuviera version, el fallback cambiaria"
    )
    # Evidencia del boot real (smoke test 2026-08-03): "Version: 1.26.33.2"
    assert os.path.exists(os.path.join(BASE_DIR, "bedrock_server.exe"))


def test_check_update_usa_version_instalada_del_log(monkeypatch):
    """CORREGIDO (F1): la version instalada se captura del log de BDS; con la
    misma version en la pagina (formato antiguo) NO se anuncia update."""
    from fastapi.testclient import TestClient

    html = (
        '<a href="https://www.minecraft.net/bedrockdedicatedserver/bin-win/'
        'bedrock-server-1.26.33.2.zip">descargar</a>'
    )

    class FakeResp:
        status_code = 200
        text = html
        headers = {}

        def iter_content(self, chunk_size=8192):
            yield b"x"

    monkeypatch.setattr(bds_update.requests, "get", lambda *a, **k: FakeResp())
    gui.manager.installed_version = "1.26.33.2"
    try:
        with TestClient(gui.app, client=("127.0.0.1", 50000)) as c:
            j = c.get("/api/check_update").json()
            assert j["current_version"] == "1.26.33.2", j
            assert j["has_update"] is False, j
            assert j["unavailable"] is False, j
            assert j["download_url"], j
    finally:
        gui.manager.installed_version = None


def test_check_update_detecta_update_real(monkeypatch):
    """F1: con la version instalada conocida y una pagina con version mas
    nueva (formato antiguo), has_update es True (comparacion real)."""
    from fastapi.testclient import TestClient

    html = (
        '<a href="https://www.minecraft.net/bedrockdedicatedserver/bin-win/'
        'bedrock-server-1.26.33.2.zip">descargar</a>'
    )

    class FakeResp:
        status_code = 200
        text = html
        headers = {}

        def iter_content(self, chunk_size=8192):
            yield b"x"

    monkeypatch.setattr(bds_update.requests, "get", lambda *a, **k: FakeResp())
    gui.manager.installed_version = "1.21.0.0"
    try:
        with TestClient(gui.app, client=("127.0.0.1", 50000)) as c:
            j = c.get("/api/check_update").json()
            assert j["current_version"] == "1.21.0.0", j
            assert j["latest_version"] == "1.26.33.2", j
            assert j["has_update"] is True, j
    finally:
        gui.manager.installed_version = None


@pytest.mark.e2e
def test_check_update_api_real_mojang_detecta_version():
    """CORREGIDO (F1): el endpoint usa la API interna de la web de Mojang
    (/api/v1.0/download/links); con red, debe detectar la version estable
    real (no reportar NO DISPONIBLE). Se salta si no hay red."""
    import requests as req

    from fastapi.testclient import TestClient

    try:
        r = req.get(
            "https://net-secondary.web.minecraft-services.net/api/v1.0/download/links",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        assert r.status_code == 200
        links = r.json().get("result", {}).get("links", [])
    except Exception as e:
        pytest.skip("sin red: %s" % e)

    win = [l for l in links if l.get("downloadType") == "serverBedrockWindows"]
    assert win, "la API cambio de formato; actualizar el hallazgo: %s" % links[:3]

    with TestClient(gui.app, client=("127.0.0.1", 50000)) as c:
        j = c.get("/api/check_update").json()
    assert j["unavailable"] is False, j
    assert j["latest_version"] is not None, j
    assert j["download_url"] == win[0]["downloadUrl"], j
    # Si la version instalada es conocida y mas vieja, debe ofrecer la actualizacion
    if j["current_version"] and bds_update._version_tuple(j["latest_version"]) > bds_update._version_tuple(j["current_version"]):
        assert j["has_update"] is True, j


# ═══════════════════════════════════════════════════════════════════════
# F2: la GUI nunca marca backup_in_progress en backups calientes
# (desajuste de acento: wrapper imprime "compresion", GUI busca "compresión")
# ═══════════════════════════════════════════════════════════════════════
def test_gui_busca_la_cadena_exacta_del_wrapper():
    """CORREGIDO (F2): la GUI busca la cadena EXACTA que imprime el wrapper
    ('Iniciando compresion', sin acento), y la condicion EXTERNA de la rama
    no excluye la linea del worker (sin 'backup' y sin 'compresión')."""
    src = open(os.path.join(BASE_DIR, "wrapper_backup.py"), encoding="utf-8").read()
    gui_src = open(os.path.join(BASE_DIR, "gui_backend", "supervisor.py"), encoding="utf-8").read()
    gui_thread = gui_src.split("def run_wrapper_thread")[1]
    assert "Starting compression in a separate process" in src
    assert (
        '"Starting compression in a separate process" in line_str' in gui_thread
    )
    assert "Iniciando compresión" not in gui_thread
    # condicion de la rama de clasificacion: debe incluir "compres" (prefijo
    # comun de "compresion"/"compresión"), porque la linea real del worker no
    # contiene "backup" ni "compresión" acentuada. La clasificacion vive en
    # classify_log_line (unica fuente de verdad) y el hilo la consume.
    gui_classify = gui_src.split("def classify_log_line")[1].split("def run_wrapper_thread")[0]
    assert '"compres"' in gui_classify
    assert "classify_log_line(line_str)" in gui_thread
    linea_real = (
        "[Worker] Starting compression in a separate process (subprocess)..."
    )
    assert any(k in linea_real.lower() for k in ("backup", "compres", "save query"))


@pytest.mark.e2e
@pytest.mark.skipif(
    not os.path.exists(os.path.join(BASE_DIR, "bedrock_server.exe")),
    reason="requiere bedrock_server.exe",
)
def test_e2e_gui_flag_backup_in_progress_nunca_true_caliente():
    """E2E real: GUI + wrapper + BDS + worker. El ciclo caliente se ejecuta de
    verdad (nace un zip auto_backup_periodico_*) y la GUI recibe la linea
    '[Worker] Iniciando compresion de archivos...' por su WebSocket, pero
    /api/status nunca devuelve backup_in_progress=True (DEFECTO confirmado)."""
    import urllib.request

    from websockets.sync.client import connect as ws_connect

    port = 18231
    base_url = "http://127.0.0.1:%d" % port
    props_path = os.path.join(BASE_DIR, "server.properties")
    orig_props = open(props_path, "rb").read()
    world_dir = os.path.join(BASE_DIR, "worlds", "TestWorld")
    world_existed = os.path.exists(world_dir)  # nunca borrar un mundo preexistente
    created_zips = []
    gui_proc = None
    ws = None
    logs = []
    # H3: BACKUP_DIR es por servidor y la subcarpeta nace con el primer backup;
    # el baseline del E2E la crea si aun no existe.
    os.makedirs(BACKUP_DIR_REAL, exist_ok=True)
    baseline = set(os.listdir(BACKUP_DIR_REAL))

    def api(method, path, timeout=10):
        url = base_url + path
        data = None
        headers = {}
        if method == "POST":
            data = b""
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", errors="replace")

    log_seen = [0]
    status_seen = []  # snapshots de status emitidos por la GUI via WS

    def wait_for_new_log(pred, timeout):
        """Espera un mensaje de log NUEVO (no visto aun: log_seen)."""
        end = time.time() + timeout
        while True:
            while log_seen[0] < len(logs):
                t = logs[log_seen[0]]
                log_seen[0] += 1
                if pred(t):
                    return True
            if time.time() >= end:
                return False
            try:
                msg = ws.recv(timeout=0.5)
                if msg is None:
                    continue
                import json as _json

                obj = _json.loads(msg)
                if obj.get("type") == "log":
                    logs.append(obj["data"].get("text", ""))
                elif obj.get("type") == "status":
                    status_seen.append(obj.get("data") or {})
            except Exception:
                pass

    try:
        # ── preparar mundo de prueba y propiedades ──
        props = orig_props.decode("utf-8")
        props = props.replace("level-name=Bedrock level", "level-name=TestWorld")
        open(props_path, "wb").write(props.encode("utf-8"))
        os.makedirs(world_dir, exist_ok=True)

        # ── arrancar la GUI real ──
        env = os.environ.copy()
        env["GUI_PORT"] = str(port)
        env["BROWSER"] = "cmd /c exit"
        env["PYTHONUNBUFFERED"] = "1"
        gui_proc = subprocess.Popen(
            [sys.executable, "-u", os.path.join(BASE_DIR, "server_gui_server.py")],
            cwd=BASE_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )
        ready = False
        for _ in range(200):
            try:
                st, body = api("GET", "/api/status", timeout=2)
                if st == 200:
                    ready = True
                    break
            except Exception:
                pass
            if gui_proc.poll() is not None:
                out = gui_proc.stdout.read().decode(errors="replace")
                raise AssertionError("la GUI murio al arrancar:\n%s" % out[-2000:])
            time.sleep(0.3)
        assert ready, "la GUI no respondio en 60s"

        ws = ws_connect("ws://127.0.0.1:%d/ws" % port)

        # ── iniciar servidor y esperar BDS listo ──
        st, _ = api("POST", "/api/action/start")
        assert '"starting"' in _ or "starting" in _, (st, _[:200])
        assert wait_for_new_log(lambda t: "Server started." in t, 240), (
            "BDS no arranco; logs: %s" % logs[-20:]
        )

        # ── ciclo de backup caliente (hasta 4 intentos, con pausa entre ellos:
        #    en mundos recien creados el chequeo de cobertura 70% da falso
        #    positivo mientras LevelDB estabiliza; ver
        #    test_cobertura_70_falso_positivo_mundo_pequeno) ──
        saw_in_progress = False
        saw_zip = None
        saw_exitosa = False
        fallida_count = 0
        last_backup_updates = 0

        for _attempt in range(4):
            if _attempt > 0:
                time.sleep(15)
            st, _ = api("POST", "/api/action/backup")
            assert "hot_backup_dispatched" in _, (st, _[:200])
            end = time.time() + 100
            cycle_done = False
            while time.time() < end and not cycle_done:
                try:
                    st, body = api("GET", "/api/status", timeout=2)
                    j = __import__("json").loads(body)
                except Exception:
                    j = {}
                if j.get("backup_in_progress"):
                    saw_in_progress = True
                if j.get("last_backup") and j.get("last_backup") != "Ninguno":
                    last_backup_updates += 1
                new_zips = [
                    f
                    for f in os.listdir(BACKUP_DIR_REAL)
                    if f not in baseline and f.startswith("auto_backup_") and "periodico" in f
                ]
                if new_zips:
                    saw_zip = new_zips[0]
                if saw_exitosa:
                    cycle_done = True
                    break
                if wait_for_new_log(lambda t: "Compression successful" in t, 1):
                    saw_exitosa = True
                    cycle_done = True
                    break
                if wait_for_new_log(lambda t: "Compression failed" in t, 1):
                    fallida_count += 1
                    cycle_done = True
                    break
                time.sleep(0.15)
            if saw_zip or saw_exitosa:
                break

        # last_backup_time se actualiza DESPUES del zip (al llegar la linea
        # "Compresión exitosa"): esperar ese rezago antes de evaluar.
        end = time.time() + 15
        while time.time() < end:
            try:
                st, body = api("GET", "/api/status", timeout=2)
                j = __import__("json").loads(body)
            except Exception:
                j = {}
            if j.get("last_backup") and j.get("last_backup") != "Ninguno":
                last_backup_updates += 1
                break
            time.sleep(0.3)

        # ── assertions del FIX (F2) ──
        # evidencia retrospectiva sobre TODOS los logs recibidos:
        recibio_linea_inicio = any(
            "Starting compression in a separate process" in t for t in logs
        )
        assert recibio_linea_inicio, (
            "la GUI debio recibir la linea del worker; logs: %s"
            % [t for t in logs if "omp" in t][-5:]
        )
        # el flag se observa por dos vias: polling HTTP y los snapshots de
        # status que la GUI emite por WS al recibir la linea (senal del fix)
        flag_true_en_ws = any(
            s.get("backup_in_progress") for s in status_seen
        )
        assert saw_in_progress or flag_true_en_ws, (
            "el flag backup_in_progress debio ponerse True durante la compresion "
            "(fix F2); http=%s ws=%s zip=%s exitosa=%s"
            % (saw_in_progress, flag_true_en_ws, saw_zip, saw_exitosa)
        )
        assert saw_zip is not None or saw_exitosa or fallida_count > 0, (
            "ningun ciclo caliente llego al worker; logs: %s" % logs[-15:]
        )
        if saw_zip is not None or saw_exitosa:
            assert last_backup_updates > 0, "last_backup_time nunca se actualizo"

        # ── Fase G1 (real): update_bds con el servidor encendido debe DETENER
        # el servidor antes de tocar nada (fix G1). Solo se ejecuta si la
        # pagina actual de Mojang no expone el zip: si algun dia la pagina
        # vuelve a exponerlo, no se corre un update real en el E2E.
        try:
            st, body = api("GET", "/api/check_update", timeout=20)
            j = __import__("json").loads(body)
            page_ok = j.get("unavailable") is True
        except Exception:
            page_ok = False
        if page_ok:
            st, _ = api("POST", "/api/action/update_bds")
            assert "update_dispatched" in _, (st, _[:200])
            assert wait_for_new_log(
                lambda t: "Deteniendo servidor de Minecraft" in t, 30
            ), "el update debio detener el servidor (fix G1); logs: %s" % logs[-10:]
            assert wait_for_new_log(
                lambda t: "No se pudo obtener la URL de descarga oficial. Abortando." in t,
                60,
            ), "el update debio abortar (pagina sin zip); logs: %s" % logs[-10:]
    finally:
        # ── apagado limpio y limpieza ──
        try:
            api("POST", "/api/action/stop", timeout=5)
        except Exception:
            pass
        for _ in range(300):
            try:
                st, body = api("GET", "/api/status", timeout=2)
                j = __import__("json").loads(body)
                if j.get("running") is False:
                    break
            except Exception:
                break
            time.sleep(0.5)
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        if gui_proc is not None:
            try:
                gui_proc.kill()
                gui_proc.wait(timeout=10)
            except Exception:
                pass
        # restaurar props (flush+close explícito: si la config del servidor no
        # puede restaurarse, el test debe FALLAR visible, nunca dejarla tocada)
        with open(props_path, "wb") as f:
            f.write(orig_props)
        # borrar el mundo SOLO si el test lo creo (nunca un mundo preexistente)
        if not world_existed:
            for _ in range(10):
                try:
                    shutil.rmtree(world_dir, ignore_errors=True)
                    if not os.path.exists(world_dir):
                        break
                except Exception:
                    time.sleep(1)
        # borrar zips creados por el test
        for f in os.listdir(BACKUP_DIR_REAL):
            if f not in baseline:
                try:
                    os.remove(os.path.join(BACKUP_DIR_REAL, f))
                except Exception:
                    pass


# ═══════════════════════════════════════════════════════════════════════
# F3: lectura snapshot sin tope de RAM por archivo
# ═══════════════════════════════════════════════════════════════════════
def test_lectura_snapshot_streaming_pico_ram_constante(monkeypatch, tmp_path):
    """CORREGIDO (F3): la copia es en streaming por chunks; un archivo de
    128MB ya no dispara un pico de RAM de 128MB (el pico debe ser < 64MB)."""
    import psutil

    fake_world, fake_bkp = _fake_env(monkeypatch, tmp_path)
    big = os.path.join(fake_world, "big.bin")
    with open(big, "wb") as f:
        chunk = b"\x00" * (1024 * 1024)
        for _ in range(128):
            f.write(chunk)
    size = os.path.getsize(big)
    _write(os.path.join(fake_world, "level.dat"), b"L" * 100)
    snapshot = [("level.dat", 100), ("big.bin", size)]

    proc = psutil.Process(os.getpid())
    rss0 = proc.memory_info().rss
    peak = {"rss": rss0}
    stop = threading.Event()

    def watch():
        while not stop.is_set():
            r = proc.memory_info().rss
            if r > peak["rss"]:
                peak["rss"] = r
            time.sleep(0.01)

    t = threading.Thread(target=watch, daemon=True)
    t.start()
    try:
        result = auto_backup.create_backup("mem_test", file_snapshot=snapshot)
    finally:
        stop.set()
        t.join()
    assert result, "el backup debio completarse"
    delta = peak["rss"] - rss0
    assert delta < 64 * 1024 * 1024, (
        "pico de RAM %d MB: la copia deberia ser streaming, no cargar el "
        "archivo entero (128MB)" % (delta // (1024 * 1024))
    )


# ═══════════════════════════════════════════════════════════════════════
# F4: trigger_name sin sanitizar puede escapar de BACKUP_DIR
# ═══════════════════════════════════════════════════════════════════════
def test_trigger_name_no_escapa_de_backup_dir(monkeypatch, tmp_path):
    """CORREGIDO (F4): trigger_name se sanea; con separadores y '..' el zip
    queda dentro de BACKUP_DIR y con nombre saneado (antes escapaba)."""
    fake_world, fake_bkp = _fake_env(monkeypatch, tmp_path)
    _write(os.path.join(fake_world, "level.dat"), b"L" * 100)

    trav = "..\\..\\..\\escape_review"
    result = auto_backup.create_backup(trav)
    assert result, "el backup debio completarse"
    absz = os.path.abspath(result)
    bkp_abs = os.path.abspath(fake_bkp)
    assert absz.startswith(bkp_abs + os.sep), (
        "el zip escapo de BACKUP_DIR: %s" % absz
    )
    assert os.path.exists(absz), absz
    assert os.path.basename(absz).startswith("auto_backup_"), os.path.basename(absz)
    assert ".." not in os.path.basename(absz), os.path.basename(absz)


# ═══════════════════════════════════════════════════════════════════════
# F5: _run_backup_process es codigo muerto
# ═══════════════════════════════════════════════════════════════════════
def test_run_backup_process_eliminado():
    """CORREGIDO: _run_backup_process (legacy del enfoque multiprocessing)
    fue eliminado de server_wrapper.py; el worker real es backup_worker.py."""
    wrapper_src = open(os.path.join(BASE_DIR, "server_wrapper.py"), encoding="utf-8").read()
    backup_src = open(os.path.join(BASE_DIR, "wrapper_backup.py"), encoding="utf-8").read()
    assert "_run_backup_process" not in wrapper_src
    assert "_run_backup_process" not in backup_src


# ═══════════════════════════════════════════════════════════════════════
# G1: update_bds puede saltarse el 'stop' durante el arranque del servidor
# ═══════════════════════════════════════════════════════════════════════
class _FakeStdin:
    def __init__(self):
        self.lines = []

    def write(self, s):
        self.lines.append(s)

    def flush(self):
        pass


class _FakeStdout:
    def __init__(self, release):
        self.release = release

    def readline(self):
        self.release.wait(30)
        return ""


class _FakeProc:
    """Proceso wrapper simulado: registra lo escrito en stdin y bloquea la
    lectura de stdout hasta que el test libere el evento."""

    def __init__(self, release):
        self.stdin = _FakeStdin()
        self.stdout = _FakeStdout(release)

    def wait(self):
        return 0

    def poll(self):
        return None


def test_update_bds_detiene_servidor_antes_de_aplicar(monkeypatch):
    """CORREGIDO (G1): el subproceso del wrapper se crea bajo op_lock en
    start; update_bds ve wrapper_process y SI detiene el servidor antes de
    aplicar binarios (antes se saltaba el stop y aplicaba con el servidor
    arrancando)."""
    from fastapi.testclient import TestClient

    _reset_manager_state()
    release = threading.Event()
    fake_proc = _FakeProc(release)
    monkeypatch.setattr(supervisor, "_spawn_wrapper_process", lambda: fake_proc)

    zip_bytes = io.BytesIO()
    with zipfile.ZipFile(zip_bytes, "w") as z:
        z.writestr("bedrock_server.exe", b"fake")
    payload = zip_bytes.getvalue()
    html = (
        '<a href="https://www.minecraft.net/bedrockdedicatedserver/bin-win/'
        'bedrock-server-1.26.33.2.zip">x</a>'
    )

    class FakeResp:
        status_code = 200
        text = html
        headers = {}

        def iter_content(self, chunk_size=8192):
            for i in range(0, len(payload), chunk_size):
                yield payload[i : i + chunk_size]

    monkeypatch.setattr(bds_update.requests, "get", lambda *a, **k: FakeResp())
    monkeypatch.setattr(
        gui.auto_backup, "create_backup", lambda *a, **k: "dummy_pre_update.zip"
    )
    record = {}

    def fake_apply(staging_dir, base_dir, preserve_files, preserve_dirs,
                   keep_prev_dir=None, prev_version=None):
        record["called"] = True
        record["is_running"] = gui.manager.is_running
        record["wrapper_process"] = gui.manager.wrapper_process

    monkeypatch.setattr(bds_update, "_apply_staged_update", fake_apply)

    try:
        with TestClient(gui.app, client=("127.0.0.1", 50000)) as c:
            r1 = c.post("/api/action/start")
            assert r1.json().get("status") == "starting", r1.text
            r2 = c.post("/api/action/update_bds")
            assert r2.json().get("status") == "update_dispatched", r2.text
            # el update debe escribir el stop al wrapper (fix G1)
            end = time.time() + 10
            while not fake_proc.stdin.lines and time.time() < end:
                time.sleep(0.05)
            assert "stop\n" in fake_proc.stdin.lines, fake_proc.stdin.lines
            # liberar el hilo del wrapper para que el update pueda continuar
            release.set()
            end = time.time() + 30
            while not record.get("called") and time.time() < end:
                time.sleep(0.2)
            assert record.get("called"), "update_bds no llego a aplicar binarios"
            assert record["is_running"] is False, (
                "los binarios se aplicaron con el servidor AUN encendido (defecto G1)"
            )
    finally:
        release.set()
        _reset_manager_state()
        # el fake de _apply_staged_update no limpia el staging que crea do_update
        shutil.rmtree(os.path.join(BASE_DIR, "bds_update_staging"), ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════
# G2: stop durante el arranque devuelve not_running y el servidor sigue
# ═══════════════════════════════════════════════════════════════════════
def test_stop_durante_arranque_ahora_es_efectivo(monkeypatch):
    """CORREGIDO (G2): tras start, wrapper_process ya existe (asignado bajo
    el lock); /stop responde 'stopping' y escribe el stop al wrapper (antes
    devolvia not_running y el servidor seguia arrancando)."""
    from fastapi.testclient import TestClient

    _reset_manager_state()
    release = threading.Event()
    fake_proc = _FakeProc(release)
    monkeypatch.setattr(supervisor, "_spawn_wrapper_process", lambda: fake_proc)

    try:
        with TestClient(gui.app, client=("127.0.0.1", 50000)) as c:
            r1 = c.post("/api/action/start")
            assert r1.json().get("status") == "starting", r1.text
            r2 = c.post("/api/action/stop")
            j = r2.json()
            assert j.get("status") == "stopping", j
            assert "stop\n" in fake_proc.stdin.lines, fake_proc.stdin.lines
    finally:
        release.set()
        _reset_manager_state()


# ═══════════════════════════════════════════════════════════════════════
# G3: restore no recupera el mundo si falla os.makedirs(WORLD_DIR)
# ═══════════════════════════════════════════════════════════════════════
def test_restore_recupera_mundo_si_falla_makedirs(monkeypatch, tmp_path):
    """CORREGIDO (G3): os.makedirs(WORLD_DIR) esta DENTRO del bloque de
    rollback; si falla, el mundo se recupera desde el respaldo .bak."""
    fake_world, fake_bkp = _fake_env(monkeypatch, tmp_path)
    _write(os.path.join(fake_world, "level.dat"), b"WORLD-ORIGINAL")
    assert auto_backup.create_backup("inicio"), "zip de prueba no creado"
    zips = glob.glob(os.path.join(fake_bkp, "*.zip"))
    assert len(zips) == 1

    orig_makedirs = os.makedirs

    def raiser(p, *a, **k):
        if os.path.abspath(p).startswith(os.path.abspath(fake_world)):
            raise OSError("permiso denegado (simulado)")
        return orig_makedirs(p, *a, **k)

    monkeypatch.setattr(os, "makedirs", raiser)

    # el rollback envuelve el fallo en RuntimeError (diseño existente)
    with pytest.raises(RuntimeError):
        auto_backup.restore_backup(os.path.basename(zips[0]))

    # el mundo original permanece intacto tras el fallo
    assert os.path.exists(fake_world), "el mundo debio recuperarse tras el fallo"
    assert os.path.exists(os.path.join(fake_world, "level.dat"))
    assert open(os.path.join(fake_world, "level.dat"), "rb").read() == b"WORLD-ORIGINAL"
    assert not os.path.exists(fake_world + ".bak"), "el .bak debio limpiarse"


# ═══════════════════════════════════════════════════════════════════════
# G5: backups frios manuales duplicados en el mismo segundo se pisan
# ═══════════════════════════════════════════════════════════════════════
def test_backup_frio_duplicado_rechazado_con_409(monkeypatch, tmp_path):
    """CORREGIDO (G5): con un backup en frio en curso, un segundo clic se
    rechaza con 409 (antes apilaba hilos y podia pisar el primer zip)."""
    from fastapi.testclient import TestClient

    _reset_manager_state()
    fake_world, fake_bkp = _fake_env(monkeypatch, tmp_path)
    _write(os.path.join(fake_world, "level.dat"), b"V1")
    try:
        gui.manager.backup_in_progress = True
        with TestClient(gui.app, client=("127.0.0.1", 50000)) as c:
            r = c.post("/api/action/backup")
            j = r.json()
            assert j.get("status") == "busy", j
            assert "backup" in j.get("message", "").lower(), j
    finally:
        _reset_manager_state()


def test_backup_nombres_unicos_mismo_segundo(monkeypatch, tmp_path):
    """CORREGIDO (G5): dos backups creados con el reloj congelado (mismo
    segundo) ya no colisionan: el nonce aleatorio garantiza nombres unicos y
    el primer zip NO se pierde."""
    fake_world, fake_bkp = _fake_env(monkeypatch, tmp_path)

    fixed = datetime.datetime(2026, 8, 3, 12, 0, 0)

    class FakeDT(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    monkeypatch.setattr(auto_backup.datetime, "datetime", FakeDT)

    lvl = os.path.join(fake_world, "level.dat")
    _write(lvl, b"V1")
    r1 = auto_backup.create_backup("gui_manual")
    assert r1, "primer backup fallo"
    _write(lvl, b"V2")
    r2 = auto_backup.create_backup("gui_manual")
    assert r2, "segundo backup fallo"
    assert r1 != r2, "los nombres colisionaron (nonce ausente)"
    zips = sorted(glob.glob(os.path.join(fake_bkp, "*.zip")))
    assert len(zips) == 2, zips
    with zipfile.ZipFile(r1) as zf:
        assert zf.read("level.dat") == b"V1"
    with zipfile.ZipFile(r2) as zf:
        assert zf.read("level.dat") == b"V2"


def test_backup_frio_recheck_bajo_lock(monkeypatch, tmp_path):
    """CORREGIDO (G5): el re-chequeo atomico bajo op_lock descarta el backup
    si otro ya entro en curso mientras el hilo esperaba el lock."""
    from fastapi.testclient import TestClient

    _reset_manager_state()
    fake_world, fake_bkp = _fake_env(monkeypatch, tmp_path)
    _write(os.path.join(fake_world, "level.dat"), b"V1")
    calls = []
    monkeypatch.setattr(
        gui.auto_backup,
        "create_backup",
        lambda *a, **k: calls.append(1) or os.path.join(fake_bkp, "dummy.zip"),
    )
    try:
        with TestClient(gui.app, client=("127.0.0.1", 50000)) as c:
            gui.manager.op_lock.acquire()  # el hilo del backup queda bloqueado
            r1 = c.post("/api/action/backup")
            assert r1.json().get("status") == "backup_dispatched", r1.text
            time.sleep(0.5)  # el hilo esta esperando op_lock
            gui.manager.backup_in_progress = True  # otro backup "en curso"
            gui.manager.op_lock.release()
            time.sleep(0.5)
            assert calls == [], (
                "el re-check bajo op_lock debio descartar el backup: %s" % calls
            )
    finally:
        _reset_manager_state()


# ═══════════════════════════════════════════════════════════════════════
# Hallazgo nuevo (reproducido en smoke test real 2026-08-03):
# chequeo de cobertura 70% da falso positivo en mundos pequenos
# ═══════════════════════════════════════════════════════════════════════
def test_cobertura_70_mundo_pequeno_sin_falso_positivo(monkeypatch, tmp_path):
    """Snapshot autoritativo de save query se acepta sin falsos desyncs."""
    fake_world, fake_bkp = _fake_env(monkeypatch, tmp_path)
    _write(os.path.join(fake_world, "level.dat"), b"L" * 100)
    _write(os.path.join(fake_world, "db", "CURRENT"), b"MANIFEST-000002")
    _write(os.path.join(fake_world, "db", "MANIFEST-000002"), b"M" * 50)
    _write(os.path.join(fake_world, "db", "000003.log"), b"D" * 3055)

    snapshot = [
        ("level.dat", 100),
        ("db/CURRENT", 15),
        ("db/MANIFEST-000002", 50),
    ]
    result = auto_backup.create_backup("periodico", file_snapshot=snapshot)
    assert result, "el backup 2-de-3 debio completarse (sin falso desync)"


def test_cobertura_70_rechaza_snapshot_genuinamente_pobre(monkeypatch, tmp_path):
    """Snapshot sin level.dat se rechaza de forma determinista."""
    fake_world, fake_bkp = _fake_env(monkeypatch, tmp_path)
    _write(os.path.join(fake_world, "level.dat"), b"L" * 100)
    _write(os.path.join(fake_world, "db", "CURRENT"), b"MANIFEST-000002")

    snapshot = [
        ("db/CURRENT", 15),
    ]
    with pytest.raises(auto_backup.SnapshotDesyncError):
        auto_backup.create_backup("periodico", file_snapshot=snapshot)


# ═══════════════════════════════════════════════════════════════════════
# D3: raiz efectiva del staging del update (zip oficial validado: plano)
# ═══════════════════════════════════════════════════════════════════════
def test_resolve_update_root_plano_prefijo_y_ambiguo(tmp_path):
    """D3: _resolve_update_root maneja el zip plano (forma oficial actual,
    validado con bedrock-server-1.26.33.2 real: exe en la raiz), la forma
    historica con una unica carpeta raiz, y falla cerrada ante estructuras
    ambiguas."""
    # plano (zip oficial actual)
    flat = os.path.join(str(tmp_path), "flat")
    os.makedirs(flat)
    _write(os.path.join(flat, "bedrock_server.exe"), b"x")
    _write(os.path.join(flat, "allowlist.json"), b"x")
    assert bds_update._resolve_update_root(flat) == flat

    # una unica carpeta raiz (forma historica)
    pref = os.path.join(str(tmp_path), "pref")
    inner = os.path.join(pref, "bedrock-server-1.26.33.2")
    os.makedirs(inner)
    _write(os.path.join(inner, "bedrock_server.exe"), b"x")
    assert bds_update._resolve_update_root(pref) == inner

    # estructura ambigua: falla cerrada (no toca nada)
    amb = os.path.join(str(tmp_path), "amb")
    os.makedirs(os.path.join(amb, "a"))
    os.makedirs(os.path.join(amb, "b"))
    _write(os.path.join(amb, "a", "bedrock_server.exe"), b"x")
    _write(os.path.join(amb, "b", "bedrock_server.exe"), b"x")
    with pytest.raises(RuntimeError):
        bds_update._resolve_update_root(amb)


# ═══════════════════════════════════════════════════════════════════════
# D4: el kill del worker limpia los .tmp huerfanos de inmediato
# ═══════════════════════════════════════════════════════════════════════
def test_kill_worker_limpia_tmp_huerfanos(monkeypatch, tmp_path):
    """D4: _force_kill_compress_process elimina los .tmp que dejo el worker
    muerto (antes quedaban huerfanos hasta el siguiente backup)."""
    import server_wrapper as sw

    fake_bkp = os.path.join(str(tmp_path), "backups")
    os.makedirs(fake_bkp)
    orphan = os.path.join(fake_bkp, "auto_backup_x.zip.tmp")
    _write(orphan, b"parcial")
    monkeypatch.setattr(sw.auto_backup, "BACKUP_DIR", fake_bkp)

    class FakeProc:
        def is_alive(self):
            return True

        def kill(self):
            pass

        def join(self):
            pass

    fp = FakeProc()
    monkeypatch.setattr(wstate, "active_compress_process", fp)
    monkeypatch.setattr(wstate, "backup_ipc_lock", wstate.multiprocessing.Lock())

    sw._force_kill_compress_process(fp)
    assert not os.path.exists(orphan), "el .tmp huerfano debio eliminarse"


# ═══════════════════════════════════════════════════════════════════════
# D5: patrones de deteccion del log de BDS centralizados (una sola fuente)
# ═══════════════════════════════════════════════════════════════════════
def test_patrones_bds_centralizados_y_matchean_log_real():
    """D5: los patrones de deteccion del log de BDS viven en server_wrapper
    (constantes/regex) y matchean las lineas reales del formato actual de BDS
    (capturadas en el smoke test con BDS 1.26.33.2). La GUI los importa."""
    import server_wrapper as sw

    line_conn = "[2026-08-03 16:22:53:363 INFO] Player connected: Bob, xuid: 12345"
    line_disc = "[2026-08-03 16:22:53:363 INFO] Player disconnected: Bob, xuid: 12345"
    line_save = "[2026-08-03 16:22:58:376 INFO] Data saved. Files are now ready to be copied."
    line_list = "[2026-08-03 16:23:45:368 INFO] There are 0/20 players online:"

    m = sw._RE_PLAYER_CONNECT.search(sw._strip_log_prefix(line_conn).strip())
    assert m and m.group(1).strip() == "Bob", m
    assert sw._RE_PLAYER_DISCONNECT.search(sw._strip_log_prefix(line_disc).strip())
    assert sw.BDS_SAVE_READY in line_save
    assert sw._RE_PLAYERS_LIST.search(sw._strip_log_prefix(line_list).strip())

    # la GUI importa los patrones del wrapper: sin regex duplicados
    gui_src = open(os.path.join(BASE_DIR, "gui_backend", "supervisor.py"), encoding="utf-8").read()
    assert (
        "from server_wrapper import _RE_PLAYER_CONNECT, _RE_PLAYER_DISCONNECT" in gui_src
    )
    assert "Player\\s+connected" not in gui_src


# ═══════════════════════════════════════════════════════════════════════
# G8: restart/update separan "BDS murió" de "wrapper terminó"
# ═══════════════════════════════════════════════════════════════════════
# Antes: restart/update esperaban wrapper_exit_event con 30s, pero ese evento
# solo llega tras el backup final de cierre del wrapper (tope interno 240s):
# con un mundo grande el reinicio se abortaba siempre aunque BDS ya se hubiera
# detenido. Ahora esperan DOS fases: server_stopped_event (BDS muerto) y luego
# wrapper_exit_event (wrapper completo) con WRAPPER_EXIT_TIMEOUT_SEC escalado.
def _fake_wrapper_proc():
    """Wrapper falso minimo para do_restart/do_update: solo stdin."""
    fake = _FakeStdin()
    return type("FakeWrapperProc", (), {"stdin": fake})(), fake


def _logs_since(log_history, start_idx):
    return [e["text"] for e in log_history[start_idx:]]


def test_restart_fase1_aborta_si_bds_no_se_detiene(monkeypatch):
    """G8-Fase1: si BDS nunca muere (server_stopped_event sin marcar), el
    restart aborta tras SERVER_STOP_TIMEOUT_SEC y NO lanza otro wrapper."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    _reset_manager_state()
    spawned = {"n": 0}
    monkeypatch.setattr(config, "SERVER_STOP_TIMEOUT_SEC", 0.3)

    def fake_spawn():
        spawned["n"] += 1

    monkeypatch.setattr(supervisor, "_spawn_wrapper_process", fake_spawn)
    proc, fake_stdin = _fake_wrapper_proc()
    gui.manager.is_running = True
    gui.manager.wrapper_process = proc
    gui.manager.wrapper_exit_event.clear()
    gui.manager.server_stopped_event.clear()
    log_start = len(gui.manager.log_history)
    try:
        with TestClient(gui.app, client=("127.0.0.1", 50000)) as c:
            r = c.post("/api/action/restart")
            assert r.json()["status"] == "restarting", r.text
            time.sleep(1.0)  # deja abortar al hilo do_restart
        assert spawned["n"] == 0, "se lanzo un wrapper con BDS vivo"
        assert "stop\n" in fake_stdin.lines, "el stop no se escribio al wrapper"
        logs = "\n".join(_logs_since(gui.manager.log_history, log_start))
        assert "did not stop" in logs and "Restart cancelled" in logs, logs
    finally:
        _reset_manager_state()


def test_restart_fase2_espera_backup_final_y_arranca(monkeypatch):
    """G8-Fase2: con BDS detenido (fase 1 ok) pero el wrapper aun haciendo el
    backup final de cierre, el restart ESPERA a wrapper_exit_event y luego
    lanza el wrapper nuevo (antes abortaba a los 30s con un mundo lento)."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    _reset_manager_state()
    spawned = {"n": 0}
    monkeypatch.setattr(config, "SERVER_STOP_TIMEOUT_SEC", 2)
    monkeypatch.setattr(config, "WRAPPER_EXIT_TIMEOUT_SEC", 2)
    proc, fake_stdin = _fake_wrapper_proc()

    def fake_spawn():
        spawned["n"] += 1
        return proc

    monkeypatch.setattr(supervisor, "_spawn_wrapper_process", fake_spawn)
    monkeypatch.setattr(supervisor, "run_wrapper_thread", lambda *a, **k: None)

    gui.manager.is_running = True
    gui.manager.wrapper_process = proc
    gui.manager.wrapper_exit_event.clear()
    gui.manager.server_stopped_event.clear()

    # BDS muere a los 0.1s; el wrapper sigue vivo hasta los 0.35s (backup final).
    def bds_muere():
        time.sleep(0.1)
        gui.manager.server_stopped_event.set()

    def wrapper_termina():
        time.sleep(0.35)
        # is_running antes del evento: visibilidad garantizada por el set().
        gui.manager.is_running = False
        gui.manager.wrapper_exit_event.set()

    threading.Thread(target=bds_muere, daemon=True).start()
    threading.Thread(target=wrapper_termina, daemon=True).start()
    try:
        with TestClient(gui.app, client=("127.0.0.1", 50000)) as c:
            r = c.post("/api/action/restart")
            assert r.json()["status"] == "restarting", r.text
            end = time.time() + 5
            while spawned["n"] == 0 and time.time() < end:
                time.sleep(0.05)
        assert spawned["n"] == 1, "el restart no lanzo el wrapper tras el backup final"
        assert "stop\n" in fake_stdin.lines
    finally:
        _reset_manager_state()


def test_restart_fase2_aborta_si_wrapper_nunca_termina(monkeypatch):
    """G8-Fase2: si el wrapper queda colgado (backup final que no termina),
    el restart aborta tras WRAPPER_EXIT_TIMEOUT_SEC con mensaje honesto y no
    lanza otro wrapper (dos wrappers pisando el mundo)."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    _reset_manager_state()
    spawned = {"n": 0}
    monkeypatch.setattr(config, "WRAPPER_EXIT_TIMEOUT_SEC", 0.3)

    def fake_spawn():
        spawned["n"] += 1

    monkeypatch.setattr(supervisor, "_spawn_wrapper_process", fake_spawn)
    proc, fake_stdin = _fake_wrapper_proc()
    gui.manager.is_running = True
    gui.manager.wrapper_process = proc
    gui.manager.wrapper_exit_event.clear()
    gui.manager.server_stopped_event.set()  # BDS ya murio
    log_start = len(gui.manager.log_history)
    try:
        with TestClient(gui.app, client=("127.0.0.1", 50000)) as c:
            r = c.post("/api/action/restart")
            assert r.json()["status"] == "restarting", r.text
            time.sleep(1.0)
        assert spawned["n"] == 0, "se lanzo un wrapper con el anterior aun vivo"
        logs = "\n".join(_logs_since(gui.manager.log_history, log_start))
        assert "wrapper did not finish" in logs and "Restart cancelled" in logs, logs
    finally:
        _reset_manager_state()


def test_update_bds_espera_fase2_antes_de_tocar_instalacion(monkeypatch):
    """G8-Fase2 (update): con BDS detenido pero el wrapper aun haciendo el
    backup final, update_bds espera y si el wrapper no termina, ABORTA sin
    hacer backup preventivo ni aplicar binarios (antes aplicaba con el
    wrapper vivo o abortaba con un mensaje falso de "no se detuvo")."""
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    _reset_manager_state()
    applied = {"backup": 0, "staged": 0}
    monkeypatch.setattr(config, "WRAPPER_EXIT_TIMEOUT_SEC", 0.3)
    proc, fake_stdin = _fake_wrapper_proc()

    def fake_backup(*a, **k):
        applied["backup"] += 1
        return "dummy.zip"

    def fake_apply(*a, **k):
        applied["staged"] += 1

    monkeypatch.setattr(gui.auto_backup, "create_backup", fake_backup)
    monkeypatch.setattr(bds_update, "_apply_staged_update", fake_apply)

    gui.manager.is_running = True
    gui.manager.wrapper_process = proc
    gui.manager.wrapper_exit_event.clear()
    gui.manager.server_stopped_event.set()  # BDS ya murio
    log_start = len(gui.manager.log_history)
    try:
        with TestClient(gui.app, client=("127.0.0.1", 50000)) as c:
            r = c.post("/api/action/update_bds")
            assert r.json()["status"] == "update_dispatched", r.text
            end = time.time() + 5
            while gui.manager.update_in_progress and time.time() < end:
                time.sleep(0.05)
        assert applied["backup"] == 0, "el backup preventivo corrio con el wrapper vivo"
        assert applied["staged"] == 0, "se aplicaron binarios con el wrapper vivo"
        logs = "\n".join(_logs_since(gui.manager.log_history, log_start))
        # El mensaje de cancelacion vive en lifecycle.stop_and_wait (generico
        # para update y rollback): "Operation cancelled".
        assert "wrapper did not finish" in logs and "Operation cancelled" in logs, logs
    finally:
        _reset_manager_state()
        shutil.rmtree(os.path.join(BASE_DIR, "bds_update_staging"), ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════
# H1: rotacion de backups marcados, zip publicado no borrable y carreras
# ═══════════════════════════════════════════════════════════════════════
def test_backup_publicado_no_se_borra_si_falla_getsize(monkeypatch, tmp_path):
    """H1: tras os.replace, un fallo de getsize/print (p.ej. antivirus
    bloqueando el zip recien publicado) NO debe borrarlo. Antes success=True
    iba despues de esas llamadas y el finally eliminaba el ZIP integro."""
    fake_world, fake_bkp = _fake_env(monkeypatch, tmp_path)
    _write(os.path.join(fake_world, "level.dat"), b"L" * 100)

    orig_getsize = os.path.getsize

    def flaky_getsize(path):
        if path.endswith(".zip"):
            raise OSError("bloqueado por antivirus (simulado)")
        return orig_getsize(path)

    monkeypatch.setattr(os.path, "getsize", flaky_getsize)

    result = auto_backup.create_backup("h1_getsize")
    assert result is False, "el backup debio reportar fallo (getsize lanzo)"
    zips = [f for f in os.listdir(fake_bkp) if f.endswith(".zip")]
    assert len(zips) == 1, f"el zip ya publicado fue borrado: {fake_bkp}"
    assert not os.listdir(fake_bkp) or all(
        not f.endswith(".tmp") for f in os.listdir(fake_bkp)
    ), "quedo un .tmp huerfano"


def test_restart_doble_simultaneo_no_lanza_dos_wrappers(monkeypatch):
    """H1: dos restarts simultaneos con el servidor apagado lanzan UN solo
    wrapper: do_restart marca is_running bajo op_lock en el spawn (igual que
    start). Antes, la ventana entre spawn y arranque del hilo permitia un
    doble wrapper pisando el mundo."""
    pytest.importorskip("httpx")
    import concurrent.futures as cf
    from fastapi.testclient import TestClient

    _reset_manager_state()
    spawned = {"n": 0}
    proc, _fake_stdin = _fake_wrapper_proc()

    def fake_spawn():
        spawned["n"] += 1
        time.sleep(0.05)  # ensanchar la ventana de carrera
        return proc

    monkeypatch.setattr(supervisor, "_spawn_wrapper_process", fake_spawn)
    monkeypatch.setattr(supervisor, "run_wrapper_thread", lambda *a, **k: None)

    try:
        with TestClient(gui.app, client=("127.0.0.1", 50000)) as c:
            with cf.ThreadPoolExecutor(max_workers=2) as ex:
                futs = [ex.submit(c.post, "/api/action/restart") for _ in range(2)]
                results = [f.result().json() for f in futs]
            time.sleep(0.5)  # deja terminar a los hilos do_restart
        assert all(r["status"] == "restarting" for r in results), results
        assert spawned["n"] == 1, f"se lanzaron {spawned['n']} wrappers"
    finally:
        _reset_manager_state()


def test_stop_normal_tiene_tope_y_fuerza_terminacion():
    """H1: la ruta normal de 'stop' esta acotada en el wrapper: si BDS no
    cierra en BDS_STOP_TIMEOUT_SEC, el wrapper lo fuerza ANTES del backup
    final (antes solo la ruta Ctrl+C forzaba; la normal colgaba para
    siempre, dejando el mundo bloqueado)."""
    src = open(os.path.join(BASE_DIR, "server_wrapper.py"), encoding="utf-8").read()
    assert "BDS_STOP_TIMEOUT_SEC" in src
    assert "shutdown_requested_at" in src
    assert "forcing termination" in src
    assert "forcing termination" in src.split("finally:")[-1], (
        "el kill forzado debe ocurrir en el finally, antes del backup final"
    )


# ═══════════════════════════════════════════════════════════════════════
# H3: backup_in_progress no debe quedar atascado tras un backup fallido
# ═══════════════════════════════════════════════════════════════════════
def test_wrapper_marca_fin_de_ciclo_en_finally():
    """CORREGIDO (H3): execute_backup_worker imprime '[Worker] Backup
    finalizado' en un finally, asi TODOS los caminos (exito, fallo, timeout,
    watchdog y excepcion) emiten el marcador, incluidos los `return`
    tempranos del watchdog y del timeout."""
    src = open(os.path.join(BASE_DIR, "wrapper_backup.py"), encoding="utf-8").read()
    worker = src.split("def execute_backup_worker")[1].split("\ndef _begin_manual_hot_backup")[0]
    assert "finally:" in worker
    assert '"[Worker] Backup finalizado"' in worker
    assert '"[Worker] Backup finished"' in worker
    assert "print(L(" in worker
    # el finally va despues del except: cubre tambien los returns tempranos
    assert worker.index("finally:") > worker.index("except Exception as e:")


def test_gui_resetea_flag_con_backup_finalizado():
    """CORREGIDO (H3): la GUI resetea backup_in_progress con el marcador de
    fin del wrapper (ademas de las cadenas de exito existentes), para que el
    boton de backup en frio no quede bloqueado tras un backup fallido."""
    gui_src = open(os.path.join(BASE_DIR, "gui_backend", "supervisor.py"), encoding="utf-8").read()
    gui_thread = gui_src.split("def run_wrapper_thread")[1]
    assert '"Backup finished" in line_str' in gui_thread
    assert "backup_in_progress = False" in gui_thread


def test_lines_waited_for_list_se_reinicia_tras_parseo_exitoso():
    """CORREGIDO (H3): lines_waited_for_list se reinicia cuando una lista de
    jugadores se parsea con exito (antes quedaba con el valor viejo; sin
    efecto practico porque la rama exige expecting_list_names, pero dejaba el
    contador inconsistente)."""
    src = open(os.path.join(BASE_DIR, "server_wrapper.py"), encoding="utf-8").read()
    read_stdout_src = src.split("def read_stdout")[1].split("def backup_scheduler")[0]
    # resets: lista vacia (original) + parseo de nombres + continuacion parseada
    assert read_stdout_src.count("lines_waited_for_list = 0") >= 3


# ═══════════════════════════════════════════════════════════════════════
# Ronda de revision 2026-08-12: CASO A (timeout de compresion) muerto por
# el shim de join, y races de la GUI (players_online y stdin sin lock)
# ═══════════════════════════════════════════════════════════════════════
def test_worker_timeout_compresion_mata_proceso_y_libera_estado(monkeypatch, tmp_path):
    """CORREGIDO (R2-HIGH): si la compresion excede WORKER_COMPRESSION_TIMEOUT_SEC,
    el worker llega al CASO A y MATA el proceso (kill + limpieza de .tmp +
    lock IPC nuevo). Antes el shim comp_proc.join = wait(timeout) lanzaba
    subprocess.TimeoutExpired (Popen.wait LANZA al vencer; Process.join
    devuelve None): la excepcion caia en el except generico, que reseteaba
    estado y dejaba active_compress_process=None SIN matar al huerfano. El
    huerfano retenia el lock de backups y todos los backups dejaban de
    funcionar hasta que terminara solo (o para siempre, si colgaba)."""
    import server_wrapper as sw

    fake_bkp = os.path.join(str(tmp_path), "backups")
    os.makedirs(fake_bkp)
    orphan_tmp = os.path.join(fake_bkp, "auto_backup_x.zip.tmp")
    _write(orphan_tmp, b"parcial")
    monkeypatch.setattr(sw.auto_backup, "BACKUP_DIR", fake_bkp)

    killed = {"n": 0}

    class FakeCompProc:
        def poll(self):
            return None  # sigue vivo: compresion lenta

        def wait(self, timeout=None):
            if timeout is not None:
                raise subprocess.TimeoutExpired(cmd="backup_worker.py", timeout=timeout)
            return 0

        def kill(self):
            killed["n"] += 1

    fake = FakeCompProc()
    monkeypatch.setattr(wrapper_backup.subprocess, "Popen", lambda *a, **k: fake)

    # estado de un ciclo caliente en plena compresion
    with wstate.state_lock:
        prev = (wstate.backup_in_progress, wstate.backup_dispatched, wstate.watchdog_fired,
                wstate.save_query_ready_seen, wstate.backup_cancel_event,
                wstate.snapshot_retry_count, wstate.snapshot_retry_at)
        wstate.backup_in_progress = True
        wstate.backup_dispatched = True
        wstate.watchdog_fired = False
        wstate.save_query_ready_seen = True
        wstate.backup_cancel_event = None
        wstate.snapshot_retry_count = 0
        wstate.snapshot_retry_at = 0.0
    try:
        sw.execute_backup_worker(file_snapshot=[("level.dat", 10)], cancel_event=None)
        assert killed["n"] == 1, "CASO A no mato el proceso de compresion"
        with wstate.state_lock:
            assert wstate.backup_in_progress is False
            assert wstate.backup_dispatched is False
            assert wstate.save_query_ready_seen is False
            assert wstate.watchdog_fired is True
            assert wstate.active_compress_process is None
            assert wstate.last_backup_completed_time != 0
        assert not os.path.exists(orphan_tmp), (
            "el .tmp huerfano debio limpiarse tras el kill"
        )
    finally:
        with wstate.state_lock:
            (wstate.backup_in_progress, wstate.backup_dispatched, wstate.watchdog_fired,
             wstate.save_query_ready_seen, wstate.backup_cancel_event,
             wstate.snapshot_retry_count, wstate.snapshot_retry_at) = prev


def test_gui_players_online_bajo_manager_lock():
    """CORREGIDO (R2-LOW): las mutaciones y lecturas de players_online de la
    GUI van bajo manager.lock. Antes el hilo del wrapper hacia
    add/discard/clear sin lock mientras el event loop iteraba
    list(players_online) (/api/status, update_status, init del WS): iterar un
    set mientras otro hilo lo muta puede lanzar RuntimeError 'set changed
    size during iteration' (500s intermitentes o desconexion del WS)."""
    # Refactor: las mutaciones viven en gui_backend/supervisor.py
    # (run_wrapper_thread), unico sitio que toca players_online.
    src = open(os.path.join(BASE_DIR, "gui_backend", "supervisor.py"), encoding="utf-8").read()
    for needle in (
        "manager.players_online.add(name)",
        "manager.players_online.discard(name)",
        "manager.players_online.clear()",
    ):
        i = src.index(needle)
        assert "with manager.lock:" in src[i - 300:i], (
            "mutacion sin manager.lock cerca de %r" % needle
        )
    # Refactor: la lectura bajo lock de /api/status, update_status y el init
    # del WS ahora vive en gui_backend/state.py (build_public_status).
    state_src = open(os.path.join(BASE_DIR, "gui_backend", "state.py"), encoding="utf-8").read()
    i = state_src.index("players = list(manager.players_online)")
    assert "with manager.lock:" in state_src[i - 300:i], (
        "build_public_status debe leer players_online bajo manager.lock"
    )


def test_gui_stdin_bajo_stdin_lock():
    """CORREGIDO (R2-LOW): todas las escrituras a wrapper_process.stdin (API,
    WS y acciones) van bajo manager.stdin_lock. TextIOWrapper no es
    thread-safe: un comando del chat + un stop simultaneos podian
    entremezclarse en el pipe y mandar una linea corrupta al servidor.

    Refactor: las escrituras ahora viven repartidas entre server_gui_server.py
    y gui_backend/ (routers); la invariante se comprueba sobre TODOS los
    archivos del backend (el total debe seguir siendo 6 writes == 6 locks).
    """
    # Refactor: el lock vive en gui_backend/state.py (ServerManager).
    state_src = open(os.path.join(BASE_DIR, "gui_backend", "state.py"), encoding="utf-8").read()
    assert "self.stdin_lock = threading.Lock()" in state_src

    backend_files = [os.path.join(BASE_DIR, "server_gui_server.py")]
    backend_root = os.path.join(BASE_DIR, "gui_backend")
    for root, _dirs, names in os.walk(backend_root):
        for n in names:
            if n.endswith(".py"):
                backend_files.append(os.path.join(root, n))

    src = "\n".join(open(p, encoding="utf-8").read() for p in backend_files)
    writes = src.count("manager.wrapper_process.stdin.write")
    locks = src.count("with manager.stdin_lock:")
    assert writes == 6, "numero inesperado de sitios de escritura: %d" % writes
    assert locks == writes, (
        "hay %d escrituras a stdin pero %d bloques con manager.stdin_lock" % (writes, locks)
    )


def test_estado_del_wrapper_no_se_rebindea_fuera_de_wrapper_state():
    """Los escalares compartidos deben escribirse siempre como wstate.X."""
    state_names = (
        "players_online", "backup_in_progress", "backup_dispatched",
        "watchdog_fired", "shutting_down", "shutdown_requested_at",
        "last_backup_completed_time", "save_hold_timestamp", "backup_thread",
        "active_compress_process", "last_save_snapshot", "save_query_ready_seen",
        "backup_cancel_event", "expecting_list_names", "last_snapshot_update_time",
        "snapshot_retry_count", "snapshot_retry_at", "server_process",
    )
    paths = [os.path.join(BASE_DIR, "server_wrapper.py")]
    wrapper_backup = os.path.join(BASE_DIR, "wrapper_backup.py")
    if os.path.exists(wrapper_backup):
        paths.append(wrapper_backup)
    for path in paths:
        source = open(path, encoding="utf-8").read()
        for name in state_names:
            assert not re.search(r"(?m)^\s*%s\s*(?:\+|-)?=" % re.escape(name), source), (
                "%s se rebindea fuera de wrapper_state en %s" % (name, path)
            )
