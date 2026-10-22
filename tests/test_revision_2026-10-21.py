# -*- coding: utf-8 -*-
"""Regresiones de la revision del 2026-10-21 (docs/INFORME_FIXES_2026-10-21.md).

M1  Rutas con corchetes: glob.escape en listados, rotacion y limpiezas.
M2  La configuracion editada de BDS sobrevive a actualizar y a revertir.
M3  Backup en frio rechazado con un servidor externo vivo.
M4  El wrapper y el worker sobreviven a la muerte de la GUI (tuberia rota).
M5  El trabajo anterior del actualizador se archiva con gui.log abierto.
M6  Un diario terminado no bloquea los lanzadores (instalacion movida).
M7  Dos instalaciones con el mismo nombre no comparten carpeta de backups.
M8  Verificar backups: deflate danado = corrupto; ilegible != corrupto.
M10 backups_revision: la GUI vuelve a pedir la lista cuando cambia.
L1  Fechas anteriores a 1980 no abortan los backups.
L2  Una carpeta ilegible aborta el backup (no publica uno incompleto).
L3  Junction en los static_includes del backup en caliente.
L4  NamedMutex falla cerrado si no puede abrir el mutex.
L5  El auxiliar de actualizacion no usa el proxy para 127.0.0.1.
L6  Reanudar Minecraft tras actualizar la suite.
L7  uvicorn recibe el socket ya enlazado.
L8  Sesiones de jugadores cerradas al terminar el wrapper.
L9  Cuerpos JSON validos que no son un objeto: 400, no 500.
L10 Restaurar no cambia el "ultimo backup".
L14 La poda de respaldos de enable_beta_apis_v2 no borra el recien creado.
L16-L20 Lanzadores .bat/.ps1.
L21 Diagnostico de referencia de tipo cruzado con filtro por tipo.

M9, L11, L12 y L13 son del frontend: gui_frontend/tests/ (bds-update,
players-command, setup-wizard). L15 vive en tests/test_update_items_v2.py.
Todo corre sobre instalaciones en tmp_path: nunca la real.
"""
import hashlib
import http.server
import importlib.util
import inspect
import io
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import types
import urllib.request
import zipfile
import zlib
from pathlib import Path

import pytest

import addon_inventory
import auto_backup
import console_lang
import restore_backup
import server_gui_server as gui
import suite_release
import suite_updater
import windows_process_guard as wpg
import wrapper_state
import zip_safety
from gui_backend import backup_location as bl
from gui_backend import supervisor
from gui_backend.services import backups as backups_service
from gui_backend.services import bds_update, external_probe, history, lifecycle, schedule_config, suite_update
from gui_backend.state import build_public_status, manager

ROOT = Path(__file__).resolve().parents[1]
URL_BDS = "https://www.minecraft.net/bedrockdedicatedserver/bin-win/bedrock-server-1.2.3.4.zip"
PAUSA = ("Presione una tecla", "Press any key")


def _arbol(base, archivos):
    for rel, data in archivos.items():
        path = Path(base) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def _cargar_tool(nombre):
    spec = importlib.util.spec_from_file_location(f"_tool_{nombre}", ROOT / "tools" / f"{nombre}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _junction(enlace, destino):
    import _winapi
    _winapi.CreateJunction(str(destino), str(enlace))


def _zip_minimo(path, entradas=None):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for nombre, data in (entradas or {"level.dat": b"L"}).items():
            zf.writestr(nombre, data)


@pytest.fixture
def mundo_aislado(tmp_path, monkeypatch):
    """create_backup sobre una instalacion en tmp con carpeta de backups fija."""
    base = tmp_path / "inst" / "Srv"
    mundo = base / "worlds" / "W"
    _arbol(mundo, {"level.dat": b"LEVEL" * 10})
    bk = tmp_path / "bk"
    monkeypatch.setattr(auto_backup, "BASE_DIR", str(base))
    monkeypatch.setattr(auto_backup, "WORLD_DIR", str(mundo))
    monkeypatch.setattr(auto_backup, "WORLD_PARENT_DIR", str(base / "worlds"))
    monkeypatch.setattr(auto_backup, "BACKUP_DIR", str(bk))
    return base, mundo, bk


@pytest.fixture
def api(tmp_path, monkeypatch):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    base = tmp_path / "inst" / "Srv"
    _arbol(base, {"worlds/W/level.dat": b"L", "server.properties": b"level-name=W\n"})
    monkeypatch.setattr(auto_backup, "BASE_DIR", str(base))
    for attr, valor in (("is_running", False), ("wrapper_process", None), ("backup_in_progress", False),
                        ("update_in_progress", False), ("suite_update_in_progress", False)):
        monkeypatch.setattr(manager, attr, valor)
    client = TestClient(gui.app, client=("127.0.0.1", 50000), raise_server_exceptions=False)
    return client, base


# ═══════════════════════════════════════════════════════════════════════
# M1. Corchetes en la ruta: glob los leia como una clase de caracteres
# ═══════════════════════════════════════════════════════════════════════
CORCHETES = "Respaldos [HDD]"


def _backups_con_fechas(carpeta, ahora, n=30):
    for i in range(n):
        p = carpeta / f"auto_backup_Srv_auto_{i:03d}_{i:08x}.zip"
        _zip_minimo(p)
        t = ahora - i * 6 * 3600  # uno cada 6 h: entran la capa reciente y la diaria
        os.utime(p, (t, t))


def test_m1_rotacion_con_corchetes_igual_que_sin_ellos(tmp_path, monkeypatch):
    import datetime
    ahora = time.time()
    plana, rara = tmp_path / "plana" / "Srv", tmp_path / CORCHETES / "Srv"
    _backups_con_fechas(plana, ahora)
    _backups_con_fechas(rara, ahora)
    for carpeta in (plana, rara):
        monkeypatch.setattr(auto_backup, "get_backup_dir", lambda base_dir=None, c=carpeta: str(c))
        auto_backup.rotate_backups(now=datetime.datetime.fromtimestamp(ahora))

    quedan = sorted(os.listdir(rara))
    assert quedan == sorted(os.listdir(plana))
    assert len(quedan) < 30  # la rotacion borro de verdad (antes: 0 encontrados)


def test_m1_listados_gui_y_cli_con_corchetes(tmp_path):
    carpeta = tmp_path / CORCHETES / "Srv"
    for i in range(3):
        _zip_minimo(carpeta / f"auto_backup_Srv_x_{i}.zip")
    _zip_minimo(carpeta / "auto_backup_Srv_roto_CORRUPTO.zip")
    esperados = sorted(str(carpeta / f"auto_backup_Srv_x_{i}.zip") for i in range(3))

    assert sorted(backups_service._list_backup_files(str(carpeta))) == esperados
    assert sorted(restore_backup._list_backup_files(str(carpeta))) == esperados


def test_m1_backup_limpia_tmp_huerfanos_con_corchetes(mundo_aislado, tmp_path, monkeypatch):
    carpeta = tmp_path / CORCHETES / "Srv"
    carpeta.mkdir(parents=True)
    huerfano = carpeta / "auto_backup_Srv_auto_viejo.zip.tmp"
    huerfano.write_bytes(b"a medias")
    monkeypatch.setattr(auto_backup, "BACKUP_DIR", str(carpeta))

    zip_path = auto_backup.create_backup("manual")

    assert zip_path and os.path.dirname(zip_path) == str(carpeta)
    assert not huerfano.exists()


def test_m1_recuperacion_bds_en_instalacion_con_corchetes(tmp_path):
    base = tmp_path / "Servidor [Survival]"
    _arbol(base, {"bedrock_server.exe": b"NUEVO"})
    prev = base / "bds_update_prev_0123abcd"
    _arbol(prev, {"bedrock_server.exe": b"VIEJO"})
    (prev / bds_update._UPDATE_MANIFEST_NAME).write_text(json.dumps(
        {"entries": [{"path": "bedrock_server.exe", "had_previous": True}], "staging": None}), encoding="utf-8")

    bds_update.recover_interrupted_updates(str(base))

    assert (base / "bedrock_server.exe").read_bytes() == b"VIEJO"
    assert not prev.exists()


_RE_GLOB = re.compile(r"\b_?glob\.i?glob\(")


def test_m1_todo_glob_de_produccion_escapa_la_carpeta():
    """Anti-drift: cada glob.glob de produccion escapa la parte de la ruta."""
    llamadas, sin_escape = 0, []
    for path in [*ROOT.glob("*.py"), *ROOT.glob("gui_backend/**/*.py"), *ROOT.glob("tools/*.py")]:
        lineas = path.read_text(encoding="utf-8").splitlines()
        for i, linea in enumerate(lineas):
            if linea.lstrip().startswith("#") or not _RE_GLOB.search(linea):
                continue
            llamadas += 1
            if "escape(" not in "\n".join(lineas[max(0, i - 3):i + 1]):
                sin_escape.append(f"{path.relative_to(ROOT)}:{i + 1}")
    assert llamadas >= 6
    assert sin_escape == []


# ═══════════════════════════════════════════════════════════════════════
# M2. Configuracion de BDS editada por el admin (conffiles)
# ═══════════════════════════════════════════════════════════════════════
CONF = ("config/default/permissions.json", "packetlimitconfig.json", "profanity_filter.wlist")


def _fabrica(rel, version):
    return f"{rel} de fabrica {version}".encode()


def _zip_bds(version):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("bedrock_server.exe", f"exe {version}".encode())
        for rel in CONF:
            zf.writestr(rel, _fabrica(rel, version))
    return buf.getvalue()


class _RespZip:
    def __init__(self, contenido):
        self.status_code = 200
        self.headers = {"Content-Length": str(len(contenido))}
        self._contenido = contenido

    def iter_content(self, chunk_size=8192):
        for i in range(0, len(self._contenido), chunk_size):
            yield self._contenido[i:i + chunk_size]


def _servir_bds(monkeypatch, version):
    monkeypatch.setattr(bds_update.requests, "get", lambda *a, **k: _RespZip(_zip_bds(version)))


def _instalacion_bds(monkeypatch, tmp_path):
    """BDS v1 instalado de una vez (misma fecha que el exe) con packetlimit editado."""
    base = tmp_path / "inst"
    _arbol(base, {"bedrock_server.exe": b"exe v1", **{rel: _fabrica(rel, "v1") for rel in CONF}})
    (base / "packetlimitconfig.json").write_bytes(b"LIMITES DEL ADMIN")
    t_exe = os.path.getmtime(base / "bedrock_server.exe")
    for rel in CONF:
        os.utime(base / rel, (t_exe + 5, t_exe + 5))
    editado = t_exe + 2 * 86400  # editado dias despues de instalar
    os.utime(base / "packetlimitconfig.json", (editado, editado))
    monkeypatch.setattr(bds_update.config, "BASE_DIR", str(base))
    monkeypatch.setattr(bds_update, "PREVIOUS_VERSION_DIR", str(base / "data" / "bds_previous"))
    monkeypatch.setattr(bds_update, "_fetch_latest_bedrock_download", lambda: (URL_BDS, "1.2.3.4"))
    monkeypatch.setattr(manager, "installed_version", None)
    return base


def _actualizar(logs):
    ok, _version = bds_update._download_and_install_bds(log_fn=lambda m, t=None: logs.append(m))
    assert ok is True, logs


def test_m2_actualizar_conserva_lo_editado_sin_registro_previo(monkeypatch, tmp_path):
    base = _instalacion_bds(monkeypatch, tmp_path)
    _servir_bds(monkeypatch, "v2")
    logs = []

    _actualizar(logs)

    assert (base / "bedrock_server.exe").read_bytes() == b"exe v2"
    # Sin registro decide la fecha: lo editado se conserva, lo de fabrica se actualiza.
    assert (base / "packetlimitconfig.json").read_bytes() == b"LIMITES DEL ADMIN"
    defaults = base / "data" / "bds_config_defaults"
    assert (defaults / "packetlimitconfig.json").read_bytes() == _fabrica("packetlimitconfig.json", "v2")
    for rel in ("config/default/permissions.json", "profanity_filter.wlist"):
        assert (base / rel).read_bytes() == _fabrica(rel, "v2")
        assert not (defaults / rel).exists()
    assert bds_update.read_shipped_config(str(base)) == {
        rel: hashlib.sha256(_fabrica(rel, "v2")).hexdigest() for rel in CONF}
    assert any("packetlimitconfig.json" in m and "bds_config_defaults" in m for m in logs), logs


def test_m2_con_registro_decide_la_huella_y_revertir_respeta_lo_editado(monkeypatch, tmp_path):
    base = _instalacion_bds(monkeypatch, tmp_path)
    _servir_bds(monkeypatch, "v2")
    _actualizar([])
    # Segunda actualizacion: la fecha ya no cuenta. packetlimit editado con la
    # misma fecha que el exe se conserva; profanity de fabrica con una fecha
    # lejana se actualiza.
    t_exe = os.path.getmtime(base / "bedrock_server.exe")
    os.utime(base / "packetlimitconfig.json", (t_exe, t_exe))
    lejos = t_exe - 30 * 86400
    os.utime(base / "profanity_filter.wlist", (lejos, lejos))
    _servir_bds(monkeypatch, "v3")
    _actualizar([])

    assert (base / "packetlimitconfig.json").read_bytes() == b"LIMITES DEL ADMIN"
    assert (base / "data/bds_config_defaults/packetlimitconfig.json").read_bytes() == \
        _fabrica("packetlimitconfig.json", "v3")
    assert (base / "profanity_filter.wlist").read_bytes() == _fabrica("profanity_filter.wlist", "v3")
    assert (base / "config/default/permissions.json").read_bytes() == \
        _fabrica("config/default/permissions.json", "v3")

    # El admin edita el filtro tras actualizar y luego revierte a v2.
    (base / "profanity_filter.wlist").write_bytes(b"PALABRAS DEL ADMIN")
    logs = []
    ok, _version = bds_update.rollback_bds(log_fn=lambda m, t=None: logs.append(m))

    assert ok is True, logs
    assert (base / "bedrock_server.exe").read_bytes() == b"exe v2"
    assert (base / "profanity_filter.wlist").read_bytes() == b"PALABRAS DEL ADMIN"
    assert (base / "config/default/permissions.json").read_bytes() == \
        _fabrica("config/default/permissions.json", "v2")
    assert (base / "packetlimitconfig.json").read_bytes() == b"LIMITES DEL ADMIN"
    # La huella de fabrica de la version restaurada no se conoce: se olvida.
    assert not os.path.exists(bds_update.shipped_config_path(str(base)))
    assert any("profanity_filter.wlist" in m for m in logs), logs


# ═══════════════════════════════════════════════════════════════════════
# M3. Backup en frio con un servidor externo vivo
# ═══════════════════════════════════════════════════════════════════════
def test_m3_endpoint_rechaza_el_backup_en_frio_con_servidor_externo(api, monkeypatch):
    client, _base = api
    monkeypatch.setattr(external_probe, "detect_external_bds", lambda base_dir=None: (True, "bds_process"))
    llamadas = []
    monkeypatch.setattr(auto_backup, "create_backup", lambda *a, **k: llamadas.append(a))

    r = client.post("/api/action/backup")

    assert r.status_code == 409, r.text
    assert "externa" in r.json()["detail"]
    assert llamadas == []


def test_m3_backup_en_frio_rechequea_bajo_op_lock(monkeypatch):
    # El watchdog diario llama directo a cold_backup, sin pasar por el endpoint.
    monkeypatch.setattr(manager, "is_running", False)
    monkeypatch.setattr(manager, "backup_in_progress", False)
    monkeypatch.setattr(external_probe, "detect_external_bds", lambda base_dir=None: (True, "wrapper_mutex"))
    llamadas, logs = [], []
    monkeypatch.setattr(auto_backup, "create_backup", lambda *a, **k: llamadas.append(a))
    monkeypatch.setattr(manager, "add_log", lambda text, log_type="info": logs.append((log_type, text)))

    lifecycle.cold_backup("watchdog_daily")

    assert llamadas == []
    assert manager.backup_in_progress is False
    assert any(t == "error" and ("externa" in m or "external" in m) for t, m in logs), logs


# ═══════════════════════════════════════════════════════════════════════
# M4. Tuberia hacia la GUI rota: el proceso sigue trabajando
# ═══════════════════════════════════════════════════════════════════════
class _Tuberia:
    def __init__(self, encoding="utf-8"):
        self.encoding = encoding
        self.error = None
        self.escrito = []

    def write(self, text):
        if self.error:
            raise self.error
        text.encode(self.encoding)  # UnicodeEncodeError como una consola cp1252
        self.escrito.append(text)
        return len(text)

    def flush(self):
        if self.error:
            raise self.error


def test_m4_salida_tolerante_descarta_tras_romperse_la_tuberia():
    tuberia = _Tuberia()
    salida = console_lang._SalidaTolerante(tuberia)
    assert salida.write("hola\n") == 5
    tuberia.error = OSError(22, "Invalid argument")  # lo que da Windows sin lector
    assert salida.write("adios\n") == 6
    salida.flush()
    tuberia.error = None
    salida.write("otra\n")  # una tuberia rota no vuelve: ni se reintenta
    assert tuberia.escrito == ["hola\n"]
    assert salida.encoding == "utf-8"  # el resto se delega


def test_m4_salida_tolerante_reemplaza_lo_que_la_consola_no_codifica():
    tuberia = _Tuberia(encoding="cp1252")
    salida = console_lang._SalidaTolerante(tuberia)
    salida.write("\u24c2 ok\n")
    assert tuberia.escrito == ["? ok\n"]


def test_m4_proteger_salida_es_idempotente(monkeypatch):
    out, err = _Tuberia(), _Tuberia()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    console_lang.proteger_salida_consola()
    console_lang.proteger_salida_consola()
    assert isinstance(sys.stdout, console_lang._SalidaTolerante) and sys.stdout._stream is out
    assert isinstance(sys.stderr, console_lang._SalidaTolerante) and sys.stderr._stream is err


_HIJO_CON_LECTOR_MUERTO = r'''
import json, sys, time
sys.path.insert(0, sys.argv[1])
import console_lang
if sys.argv[3] == "protegido":
    console_lang.proteger_salida_consola()
print("listo", flush=True)
time.sleep(0.5)  # el padre cierra su extremo: la GUI murio
for i in range(200):
    print(f"[Wrapper] linea {i}", flush=True)
    time.sleep(0.005)
with open(sys.argv[2], "w", encoding="utf-8") as f:
    json.dump({"lineas": 200}, f)
'''


@pytest.mark.parametrize("modo", ["protegido", "sin_proteger"])
def test_m4_proceso_sigue_tras_morir_su_lector(tmp_path, modo):
    script = tmp_path / "hijo.py"
    script.write_text(_HIJO_CON_LECTOR_MUERTO, encoding="utf-8")
    resultado = tmp_path / "resultado.json"
    # Igual que supervisor._spawn_wrapper_process: -u y stdout+stderr a una tuberia.
    with subprocess.Popen([sys.executable, "-u", str(script), str(ROOT), str(resultado), modo],
                          stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          env=dict(os.environ, PYTHONIOENCODING="utf-8")) as proc:
        try:
            assert proc.stdout.readline().strip() == b"listo"
            proc.stdout.close()
            proc.wait(timeout=60)
        finally:
            if proc.poll() is None:
                proc.kill()
    if modo == "protegido":
        assert proc.returncode == 0
        assert json.loads(resultado.read_text(encoding="utf-8")) == {"lineas": 200}
    else:
        # Control: sin la proteccion, el primer print sin lector mata el proceso.
        assert proc.returncode != 0
        assert not resultado.exists()


def _primera_sentencia(cuerpo):
    return next(l.strip() for l in cuerpo.splitlines() if l.strip() and not l.strip().startswith("#"))


def test_m4_wrapper_y_worker_protegen_su_salida_lo_primero():
    wrapper = (ROOT / "server_wrapper.py").read_text(encoding="utf-8")
    assert _primera_sentencia(wrapper.split('if __name__ == "__main__":', 1)[1]) == "proteger_salida_consola()"
    worker = (ROOT / "backup_worker.py").read_text(encoding="utf-8")
    assert _primera_sentencia(worker.split("def _main():", 1)[1]) == "proteger_salida_consola()"


# ═══════════════════════════════════════════════════════════════════════
# M5. Archivar recovery/ con gui.log abierto por la GUI anterior
# ═══════════════════════════════════════════════════════════════════════
def test_m5_archivar_recovery_con_gui_log_abierto_por_otro_proceso(tmp_path):
    area = tmp_path / "suite_updates"
    recovery = area / "recovery"
    _arbol(recovery, {"journal.json": b"{}", "progress.json": b"{}", "helper/suite_updater.py": b"#"})
    with open(recovery / "gui.log", "ab") as log:
        log.write(b"GUI vieja\n")
        log.flush()
        # Una GUI relanzada por un auxiliar <= 2.2.0 hereda gui.log como stdout.
        gui_vieja = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
    try:
        with pytest.raises(OSError):
            os.replace(recovery, area / "previous_rename")  # lo que hacia shutil.move
        historial = area / "previous_x"

        suite_update._archive_job(recovery, historial)

        assert sorted(p.name for p in historial.iterdir()) == ["gui.log", "helper", "journal.json", "progress.json"]
        assert (historial / "helper" / "suite_updater.py").exists()
        assert (historial / "gui.log").read_bytes() == b"GUI vieja\n"
        # Solo queda el log abierto y el trabajo nuevo se crea encima.
        assert [p.name for p in recovery.iterdir()] == ["gui.log"]
        recovery.mkdir(parents=True, exist_ok=True)
    finally:
        gui_vieja.kill()
        gui_vieja.wait()


def test_m5_el_trabajo_nuevo_se_crea_tras_archivar():
    src = inspect.getsource(suite_update._update_worker)
    assert "_archive_job(candidate, history)" in src
    assert "shutil.move" not in src
    assert "job.mkdir(parents=True, exist_ok=True)" in src


def test_m5_el_auxiliar_lanza_la_gui_con_el_log_fuera_de_recovery(tmp_path, monkeypatch):
    lanzados = []

    def popen(args, **kwargs):
        lanzados.append((args, kwargs["stdout"].name))
        return "proceso"

    monkeypatch.setattr(suite_updater.subprocess, "Popen", popen)
    log = tmp_path / suite_updater.GUI_LOG
    log.parent.mkdir(parents=True)
    log.write_bytes(b"x" * (suite_updater.GUI_LOG_MAX_BYTES + 1))

    assert suite_updater.launch_gui(tmp_path, {"old_python": sys.executable, "port": 8000}, "tok") == "proceso"

    assert "recovery" not in Path(suite_updater.GUI_LOG).parts
    assert os.path.normcase(lanzados[0][1]) == os.path.normcase(str(log))
    # Pasado el tope se rota: el log nuevo empieza vacio.
    assert log.stat().st_size == 0
    assert (tmp_path / (suite_updater.GUI_LOG + ".1")).stat().st_size == suite_updater.GUI_LOG_MAX_BYTES + 1


# ═══════════════════════════════════════════════════════════════════════
# M6. Diario terminado de una instalacion movida o copiada
# ═══════════════════════════════════════════════════════════════════════
def _diario(root, fase, objetivo):
    job = Path(root) / "data" / "suite_updates" / "recovery"
    job.mkdir(parents=True, exist_ok=True)
    suite_release.write_json(job / "journal.json", {
        "phase": fase, "target": str(objetivo), "stage": str(Path(objetivo) / "data/suite_updates/recovery/stage")})
    return job


@pytest.mark.parametrize("fase", ["complete", "rolled_back"])
def test_m6_recover_con_diario_terminado_de_otra_ruta(tmp_path, fase):
    movida = tmp_path / "movida"
    _diario(movida, fase, tmp_path / "ubicacion_original")
    assert suite_updater.recover(movida) == 0


def test_m6_recover_sigue_validando_un_diario_pendiente(tmp_path):
    movida = tmp_path / "movida"
    _diario(movida, "applying", tmp_path / "ubicacion_original")
    with pytest.raises(ValueError, match="no corresponde"):
        suite_updater.recover(movida)


def _python_base():
    return Path(os.path.realpath(getattr(sys, "_base_executable", sys.executable))).parent


def _cmd(bat, *args, cwd):
    """Ejecuta un .bat como doble clic: consola propia (oculta) y una tecla para pause."""
    r = subprocess.run(["cmd", "/d", "/c", str(bat), *args], cwd=cwd, input=b"x\r\n",
                       capture_output=True, timeout=120,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.returncode, (r.stdout + r.stderr).decode("utf-8", errors="replace")


def _pausas(salida):
    return sum(salida.count(p) for p in PAUSA)


@pytest.fixture
def instalacion_bat(tmp_path):
    inst = tmp_path / "inst"
    inst.mkdir()
    for nombre in ("Recuperar_suite.bat", "iniciar_gui.bat", "iniciar_servidor.bat"):
        shutil.copy2(ROOT / nombre, inst / nombre)
    enlaces = []
    yield inst, enlaces
    for enlace in enlaces:
        os.rmdir(enlace)  # quita solo la junction, nunca el Python enlazado


def _auxiliar(inst, enlaces, script):
    helper = inst / "data" / "suite_updates" / "recovery" / "helper"
    helper.mkdir(parents=True)
    _junction(helper / "runtime", _python_base())
    enlaces.append(helper / "runtime")
    (helper / "suite_updater.py").write_text(script, encoding="utf-8")


def test_m6_recuperar_suite_no_ejecuta_el_auxiliar_con_diario_terminado(instalacion_bat):
    inst, enlaces = instalacion_bat
    _diario(inst, "complete", Path(r"C:\otra\ubicacion"))
    # El auxiliar de 2.2.0 fallaba con el diario de una instalacion movida.
    _auxiliar(inst, enlaces, "import sys; print('AUXILIAR EJECUTADO'); sys.exit(1)")

    codigo, salida = _cmd(inst / "Recuperar_suite.bat", cwd=inst)

    assert codigo == 0, salida
    assert "AUXILIAR EJECUTADO" not in salida


def test_m6_recuperacion_fallida_se_ve_y_pausa_una_sola_vez(instalacion_bat):
    inst, enlaces = instalacion_bat
    _diario(inst, "applying", Path(r"C:\otra\ubicacion"))
    _auxiliar(inst, enlaces, "import sys; print('[ERROR] El diario no corresponde'); sys.exit(1)")

    desde_lanzador = _cmd(inst / "Recuperar_suite.bat", "--sin-pausa", cwd=inst)
    doble_clic = _cmd(inst / "Recuperar_suite.bat", cwd=inst)
    gui = _cmd(inst / "iniciar_gui.bat", cwd=inst)
    servidor = _cmd(inst / "iniciar_servidor.bat", cwd=inst)

    assert desde_lanzador[0] == 1 and _pausas(desde_lanzador[1]) == 0, desde_lanzador
    assert "No se pudo recuperar" in desde_lanzador[1]
    assert doble_clic[0] == 1 and _pausas(doble_clic[1]) == 1, doble_clic
    for codigo, salida in (gui, servidor):
        # El mensaje del auxiliar queda a la vista con una sola pausa, la del lanzador.
        assert codigo == 1 and _pausas(salida) == 1, salida
        assert "El diario no corresponde" in salida
        assert "recuperacion de una actualizacion de la suite" in salida


# ═══════════════════════════════════════════════════════════════════════
# M7. Carpeta de backups con dueno
# ═══════════════════════════════════════════════════════════════════════
def _inst(tmp_path, *partes):
    base = tmp_path.joinpath(*partes)
    _arbol(base, {"worlds/W/level.dat": b"LEVEL", "server.properties": b"level-name=W\n"})
    return str(base)


def _backup_en(base, monkeypatch):
    """create_backup real; la carpeta la resuelve backup_location (sin parche)."""
    monkeypatch.setattr(auto_backup, "BASE_DIR", base)
    monkeypatch.setattr(auto_backup, "WORLD_DIR", os.path.join(base, "worlds", "W"))
    monkeypatch.setattr(auto_backup, "WORLD_PARENT_DIR", os.path.join(base, "worlds"))
    zip_path = auto_backup.create_backup("manual")
    assert zip_path
    return zip_path


def _dueno(carpeta):
    return json.loads(Path(carpeta, bl.OWNER_FILE).read_text(encoding="utf-8"))


def _id(base):
    return json.loads(Path(bl.identity_path(base)).read_text(encoding="utf-8"))["id"]


def test_m7_dos_instalaciones_con_el_mismo_nombre_no_comparten_carpeta(tmp_path, monkeypatch):
    a = _inst(tmp_path, "Survival", "Suite")
    b = _inst(tmp_path, "Creative", "Suite")
    raiz = str(tmp_path / "Respaldos")
    comun = os.path.join(raiz, "Suite")

    assert bl.save_root(a, raiz) == comun
    zip_a = _backup_en(a, monkeypatch)
    assert os.path.dirname(zip_a) == comun
    assert _dueno(comun) == {"id": _id(a), "path": a}

    carpeta_b = bl.save_root(b, raiz)
    assert carpeta_b == os.path.join(raiz, "Suite-" + _id(b)[:8])
    zip_b = _backup_en(b, monkeypatch)
    assert os.path.dirname(zip_b) == carpeta_b
    assert _dueno(carpeta_b)["path"] == b
    assert bl.describe(b)["shared_name"] is True and bl.describe(b)["backup_dir"] == carpeta_b
    assert bl.describe(a)["shared_name"] is False
    # Cada instalacion lista (y rota) solo lo suyo.
    for base, propio in ((a, zip_a), (b, zip_b)):
        monkeypatch.setattr(auto_backup, "BASE_DIR", base)
        assert backups_service._list_backup_files(auto_backup.get_backup_dir()) == [propio]


def test_m7_mover_la_instalacion_conserva_su_carpeta(tmp_path, monkeypatch):
    a = _inst(tmp_path, "x", "Suite")
    raiz = str(tmp_path / "Respaldos")
    carpeta = bl.save_root(a, raiz)
    _backup_en(a, monkeypatch)
    movida = str(tmp_path / "y" / "Suite")
    os.makedirs(os.path.dirname(movida))
    shutil.move(a, movida)

    assert bl.resolve_backup_dir(movida) == carpeta
    _backup_en(movida, monkeypatch)
    assert _dueno(carpeta)["path"] == movida  # el dueno sigue a la instalacion


def test_m7_una_copia_de_la_instalacion_recibe_carpeta_propia(tmp_path, monkeypatch):
    a = _inst(tmp_path, "x", "Suite")
    raiz = str(tmp_path / "Respaldos")
    carpeta = bl.save_root(a, raiz)
    _backup_en(a, monkeypatch)
    copia = str(tmp_path / "y" / "Suite")
    shutil.copytree(a, copia)

    carpeta_copia = bl.resolve_backup_dir(copia)

    assert _id(copia) != _id(a)
    assert carpeta_copia == os.path.join(raiz, "Suite-" + _id(copia)[:8])
    assert bl.resolve_backup_dir(a) == carpeta


def test_m7_borrar_data_no_cambia_la_carpeta(tmp_path, monkeypatch):
    a = _inst(tmp_path, "x", "Suite")  # carpeta predeterminada: el ajuste no esta en data/
    _backup_en(a, monkeypatch)
    carpeta = bl.resolve_backup_dir(a)
    shutil.rmtree(os.path.join(a, "data"))

    assert bl.resolve_backup_dir(a) == carpeta  # el dueno coincide por la ruta
    _backup_en(a, monkeypatch)
    assert _dueno(carpeta)["id"] == _id(a)  # y adopta la identidad nueva


def test_m7_un_backup_fallido_no_reclama_la_carpeta(tmp_path, monkeypatch):
    # Hallado al validar: el worker de un test corre en otro proceso (sin los
    # guards de conftest) y un backup que fallaba ya reclamaba la carpeta.
    a = _inst(tmp_path, "x", "Suite")
    monkeypatch.setattr(auto_backup, "BASE_DIR", a)
    monkeypatch.setattr(auto_backup, "WORLD_DIR", os.path.join(a, "worlds", "W"))
    monkeypatch.setattr(auto_backup, "WORLD_PARENT_DIR", os.path.join(a, "worlds"))

    with pytest.raises(auto_backup.SnapshotDesyncError):
        auto_backup.create_backup("periodico", file_snapshot=[("level.dat", 5), ("db/borrado.ldb", 3)])

    assert not os.path.exists(os.path.join(bl.resolve_backup_dir(a), bl.OWNER_FILE))
    assert not os.path.exists(bl.identity_path(a))


def test_m7_una_carpeta_parcheada_no_se_reclama(mundo_aislado):
    _base, _mundo, bk = mundo_aislado
    assert auto_backup.create_backup("manual")
    assert not (bk / bl.OWNER_FILE).exists()


# ═══════════════════════════════════════════════════════════════════════
# M8. Integridad: deflate danado y ZIP ilegible
# ═══════════════════════════════════════════════════════════════════════
def _zip_con_deflate_danado(path):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("level.dat", b"LEVEL")
        zf.writestr("db/000005.ldb", b"chunk del mundo " * 4000)
    with zipfile.ZipFile(path) as zf:
        info = zf.getinfo("db/000005.ldb")
    data = bytearray(Path(path).read_bytes())
    largo_nombre, largo_extra = struct.unpack("<HH", data[info.header_offset + 26:info.header_offset + 30])
    # BTYPE=11 en el primer bloque deflate: zlib.error al leer, no un CRC distinto.
    data[info.header_offset + 30 + largo_nombre + largo_extra] = 0xFF
    Path(path).write_bytes(bytes(data))


def test_m8_deflate_danado_es_corrupto_y_no_un_traceback(tmp_path):
    z = tmp_path / "auto_backup_roto.zip"
    _zip_con_deflate_danado(z)
    with zipfile.ZipFile(z) as zf, pytest.raises(zlib.error):
        zf.testzip()  # lo que usaban la GUI y tools/verify_backups.py

    motivo, nombres = zip_safety.check_zip_integrity(str(z))

    assert motivo.startswith("db/000005.ldb (error:")
    assert nombres == ["level.dat", "db/000005.ldb"]


def test_m8_cabecera_invalida_es_corrupto(tmp_path):
    z = tmp_path / "auto_backup_basura.zip"
    z.write_bytes(b"esto no es un zip")
    motivo, nombres = zip_safety.check_zip_integrity(str(z))
    assert motivo and nombres == []


def test_m8_verify_backups_marca_y_sigue_con_los_demas(tmp_path):
    mod = _cargar_tool("verify_backups")
    _zip_con_deflate_danado(tmp_path / "auto_backup_a_roto.zip")
    _zip_minimo(tmp_path / "auto_backup_b_bueno.zip")

    assert mod.revisar_todos(str(tmp_path)) == (1, 1, 0)

    assert (tmp_path / "auto_backup_a_roto_CORRUPTO.zip").exists()
    assert (tmp_path / "auto_backup_b_bueno.zip").exists()
    assert mod.main([str(tmp_path)]) == 0  # el marcado se salta; el bueno sigue OK


def test_m8_zip_ilegible_no_se_marca_y_sale_con_2(tmp_path):
    import _winapi
    mod = _cargar_tool("verify_backups")
    z = tmp_path / "auto_backup_bloqueado.zip"
    _zip_minimo(z)
    # Abierto sin compartir (antivirus, copia en curso): leerlo da PermissionError.
    handle = _winapi.CreateFile(str(z), _winapi.GENERIC_READ, 0, 0, _winapi.OPEN_EXISTING, 0, 0)
    try:
        assert mod.main([str(tmp_path)]) == 2
        assert z.exists()
    finally:
        _winapi.CloseHandle(handle)
    assert mod.main([str(tmp_path)]) == 0


def test_m8_gui_verifica_deflate_danado_como_corrupto(api):
    client, _base = api
    carpeta = Path(auto_backup.get_backup_dir())
    carpeta.mkdir(parents=True)
    _zip_con_deflate_danado(carpeta / "auto_backup_roto.zip")

    r = client.post("/api/backups/auto_backup_roto.zip/verify")

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "corrupt"
    assert r.json()["entry"].startswith("db/000005.ldb")


# ═══════════════════════════════════════════════════════════════════════
# M10. backups_revision
# ═══════════════════════════════════════════════════════════════════════
class _Stdout:
    def __init__(self, lineas):
        self._lineas = list(lineas)

    def readline(self):
        return self._lineas.pop(0) if self._lineas else ""


class _ProcFalso:
    def __init__(self, lineas):
        self.stdout = _Stdout(lineas)

    def wait(self):
        return 0


def test_m10_estado_publico_incluye_revision_y_backup_inicial(monkeypatch):
    monkeypatch.setattr(manager, "backups_revision", 0)
    monkeypatch.setattr(manager, "wrapper_pre_bds", True)

    estado = build_public_status(manager)
    assert estado["backups_revision"] == 0
    assert estado["initial_backup_in_progress"] is True

    manager.note_backups_changed()
    assert build_public_status(manager)["backups_revision"] == 1


@pytest.mark.parametrize("evento", [
    {"event": "bds_launched"},
    {"event": "backup_finished", "outcome": "success"},
    {"event": "final_backup_finished", "success": True, "zip": "x.zip"},
])
def test_m10_eventos_que_cambian_la_lista_suben_la_revision(monkeypatch, evento):
    for attr, valor in (("backups_revision", 5), ("final_backup_result", None),
                        ("wrapper_pre_bds", False), ("backup_in_progress", False)):
        monkeypatch.setattr(manager, attr, valor)
    supervisor._apply_event(evento)
    assert manager.backups_revision == 6


def test_m10_backup_por_consola_y_fin_del_wrapper_suben_la_revision(monkeypatch, tmp_path):
    monkeypatch.setattr(supervisor, "KNOWN_PLAYERS_PATH", str(tmp_path / "known_players.json"))
    for attr, valor in (("backups_revision", 0), ("events_alive", False), ("wrapper_process", None),
                        ("is_running", True), ("backup_in_progress", True)):
        monkeypatch.setattr(manager, attr, valor)

    supervisor.run_wrapper_thread(_ProcFalso(["[Wrapper] Backup finished", ""]))

    assert manager.backups_revision == 2  # fin del ciclo por consola + cierre de sesion


def test_m10_backup_en_frio_y_borrado_suben_la_revision(api, monkeypatch):
    client, _base = api
    monkeypatch.setattr(external_probe, "detect_external_bds", lambda base_dir=None: (False, None))
    monkeypatch.setattr(auto_backup, "create_backup", lambda trigger: None)
    monkeypatch.setattr(manager, "backups_revision", 0)

    lifecycle.cold_backup("gui_manual")
    assert manager.backups_revision == 1

    carpeta = Path(auto_backup.get_backup_dir())
    _zip_minimo(carpeta / "auto_backup_Srv_x.zip")
    assert client.post("/api/backups/auto_backup_Srv_x.zip/delete").status_code == 200
    assert manager.backups_revision == 2


# ═══════════════════════════════════════════════════════════════════════
# L1-L3. Empaquetado del backup
# ═══════════════════════════════════════════════════════════════════════
def test_l1_archivo_con_fecha_anterior_a_1980_no_aborta_el_backup(mundo_aislado):
    _base, mundo, _bk = mundo_aislado
    icono = mundo / "world_icon.jpeg"
    icono.write_bytes(b"icono")
    t = time.mktime((1975, 6, 1, 12, 0, 0, 0, 0, -1))
    os.utime(icono, (t, t))

    zip_path = auto_backup.create_backup("manual")

    assert zip_path
    with zipfile.ZipFile(zip_path) as zf:
        assert zf.getinfo("world_icon.jpeg").date_time[:3] == (1980, 1, 1)
        assert zf.read("world_icon.jpeg") == b"icono"


def test_l1_fecha_anterior_a_1970(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"x")
    try:
        os.utime(f, (-400 * 86400, -400 * 86400))
    except (OSError, OverflowError, ValueError):
        pytest.skip("el sistema no admite fijar esa fecha")

    zinfo = auto_backup._zipinfo_for(str(f), "a.bin")

    assert zinfo.date_time == (1980, 1, 1, 0, 0, 0)
    assert zinfo.file_size == 1


def _icacls(*args):
    return subprocess.run(["icacls", *args], capture_output=True)


def test_l2_carpeta_ilegible_aborta_el_backup(mundo_aislado):
    _base, mundo, bk = mundo_aislado
    _arbol(mundo, {"db/CURRENT": b"MANIFEST-000001\n", "db/000005.ldb": b"chunks"})
    usuario = os.environ.get("USERNAME", "")
    db = str(mundo / "db")
    if not usuario or _icacls(db, "/deny", f"{usuario}:(OI)(CI)(RD)").returncode != 0:
        pytest.skip("icacls no pudo denegar el listado")
    try:
        try:
            os.listdir(db)
        except PermissionError:
            pass
        else:
            pytest.skip("la denegacion no impide listar (privilegio de copia de seguridad)")
        resultado = auto_backup.create_backup("manual")
    finally:
        _icacls(db, "/remove:d", usuario)

    # Antes: ZIP publicado con level.dat y sin los chunks, aceptado por el restore.
    assert resultado is False
    assert [n for n in os.listdir(bk) if n.endswith((".zip", ".tmp"))] == []


def test_l3_junction_en_static_includes_no_entra_en_el_backup_en_caliente(mundo_aislado, tmp_path):
    _base, mundo, _bk = mundo_aislado
    externo = tmp_path / "fuera_de_la_instalacion"
    _arbol(externo, {"secreto.txt": b"NO DEBE ENTRAR"})
    _junction(mundo / "behavior_packs", externo)
    try:
        zip_path = auto_backup.create_backup("periodico", file_snapshot=[("level.dat", 50)])
    finally:
        os.rmdir(mundo / "behavior_packs")

    assert zip_path
    with zipfile.ZipFile(zip_path) as zf:
        nombres = zf.namelist()
    assert "level.dat" in nombres
    assert not any("secreto" in n for n in nombres)


# ═══════════════════════════════════════════════════════════════════════
# L4. Mutex que existe pero no se puede abrir (titular elevado)
# ═══════════════════════════════════════════════════════════════════════
_TITULAR_RESTRICTIVO = r'''
import ctypes, sys
from ctypes import wintypes
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
adv = ctypes.WinDLL("advapi32", use_last_error=True)

class SA(ctypes.Structure):
    _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p),
                ("bInheritHandle", wintypes.BOOL)]

sd = ctypes.c_void_p()
# Solo SYSTEM: como el mutex de un wrapper que corre elevado o como servicio.
if not adv.ConvertStringSecurityDescriptorToSecurityDescriptorW("D:(A;;GA;;;SY)", 1, ctypes.byref(sd), None):
    sys.exit(2)
sa = SA(ctypes.sizeof(SA), sd, False)
k32.CreateMutexW.restype = wintypes.HANDLE
if not k32.CreateMutexW(ctypes.byref(sa), True, sys.argv[1]):
    sys.exit(3)
print("listo", flush=True)
sys.stdin.read()
'''


def test_l4_mutex_inaccesible_cuenta_como_ocupado(tmp_path):
    nombre = "BDS_Test_L4_" + os.urandom(6).hex()
    script = tmp_path / "titular.py"
    script.write_text(_TITULAR_RESTRICTIVO, encoding="utf-8")
    with subprocess.Popen([sys.executable, str(script), "Local\\" + nombre],
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE) as titular:
        try:
            assert titular.stdout.readline().strip() == b"listo"
            sonda = wpg.NamedMutex(nombre)
            try:
                assert not sonda.handle and sonda.open_error == 5  # ERROR_ACCESS_DENIED
                assert sonda.acquire(timeout_ms=0) is False  # antes: True (fallaba en abierto)
            finally:
                sonda.close()
            assert wpg.mutex_held_by_other(nombre) is True
        finally:
            titular.stdin.close()
            titular.wait(timeout=30)


# ═══════════════════════════════════════════════════════════════════════
# L5. Proxy del sistema y la GUI local
# ═══════════════════════════════════════════════════════════════════════
class _GuiFalsa(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        cuerpo = json.dumps({"ok": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def log_message(self, *args):
        pass


def test_l5_el_auxiliar_no_usa_el_proxy_para_la_gui_local(monkeypatch):
    servidor = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _GuiFalsa)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    try:
        monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
        monkeypatch.delenv("NO_PROXY", raising=False)
        puerto = servidor.server_address[1]
        # Control: un opener por defecto lee el proxy del entorno y no llega.
        with pytest.raises(OSError):
            urllib.request.build_opener().open(f"http://127.0.0.1:{puerto}/api/status", timeout=3)

        assert suite_updater.get_json(puerto, "/api/status") == {"ok": True}
    finally:
        servidor.shutdown()
        servidor.server_close()
        hilo.join(5)


def test_l5_ninguna_llamada_del_auxiliar_usa_urlopen():
    assert "urllib.request.urlopen" not in (ROOT / "suite_updater.py").read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════
# L6. Reanudar Minecraft tras actualizar la suite
# ═══════════════════════════════════════════════════════════════════════
def _reanudar(monkeypatch, estado):
    """resume_minecraft con un reloj virtual; estado(t) da /api/status (o lanza)."""
    reloj = types.SimpleNamespace(t=0.0)

    def dormir(segundos):
        reloj.t += segundos

    monkeypatch.setattr(suite_updater, "time", types.SimpleNamespace(monotonic=lambda: reloj.t, sleep=dormir))
    llamadas = []

    def get_json(port, route, body=None):
        llamadas.append(route)
        if route == "/api/action/start":
            return {"status": "starting"}
        respuesta = estado(reloj.t)
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta

    monkeypatch.setattr(suite_updater, "get_json", get_json)
    ok = suite_updater.resume_minecraft({"restart_bds": True, "port": 8000})
    return ok, reloj.t, llamadas


def test_l6_backup_inicial_largo_no_es_un_arranque_fallido(monkeypatch):
    def estado(t):
        if t < 600:
            return {"running": True, "installed_version": None, "initial_backup_in_progress": True}
        if t < 640:
            return {"running": True, "installed_version": None, "initial_backup_in_progress": False}
        return {"running": True, "installed_version": "1.21.0"}

    ok, t, _ = _reanudar(monkeypatch, estado)
    assert ok is True and 640 <= t < 641


def test_l6_fallos_sueltos_de_la_api_se_toleran(monkeypatch):
    def estado(t):
        if t < 2:
            return OSError("HTTP 503")
        if t < 4:
            return ValueError("JSON a medias")
        return {"running": True, "installed_version": "1.21.0"}

    ok, _t, _ = _reanudar(monkeypatch, estado)
    assert ok is True


def test_l6_si_el_wrapper_termina_no_espera_al_plazo(monkeypatch):
    ok, t, _ = _reanudar(monkeypatch, lambda t: {"running": t < 5})
    assert ok is False and t < 10


def test_l6_bds_que_no_arranca_falla_al_terminar_el_plazo(monkeypatch):
    ok, t, _ = _reanudar(monkeypatch, lambda t: {"running": True, "installed_version": None})
    assert ok is False
    assert suite_updater.RESUME_START_SEC <= t < suite_updater.RESUME_START_SEC + 1


def test_l6_api_caida_falla_tras_los_errores_tolerados(monkeypatch):
    ok, _t, llamadas = _reanudar(monkeypatch, lambda t: OSError("caida"))
    assert ok is False
    assert llamadas.count("/api/status") == suite_updater.RESUME_MAX_ERRORS


def test_l6_backup_inicial_eterno_tiene_tope(monkeypatch):
    ok, t, _ = _reanudar(monkeypatch, lambda t: {"running": True, "initial_backup_in_progress": True})
    assert ok is False
    assert suite_updater.RESUME_MAX_SEC <= t < suite_updater.RESUME_MAX_SEC + 1


def test_l6_tope_alineado_con_el_del_wrapper():
    # El auxiliar no puede importar wrapper_state (corre con su propio runtime).
    assert suite_updater.RESUME_MAX_SEC == wrapper_state.BACKUP_TIMEOUT_MAX_SEC + suite_updater.RESUME_START_SEC


# ═══════════════════════════════════════════════════════════════════════
# L7. Puerto enlazado una sola vez
# ═══════════════════════════════════════════════════════════════════════
def _puerto_efimero():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_l7_uvicorn_sirve_en_el_socket_ya_enlazado():
    import uvicorn
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    app = Starlette(routes=[Route("/", lambda request: PlainTextResponse("ok"))])
    sock, puerto = gui._resolver_puerto(_puerto_efimero(), "127.0.0.1")
    try:
        # Mientras la GUI tiene el socket nadie mas puede tomar el puerto.
        assert gui._enlazar(puerto, "127.0.0.1") is None
        servidor = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=puerto, log_level="warning",
                                                 lifespan="off", ws="none"))
        hilo = threading.Thread(target=servidor.run, kwargs={"sockets": [sock]}, daemon=True)
        hilo.start()
        try:
            texto, fin = None, time.monotonic() + 15
            sin_proxy = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            while texto is None and time.monotonic() < fin:
                try:
                    with sin_proxy.open(f"http://127.0.0.1:{puerto}/", timeout=2) as r:
                        texto = r.read().decode()
                except OSError:
                    time.sleep(0.1)
            assert texto == "ok"
        finally:
            servidor.should_exit = True
            hilo.join(15)
    finally:
        sock.close()


def test_l7_entrypoint_usa_el_socket_y_sin_reintento_muerto():
    main = (ROOT / "server_gui_server.py").read_text(encoding="utf-8").split('if __name__ == "__main__":', 1)[1]
    assert "server.run(sockets=[sock])" in main
    assert "except OSError" not in main


# ═══════════════════════════════════════════════════════════════════════
# L8. Sesiones de jugadores al terminar el wrapper
# ═══════════════════════════════════════════════════════════════════════
def test_l8_jugadores_conectados_salen_con_la_sesion_del_wrapper(monkeypatch, tmp_path):
    monkeypatch.setattr(supervisor, "KNOWN_PLAYERS_PATH", str(tmp_path / "known_players.json"))
    for attr, valor in (("events_alive", False), ("wrapper_process", None), ("is_running", True)):
        monkeypatch.setattr(manager, attr, valor)
    manager.players_online.clear()
    manager.players_xuid.clear()
    history.start()

    # Sesion 1: BDS cae con Alice dentro (sin linea de desconexion).
    supervisor.run_wrapper_thread(_ProcFalso(["[INFO] Player connected: Alice, xuid: 111", ""]))
    # Sesion 2: vuelve a entrar y sale con normalidad.
    supervisor.run_wrapper_thread(_ProcFalso([
        "[INFO] Player connected: Alice, xuid: 111", "[INFO] Player disconnected: Alice, xuid: 111", ""]))

    sesiones = history.query_sessions(1)["sessions"]
    assert len(sesiones) == 2  # antes la reconexion reutilizaba la sesion abierta
    assert all(s["player"] == "Alice" and s["ended_ts"] is not None for s in sesiones)
    assert manager.players_online == set()


# ═══════════════════════════════════════════════════════════════════════
# L9-L10. Endpoints
# ═══════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("ruta,cuerpo", [
    ("/api/restore", "[1]"), ("/api/restore", '"x"'), ("/api/restore", "5"),
    ("/api/server_properties", "[1]"), ("/api/server_properties", '"x"'),
    ("/api/schedule", "[]"), ("/api/schedule", "0"),
    ("/api/schedule", '{"backup_interval_min": Infinity}'),
    ("/api/schedule", '{"backup_interval_min": 1e400}'),
])
def test_l9_cuerpos_json_que_no_son_un_objeto_dan_400(api, monkeypatch, tmp_path, ruta, cuerpo):
    client, _base = api
    destino = tmp_path / "schedule_config.json"
    monkeypatch.setattr(schedule_config, "SCHEDULE_PATH", str(destino))

    r = client.post(ruta, content=cuerpo, headers={"Content-Type": "application/json"})

    assert r.status_code == 400, r.text
    assert not destino.exists()  # "[]" o "0" ya no se guardan como un objeto vacio


def test_l10_restaurar_no_cambia_el_ultimo_backup(api, monkeypatch):
    client, _base = api
    monkeypatch.setattr(manager, "last_backup_time", "08:15:00")
    monkeypatch.setattr(backups_service, "restore_backup_under_lock",
                        lambda mgr, filename: os.path.join("x", "worlds", "W"))

    r = client.post("/api/restore", json={"filename": "auto_backup_Srv_x.zip"})

    assert r.status_code == 200, r.text
    assert manager.last_backup_time == "08:15:00"


# ═══════════════════════════════════════════════════════════════════════
# L14. Poda de respaldos de enable_beta_apis_v2
# ═══════════════════════════════════════════════════════════════════════
def test_l14_la_poda_nunca_borra_el_respaldo_recien_creado(tmp_path, monkeypatch):
    eb = _cargar_tool("enable_beta_apis_v2")

    class _Nbt:
        compound = {}

        def save_to(self, f, compressed=False, little_endian=True):
            f.write(b"\x0a\x00\x00\x00")

    falso = types.SimpleNamespace(load=lambda f, compressed=False, little_endian=True: _Nbt(),
                                  TAG_Compound=dict, TAG_Byte=int)
    monkeypatch.setattr(eb, "amulet_nbt", falso)  # amulet_nbt no esta en el .venv: el NBT da igual
    level = struct.pack("<II", 10, 4) + b"\x0a\x00\x00\x00"
    ahora = time.time()
    activo, otro = tmp_path / "worlds" / "Activo", tmp_path / "worlds" / "Otro"
    for i in range(3):  # respaldos RECIENTES de otro mundo
        _arbol(activo, {f"level.dat.respaldo_{i:08x}": level})
        os.utime(activo / f"level.dat.respaldo_{i:08x}", (ahora - i, ahora - i))
    viejo = ahora - 30 * 86400
    _arbol(otro, {"level.dat": level, **{f"level.dat.respaldo_viejo{i}": level for i in range(3)}})
    for i in range(3):
        os.utime(otro / f"level.dat.respaldo_viejo{i}", (viejo - i, viejo - i))
    os.utime(otro / "level.dat", (viejo, viejo))  # copy2 le daba esta fecha al respaldo nuevo

    eb.enable_experiments(str(otro / "level.dat"))

    propios = sorted(p.name for p in otro.iterdir() if ".respaldo_" in p.name)
    nuevos = [n for n in propios if "viejo" not in n]
    assert len(nuevos) == 1  # el que protege la reescritura sobrevive
    assert propios == sorted(nuevos + ["level.dat.respaldo_viejo0", "level.dat.respaldo_viejo1"])
    assert sorted(p.name for p in activo.iterdir()) == [f"level.dat.respaldo_{i:08x}" for i in range(3)]


# ═══════════════════════════════════════════════════════════════════════
# L16-L20. Lanzadores
# ═══════════════════════════════════════════════════════════════════════
def test_l16_modo_lan_no_salta_de_puerto():
    bat = (ROOT / "iniciar_gui_lan.bat").read_text(encoding="utf-8")
    assert re.search(r"(?im)^set GUI_PORT_STRICT=1\s*$", bat)
    main = (ROOT / "server_gui_server.py").read_text(encoding="utf-8").split('if __name__ == "__main__":', 1)[1]
    assert 'os.environ.get("GUI_PORT_STRICT"' in main and "estricto=estricto" in main
    ocupado = socket.socket()
    ocupado.bind(("127.0.0.1", 0))
    try:
        with pytest.raises(RuntimeError, match="GUI_PORT"):
            gui._resolver_puerto(ocupado.getsockname()[1], "127.0.0.1", estricto=True)
    finally:
        ocupado.close()


def test_l17_los_bat_que_fijan_variables_usan_setlocal():
    for bat in sorted(ROOT.glob("*.bat")):
        texto = bat.read_text(encoding="utf-8")
        primer_set = re.search(r"(?im)^\s*(?:if\b[^\r\n]*?\s)?set\s", texto)
        if primer_set is None:
            continue
        local = re.search(r"(?im)^\s*setlocal\b", texto)
        assert local is not None and local.start() < primer_set.start(), bat.name


@pytest.mark.parametrize("codigo,pausa", [(1, True), (0, False)])
def test_l18_iniciar_gui_con_runtime_deja_a_la_vista_un_error(instalacion_bat, codigo, pausa):
    inst, enlaces = instalacion_bat
    _junction(inst / "runtime", _python_base())
    enlaces.append(inst / "runtime")
    (inst / "server_gui_server.py").write_text(
        f"print('[ERROR] No hay puertos libres'); raise SystemExit({codigo})", encoding="utf-8")

    salida_codigo, salida = _cmd(inst / "iniciar_gui.bat", cwd=inst)

    assert salida_codigo == codigo, salida
    assert (_pausas(salida) == 1) is pausa, salida
    assert ("La GUI se cerro con un error" in salida) is pausa


def test_l19_los_ps1_con_acentos_llevan_bom():
    for ps1 in [*ROOT.glob("*.ps1"), *ROOT.glob("tools/*.ps1")]:
        data = ps1.read_bytes()
        if any(b > 0x7F for b in data):
            assert data.startswith(b"\xef\xbb\xbf"), ps1.name


def test_l19_powershell_5_lee_bien_el_script_de_defender():
    ps1 = ROOT / "tools" / "setup_defender_exclusions.ps1"
    analisis = (
        "$t=$null; $e=$null;"
        "$a=[System.Management.Automation.Language.Parser]::ParseFile($env:PS1_RUTA,[ref]$t,[ref]$e);"
        "'errores=' + $e.Count;"
        "$s=$a.FindAll({param($n) $n -is [System.Management.Automation.Language.StringConstantExpressionAst]"
        " -or $n -is [System.Management.Automation.Language.ExpandableStringExpressionAst]}, $true);"
        "'mojibake=' + @($s | Where-Object { $_.Value.Contains([string][char]0x00C3) }).Count;"
        "'enes=' + @($s | Where-Object { $_.Value.Contains([string][char]0x00F1) }).Count"
    )
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", analisis],
                           env=dict(os.environ, PS1_RUTA=str(ps1)), capture_output=True, timeout=120)
    except FileNotFoundError:
        pytest.skip("Windows PowerShell no disponible")
    salida = r.stdout.decode("ascii", errors="replace")
    assert "errores=0" in salida, salida
    assert "mojibake=0" in salida, salida  # sin BOM, PS 5.1 lee "añade" como "aÃ±ade"
    assert re.search(r"enes=[1-9]", salida), salida


@pytest.mark.parametrize("codigo_ps1,esperado", [(0, "[OK]"), (2, "[AVISO] Windows Defender no esta activo")])
def test_l20_configurar_antivirus_distingue_defender_inactivo(tmp_path, codigo_ps1, esperado):
    shutil.copy2(ROOT / "configurar_antivirus.bat", tmp_path / "configurar_antivirus.bat")
    (tmp_path / "tools").mkdir()
    # Sustituto del script real (que pide UAC y toca Defender): solo devuelve el codigo.
    (tmp_path / "tools" / "setup_defender_exclusions.ps1").write_text(f"exit {codigo_ps1}\n", encoding="ascii")

    codigo, salida = _cmd(tmp_path / "configurar_antivirus.bat", cwd=tmp_path)

    assert codigo == codigo_ps1, salida
    assert esperado in salida
    if codigo_ps1:
        assert "[OK]" not in salida


def test_l20_defender_inactivo_sale_con_2():
    ps1 = (ROOT / "tools" / "setup_defender_exclusions.ps1").read_text(encoding="utf-8-sig")
    rama = ps1.split("if (-not $defenderAvailable) {", 1)[1].split("\n}", 1)[0]
    assert re.search(r"(?m)^\s*exit 2\s*$", rama)
    assert not re.search(r"(?m)^\s*exit\s*$", ps1)  # ningun exit sin codigo (devolvia 0)


# ═══════════════════════════════════════════════════════════════════════
# L21. Diagnostico de tipo cruzado y filtro por tipo (espejo de addonsLogic.js)
# ═══════════════════════════════════════════════════════════════════════
FIXTURE_TIPO_CRUZADO = ROOT / "tests" / "fixtures" / "addons_tipo_cruzado.json"
UUID_A = "aaaaaaaa-1111-4111-8111-111111111111"
UUID_B = "bbbbbbbb-2222-4222-8222-222222222222"


def _instalacion_tipo_cruzado(base):
    """La instalacion con la que se genero el fixture (BP listado como recurso)."""
    def manifiesto(uuid, nombre, tipo):
        return json.dumps({
            "format_version": 2,
            "header": {"name": nombre, "description": nombre, "uuid": uuid,
                       "version": [1, 0, 0], "min_engine_version": [1, 20, 0]},
            "modules": [{"type": tipo, "uuid": uuid[:-1] + "9", "version": [1, 0, 0]}]}, indent=2).encode()

    _arbol(base, {
        "server.properties": b"level-name=Alfa\nserver-port=19132\n",
        "worlds/Alfa/level.dat": b"level",
        "behavior_packs/BP/manifest.json": manifiesto(UUID_A, "BP", "data"),
        "resource_packs/RP/manifest.json": manifiesto(UUID_B, "RP", "resources"),
        "worlds/Alfa/world_behavior_packs.json": b"[]",
        "worlds/Alfa/world_resource_packs.json": json.dumps([
            {"pack_id": UUID_A, "version": [1, 0, 0]}, {"pack_id": UUID_B, "version": [1, 0, 0]}]).encode(),
    })
    (base / "worlds" / "Alfa" / "behavior_packs").mkdir()
    (base / "worlds" / "Alfa" / "resource_packs").mkdir()


def _proyeccion(payload):
    return (
        [(d["code"], d["scope"], d["pack"], d["world"]) for d in payload["diagnostics"]],
        [(r["pack_id"], r["kind"], r["status"]) for w in payload["worlds"] for r in w["references"]],
        [(p["id"], p["kind"], p["scope"]) for p in payload["packs"]],
    )


def test_l21_el_fixture_es_lo_que_produce_el_analizador(tmp_path):
    """El fixture (generado con analyze_addons sobre esta misma instalacion y
    base_dir anonimizado) no puede quedar desfasado del analizador en lo que
    deciden los filtros."""
    _instalacion_tipo_cruzado(tmp_path)
    real = addon_inventory.analyze_addons(str(tmp_path))
    fixture = json.loads(FIXTURE_TIPO_CRUZADO.read_text(encoding="utf-8"))
    assert _proyeccion(real) == _proyeccion(fixture)
    assert ("WORLD_REF_KIND_MISMATCH", "resource", "behavior_packs/BP", "Alfa") in _proyeccion(real)[0]


def test_l21_filtro_por_tipo_conserva_el_diagnostico_de_tipo_cruzado():
    payload = json.loads(FIXTURE_TIPO_CRUZADO.read_text(encoding="utf-8"))

    def codigos(**filtro):
        return [d["code"] for d in addon_inventory.filter_payload(payload, **filtro)["diagnostics"]]

    # Mismas expectativas que gui_frontend/tests/addons.test.js (mismo fixture).
    assert codigos(kind="resource") == ["WORLD_REF_KIND_MISMATCH", "SCOPE_ROOT_MISSING"]
    assert codigos(world="Alfa", kind="resource") == ["WORLD_REF_KIND_MISMATCH", "SCOPE_ROOT_MISSING"]
    assert codigos(kind="behavior") == ["SCOPE_ROOT_MISSING"]
    vista = addon_inventory.filter_payload(payload, kind="resource")
    assert [r["status"] for r in vista["worlds"][0]["references"]] == ["kind_mismatch", "resolved"]
