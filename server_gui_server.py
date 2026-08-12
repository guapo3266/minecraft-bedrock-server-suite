"""
server_gui_server.py — Servidor Web FastAPI + WebSockets para el Minecraft Bedrock Wrapper GUI
=============================================================================================
Proporciona endpoints REST y comunicación por WebSockets en tiempo real para controlar el servidor,
visualizar logs, monitorear jugadores y gestionar backups desde el frontend animado (ReactBits).
"""

import os
import sys
import time
import json
import asyncio
import threading
import subprocess
import glob
import shutil
import tempfile
from typing import Set
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from contextlib import asynccontextmanager
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel
import uvicorn

import psutil
import requests
import zipfile
import re
from urllib.parse import urlsplit

# Importar lógica de auto_backup para consultar directorio de backups
import auto_backup
from console_lang import L, set_lang as _set_lang
# D5: patrones de deteccion del log de BDS centralizados en server_wrapper
from server_wrapper import _RE_PLAYER_CONNECT, _RE_PLAYER_DISCONNECT

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")
SERVER_EXE = os.path.join(BASE_DIR, "bedrock_server.exe")

# ═══════════════════════════════════════════════════════════════
# G8: tiempos de espera de apagado del wrapper (restart / update_bds).
# La GUI espera en DOS fases: primero que BDS muera (server_stopped_event,
# marcado por la linea "[Wrapper] BDS detenido..." del wrapper) y despues que
# el wrapper termine del todo, incluido el backup final de cierre. Antes se
# esperaba el evento de salida del wrapper con un unico timeout de 30s, pero
# ese evento solo llega tras el backup final (tope interno del wrapper: 135s
# de join del worker caliente + 240s del backup final): con un mundo grande
# el reinicio/actualizacion se abortaban siempre aunque BDS ya se hubiera
# detenido, y el mensaje de error era enganoso ("no se detuvo").
SERVER_STOP_TIMEOUT_SEC = 75      # Fase 1: max segundos esperando que BDS muera
                                  # (mayor que BDS_STOP_TIMEOUT_SEC=60 del wrapper:
                                  # el wrapper fuerza el kill y la GUI solo observa)
WRAPPER_EXIT_TIMEOUT_SEC = 450    # Fase 2: max segundos esperando al wrapper completo
                                  # (75 BDS + 135 join worker + 240 backup final + margen)

def _version_tuple(version: str):
    """Convierte '1.21.30.03' en (1, 21, 30, 3) para comparar versiones semánticamente."""
    parts = []
    for p in str(version).split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])

MOJANG_DOWNLOAD_API = "https://net-secondary.web.minecraft-services.net/api/v1.0/download/links"
MOJANG_DOWNLOAD_PAGE = "https://www.minecraft.net/en-us/download/server/bedrock"
_UA_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def _fetch_latest_bedrock_download():
    """Devuelve (url, version) de la ultima version estable de BDS, o (None, None).

    Fuente primaria: la API interna que usa la propia web de Mojang
    (/api/v1.0/download/links), que devuelve JSON con los links oficiales
    (verificado en vivo 2026-08-04). El HTML de la pagina ya no expone el
    link del zip, asi que el scrape queda solo como ultimo recurso.
    """
    try:
        r = requests.get(MOJANG_DOWNLOAD_API, headers=_UA_HEADERS, timeout=5)
        if r.status_code == 200:
            for link in r.json().get("result", {}).get("links", []):
                if link.get("downloadType") == "serverBedrockWindows":
                    url = link.get("downloadUrl") or ""
                    match = re.search(r"bedrock-server-(\d+\.\d+\.\d+\.\d+)\.zip", url)
                    if match:
                        return url, match.group(1)
    except Exception:
        pass
    # Ultimo recurso: scrape de la pagina oficial (fragil, puede dejar de funcionar).
    try:
        r = requests.get(MOJANG_DOWNLOAD_PAGE, headers=_UA_HEADERS, timeout=5)
        if r.status_code == 200:
            match = re.search(r'https://[^\s"]+?bedrock-server-(\d+\.\d+\.\d+\.\d+)\.zip', r.text)
            if match:
                return match.group(0), match.group(1)
    except Exception:
        pass
    return None, None


def _ensure_local(client_host: str):
    """S1: Solo acepta peticiones desde la propia máquina (loopback)."""
    if client_host not in ("127.0.0.1", "::1"):
        raise HTTPException(status_code=403, detail="Acceso denegado: solo conexiones locales")

_LOCAL_ORIGIN_HOSTS = ("127.0.0.1", "localhost")

def _is_allowed_origin(origin: str | None) -> bool:
    """S3: True si el header Origin viene de la propia máquina.

    Los navegadores siempre envían Origin en POST y en el handshake de
    WebSocket. Una página web maliciosa abierta en el navegador del usuario
    genera conexiones desde 127.0.0.1 (superando _ensure_local), así que el
    Origin es el único filtro que distingue "la GUI local" de "una web externa".
    Clientes sin navegador (curl, scripts) no envían Origin: se permiten y
    queda el filtro de IP como respaldo.
    """
    if not origin:
        return True
    try:
        host = urlsplit(origin).hostname
    except ValueError:
        return False
    return host in _LOCAL_ORIGIN_HOSTS

def _check_origin(request: Request):
    """Rechaza peticiones de navegador cuyo Origin no sea loopback (anti-CSRF)."""
    if not _is_allowed_origin(request.headers.get("origin")):
        raise HTTPException(status_code=403, detail="Acceso denegado: origen no permitido")

def _is_safe_zip_entry(filename: str) -> bool:
    """S2: True si la entrada del zip es segura para extraer.

    Conservador: rechaza rutas absolutas, cualquier segmento '..' (traversal,
    incluso normalizado internamente) y prefijos de unidad/ADS tipo 'C:'.
    """
    norm = filename.replace("\\", "/")
    if norm.startswith("/") or os.path.isabs(norm):
        return False
    segs = norm.split("/")
    if any(s == ".." for s in segs):
        return False
    if ":" in segs[0]:
        return False
    return True

# Caché de objetos psutil.Process por PID. Necesaria para que cpu_percent(interval=None)
# tenga baseline entre muestras (con objeto nuevo SIEMPRE devuelve 0.0). Se recrea el
# objeto si el PID cambia (p. ej. al reiniciar BDS o el wrapper).
_process_cache = {}


def _measure_process_tree():
    """Mide RAM y CPU acumuladas de todo lo relacionado al servidor:
    la propia GUI (server_gui_server.py), el wrapper (server_wrapper.py) y
    bedrock_server.exe (+ cualquier subproceso del wrapper, p. ej. compresión de backups).

    Devuelve (ram_mb_total, raw_cpu_por_nucleo)."""
    # PIDs del árbol: la GUI + todos sus descendientes recursivos (wrapper, BDS, compresión)
    pids = {os.getpid()}
    try:
        for child in psutil.Process(os.getpid()).children(recursive=True):
            try:
                pids.add(child.pid)
            except psutil.NoSuchProcess:
                pass
    except psutil.NoSuchProcess:
        pass

    # Limpiar de la caché los procesos que ya no existen
    for pid in list(_process_cache):
        if pid not in pids:
            _process_cache.pop(pid, None)

    ram_mb = 0.0
    raw_cpu = 0.0
    for pid in pids:
        try:
            proc = _process_cache.get(pid)
            if proc is None:
                proc = psutil.Process(pid)
                _process_cache[pid] = proc
            raw_cpu += proc.cpu_percent(interval=None)
            ram_mb += proc.memory_info().rss / (1024 * 1024)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            _process_cache.pop(pid, None)

    return ram_mb, raw_cpu


def get_hardware_metrics():
    """Mide RAM y CPU de todo lo relacionado al servidor (GUI + wrapper + BDS).
    CPU normalizada como % de la capacidad total de la máquina (igual que el
    Administrador de Tareas de Windows)."""
    sys_mem = psutil.virtual_memory()
    total_ram_gb = round(sys_mem.total / (1024**3), 1)
    system_used_gb = round(sys_mem.used / (1024**3), 1)
    system_available_gb = round(sys_mem.available / (1024**3), 1)
    system_used_pct = round(sys_mem.percent, 1)
    num_cores = psutil.cpu_count() or 1

    ram_mb, raw_cpu = _measure_process_tree()

    bds_ram_mb = round(ram_mb, 1)
    bds_ram_pct = round((ram_mb * 1024 * 1024 / sys_mem.total) * 100, 2)
    # psutil devuelve % por núcleo (puede superar 100); dividir entre núcleos
    # lo normaliza a % de la capacidad total de la máquina.
    bds_cpu_pct = round(raw_cpu / num_cores, 1)

    # Disco: el volumen donde viven el servidor y los backups (C:).
    disk = psutil.disk_usage(BASE_DIR)
    disk_total_gb = round(disk.total / (1024**3), 1)
    disk_free_gb = round(disk.free / (1024**3), 1)
    disk_used_pct = round(disk.percent, 1)

    return {
        "ram_mb": bds_ram_mb,
        "ram_pct": bds_ram_pct,
        "cpu_pct": bds_cpu_pct,
        "total_ram_gb": total_ram_gb,
        "system_used_gb": system_used_gb,
        "system_available_gb": system_available_gb,
        "system_used_pct": system_used_pct,
        "disk_total_gb": disk_total_gb,
        "disk_free_gb": disk_free_gb,
        "disk_used_pct": disk_used_pct
    }

# ═══════════════════════════════════════════════════════════════
# ESTADO GLOBAL DEL WRAPPER SERVIDOR
# ═══════════════════════════════════════════════════════════════
class ServerManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.wrapper_process = None
        self.is_running = False
        self.players_online = set()
        self.log_history = []
        self.max_log_history = 500
        self.start_time = None
        self.last_backup_time = "Ninguno"
        self.backup_in_progress = False
        self.update_in_progress = False
        self.installed_version = None  # FIX F1: version real capturada del log de BDS
        self.wrapper_exit_event = threading.Event()
        self.wrapper_exit_event.set()  # Sin wrapper en ejecución al inicio
        # G8: "BDS murió" separado de "wrapper terminó". Se marca al ver la
        # linea "[Wrapper] BDS detenido..." del wrapper (y como respaldo en el
        # finally del hilo). restart/update lo usan para saber que el mundo
        # quedo quieto sin esperar el backup final de cierre del wrapper.
        self.server_stopped_event = threading.Event()
        self.server_stopped_event.set()  # Sin wrapper: BDS tampoco corre
        self.active_websockets: Set[WebSocket] = set()
        self.loop = None
        # Exclusion mutua de operaciones que tocan servidor/mundo/instalacion:
        # start, restore y update no pueden solaparse (evita lanzar BDS mientras
        # se reemplaza el mundo o los binarios). El start lo toma sin bloqueo
        # (rechaza con 'busy' si hay contención); restore/update lo toman
        # bloqueante dentro de sus hilos.
        self.op_lock = threading.Lock()
        # Exclusion mutua de escrituras al stdin del wrapper (varios hilos:
        # /api/command, WebSocket y las acciones stop/restart/backup/update).
        # TextIOWrapper no es thread-safe: escrituras concurrentes pueden
        # entremezclarse o corromper el buffer del pipe.
        self.stdin_lock = threading.Lock()

    def add_log(self, text: str, log_type: str = "info"):
        timestamp = time.strftime("%H:%M:%S")
        entry = {"time": timestamp, "text": text.strip(), "type": log_type}
        with self.lock:
            self.log_history.append(entry)
            if len(self.log_history) > self.max_log_history:
                self.log_history.pop(0)
        
        # Broadcast vía WebSocket en asyncio
        if self.loop and self.active_websockets:
            asyncio.run_coroutine_threadsafe(self.broadcast({"type": "log", "data": entry}), self.loop)

    def update_status(self):
        hw = get_hardware_metrics()
        with self.lock:
            players = list(self.players_online)
        status_payload = {
            "type": "status",
            "data": {
                "running": self.is_running,
                "players": players,
                "player_count": len(players),
                "last_backup": self.last_backup_time,
                "backup_in_progress": self.backup_in_progress,
                "update_in_progress": self.update_in_progress,
                "uptime": int(time.time() - self.start_time) if (self.is_running and self.start_time) else 0,
                "hardware": hw
            }
        }
        if self.loop and self.active_websockets:
            asyncio.run_coroutine_threadsafe(self.broadcast(status_payload), self.loop)

    async def broadcast(self, message: dict):
        disconnected = set()
        for ws in list(self.active_websockets):
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.add(ws)
        for ws in disconnected:
            self.active_websockets.discard(ws)

manager = ServerManager()

# ═══════════════════════════════════════════════════════════════
# PROCESO WRAPPER EN SEGUNDO PLANO
# ═══════════════════════════════════════════════════════════════
def _spawn_wrapper_process():
    """Crea el subproceso del wrapper (server_wrapper.py).

    FIX G1: se llama SIEMPRE bajo op_lock desde start/restart, de modo que
    manager.wrapper_process existe antes de liberar el lock: update_bds y
    restore ya no pueden ver is_running=True con wrapper_process=None y
    saltarse la detencion del servidor.
    """
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    process = subprocess.Popen(
        [sys.executable, "-u", os.path.join(BASE_DIR, "server_wrapper.py")],
        cwd=BASE_DIR,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    # Limpia el estado de salida anterior antes de liberar op_lock. Si no,
    # update_bds puede ver un proceso nuevo pero un evento todavía marcado
    # como terminado y continuar sin esperar su cierre.
    manager.wrapper_exit_event.clear()
    # G8: un wrapper nuevo significa BDS (potencialmente) vivo otra vez.
    manager.server_stopped_event.clear()
    return process


def run_wrapper_thread(process=None):
    """Hilo que consume el stdout del wrapper y mantiene el estado de la GUI.

    `process` es el subproceso ya creado bajo op_lock (FIX G1); si es None
    (flujo legacy), el hilo lo crea el mismo.
    """

    # Cada arranque debe volver a descubrir la versión del proceso actual.
    manager.installed_version = None
    manager.add_log(L("[GUI Backend] Iniciando wrapper de Minecraft Bedrock...", "[GUI Backend] Starting Minecraft Bedrock wrapper..."), "system")
    manager.wrapper_exit_event.clear()
    manager.server_stopped_event.clear()
    manager.is_running = True
    manager.start_time = time.time()
    manager.update_status()

    try:
        if process is None:
            process = _spawn_wrapper_process()
        manager.wrapper_process = process

        # Leer stdout en tiempo real
        for line in iter(process.stdout.readline, ''):
            if not line:
                break
            
            line_str = line.strip()
            if not line_str:
                continue

            # FIX F1: capturar la version instalada real desde el log de BDS
            # ("Version: 1.26.33.2"); se usa en /api/check_update
            m_ver = re.search(r"Version:\s*(\d+\.\d+\.\d+\.\d+)", line_str)
            if m_ver:
                manager.installed_version = m_ver.group(1)

            # G8: BDS confirmado detenido. El wrapper lo anuncia al empezar su
            # limpieza final; en ese momento el mundo ya está quieto, aunque el
            # proceso del wrapper siga vivo haciendo el backup de cierre.
            # (Marcador bilingue: la consola adapta el texto al idioma GUI.)
            if "BDS stopped" in line_str or "BDS detenido" in line_str:
                manager.server_stopped_event.set()

            # Determinar tipo de log para coloreado en la GUI
            log_type = "info"
            # D5: patrones compartidos con server_wrapper (una sola fuente)
            m_conn = _RE_PLAYER_CONNECT.search(line_str)
            m_disc = _RE_PLAYER_DISCONNECT.search(line_str)
            if m_conn:
                log_type = "join"
                try:
                    name = m_conn.group(1).strip()
                    if not name:
                        raise ValueError("nombre de jugador ausente")
                    with manager.lock:
                        manager.players_online.add(name)
                    manager.update_status()
                except Exception:
                    pass
            elif m_disc:
                log_type = "leave"
                try:
                    name = m_disc.group(1).strip()
                    if not name:
                        raise ValueError("nombre de jugador ausente")
                    with manager.lock:
                        manager.players_online.discard(name)
                    manager.update_status()
                except Exception:
                    pass
            elif any(k in line_str.lower() for k in ("backup", "compres", "save query")):
                # FIX F2: "compres" es el prefijo comun de "compression"/"compresion":
                # la condicion externa NO debe excluir la linea del worker
                # ("Starting compression in a separate process...", sin la palabra
                # "backup").
                log_type = "backup"
                # la cadena debe coincidir EXACTA con la del wrapper (bilingue)
                if ("Starting compression in a separate process" in line_str
                        or "Iniciando compresion de archivos en proceso separado" in line_str):
                    manager.backup_in_progress = True
                    manager.update_status()
                elif ("Compression successful" in line_str or "Compresión exitosa" in line_str
                      or "Backup completed" in line_str or "Backup completado" in line_str):
                    manager.backup_in_progress = False
                    manager.last_backup_time = time.strftime("%H:%M:%S")
                    manager.update_status()
                elif "Backup finished" in line_str or "Backup finalizado" in line_str:
                    # H3: fin incondicional del ciclo de compresion (exito,
                    # fallo, timeout, watchdog o excepcion). Sin este reset el
                    # flag quedaba en True tras un backup fallido y el boton de
                    # backup en frio quedaba bloqueado hasta reiniciar la GUI.
                    manager.backup_in_progress = False
                    manager.update_status()
            elif ("ERROR" in line_str or "WARN" in line_str
                  or "Exception" in line_str or "Excepcion" in line_str or "Excepción" in line_str):
                log_type = "error"

            manager.add_log(line_str, log_type)

        process.wait()

    except Exception as e:
        manager.add_log(L(f"[GUI Backend] Error en el wrapper: {e}", f"[GUI Backend] Error in the wrapper: {e}"), "error")
    finally:
        manager.is_running = False
        manager.backup_in_progress = False
        manager.wrapper_process = None
        with manager.lock:
            manager.players_online.clear()
        manager.wrapper_exit_event.set()
        # G8: respaldo: si el hilo muere, BDS ya no corre.
        manager.server_stopped_event.set()
        manager.add_log(L("[GUI Backend] Servidor de Minecraft detenido.", "[GUI Backend] Minecraft server stopped."), "system")
        manager.update_status()


async def hardware_metrics_loop():
    while True:
        try:
            manager.update_status()
        except Exception:
            pass
        await asyncio.sleep(2.0)

@asynccontextmanager
async def lifespan(app: FastAPI):
    manager.loop = asyncio.get_running_loop()
    try:
        recover_interrupted_updates()
    except Exception as exc:
        manager.add_log(L(f"[Actualizador BDS] No se pudo revisar una actualizacion interrumpida: {exc}", f"[Actualizador BDS] Could not check for an interrupted update: {exc}"), "error")
    task = asyncio.create_task(hardware_metrics_loop())
    yield
    task.cancel()

app = FastAPI(title="ReactBits Minecraft Bedrock Wrapper GUI", lifespan=lifespan)

DIST_DIR = os.path.join(BASE_DIR, "gui_frontend", "dist")
STATIC_TARGET = DIST_DIR if os.path.exists(DIST_DIR) else WEB_DIR

if not os.path.exists(STATIC_TARGET):
    os.makedirs(STATIC_TARGET)

if os.path.exists(DIST_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(DIST_DIR, "assets")), name="assets")

app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/favicon.svg")
async def get_favicon():
    favicon_path = os.path.join(BASE_DIR, "gui_frontend", "public", "favicon.svg")
    if os.path.exists(favicon_path):
        return FileResponse(favicon_path)
    return FileResponse(os.path.join(WEB_DIR, "index.html"))


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    if os.path.exists(DIST_DIR):
        index_path = os.path.join(DIST_DIR, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
    index_path = os.path.join(WEB_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("<h1>Cargando GUI...</h1>")


@app.get("/api/status")
async def get_status(request: Request):
    _ensure_local(request.client.host if request.client else "")
    with manager.lock:
        players = list(manager.players_online)
    return {
        "running": manager.is_running,
        "players": players,
        "player_count": len(players),
        "last_backup": manager.last_backup_time,
        "backup_in_progress": manager.backup_in_progress,
        "update_in_progress": manager.update_in_progress,
        "uptime": int(time.time() - manager.start_time) if (manager.is_running and manager.start_time) else 0,
        "hardware": get_hardware_metrics()
    }


class CommandRequest(BaseModel):
    command: str


@app.post("/api/command")
async def send_command(req: CommandRequest, request: Request):
    _ensure_local(request.client.host if request.client else "")
    _check_origin(request)
    cmd = req.command.strip()
    if not cmd:
        return {"status": "ok"}

    if not manager.is_running or not manager.wrapper_process or manager.wrapper_process.poll() is not None:
        manager.add_log(f"> {cmd}", "command")
        manager.add_log(L("[SISTEMA] El servidor de Minecraft está APAGADO. Presiona '▶ Iniciar Servidor' primero.", "[SISTEMA] The Minecraft server is OFF. Press '▶ Start Server' first."), "error")
        return {"status": "offline", "message": "El servidor no está en ejecución"}
    
    try:
        with manager.stdin_lock:
            manager.wrapper_process.stdin.write(cmd + "\n")
            manager.wrapper_process.stdin.flush()
        manager.add_log(f"> {cmd}", "command")
        return {"status": "ok", "command": cmd}
    except Exception as e:
        manager.add_log(L(f"[GUI Backend] Error enviando comando: {e}", f"[GUI Backend] Error sending command: {e}"), "error")
        return {"status": "error", "message": str(e)}


# ═══════════════════════════════════════════════════════════════
# Editor de server.properties (subconjunto seguro de campos)
# ═══════════════════════════════════════════════════════════════
PROPS_PATH = os.path.join(BASE_DIR, "server.properties")

# Campos editables con su validacion. Los demas (comentarios, claves no
# listadas) se preservan tal cual al escribir.
PROPS_FIELDS = {
    "server-name": {"type": "string", "max": 128},
    "gamemode": {"type": "enum", "values": ["survival", "creative", "adventure"]},
    "difficulty": {"type": "enum", "values": ["peaceful", "easy", "normal", "hard"]},
    "allow-cheats": {"type": "bool"},
    "max-players": {"type": "int", "min": 1, "max": 999},
    "online-mode": {"type": "bool"},
    "allow-list": {"type": "bool"},
    "server-port": {"type": "int", "min": 1, "max": 65535},
    "view-distance": {"type": "int", "min": 5, "max": 96},
    "tick-distance": {"type": "int", "min": 4, "max": 12},
    "player-idle-timeout": {"type": "int", "min": 0, "max": 10080},
    "default-player-permission-level": {"type": "enum", "values": ["visitor", "member", "operator"]},
}


def _read_props_values():
    """{clave: valor} de las lineas activas (no comentadas) de server.properties."""
    values = {}
    if os.path.exists(PROPS_PATH):
        with open(PROPS_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                if key in PROPS_FIELDS:
                    values[key] = val.strip()
    return values


def _validate_props(values):
    """Valida {clave: valor} contra PROPS_FIELDS. Devuelve (ok, detalle)."""
    for key, raw in values.items():
        spec = PROPS_FIELDS.get(key)
        if spec is None:
            return False, f"campo desconocido: {key}"
        if spec["type"] == "enum":
            if raw not in spec["values"]:
                return False, f"{key}: valores validos: {', '.join(spec['values'])}"
        elif spec["type"] == "bool":
            if raw not in ("true", "false"):
                return False, f"{key}: debe ser true o false"
        elif spec["type"] == "int":
            try:
                n = int(raw)
            except (TypeError, ValueError):
                return False, f"{key}: debe ser un entero"
            if not (spec["min"] <= n <= spec["max"]):
                return False, f"{key}: rango {spec['min']}-{spec['max']}"
        elif spec["type"] == "string":
            if len(raw) > spec["max"]:
                return False, f"{key}: maximo {spec['max']} caracteres"
    return True, ""


def _write_props_values(values):
    """Actualiza las claves dadas preservando el resto del archivo.

    Reemplaza la primera linea activa 'clave=...'; si la clave no existe (o
    solo esta comentada), la anade al final. Devuelve las claves escritas.
    """
    with open(PROPS_PATH, encoding="utf-8") as f:
        lines = f.readlines()
    written = []
    for key, val in values.items():
        replaced = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith(key + "=") or stripped.startswith(key + " ="):
                lines[i] = f"{key}={val}\n"
                replaced = True
                break
        if not replaced:
            lines.append(f"{key}={val}\n")
        written.append(key)
    with open(PROPS_PATH, "w", encoding="utf-8", newline="") as f:
        f.writelines(lines)
    return written


@app.get("/api/server_properties")
async def get_server_properties(request: Request):
    """Devuelve los valores actuales de los campos editables."""
    _ensure_local(request.client.host if request.client else "")
    return {
        "fields": _read_props_values(),
        "server_running": manager.is_running,
    }


@app.post("/api/server_properties")
async def set_server_properties(request: Request):
    """Actualiza los campos editables de server.properties (los demas se preservan).

    Los cambios se aplican al REINICIAR el servidor (BDS lee el archivo al
    arrancar); se informa al frontend con 'restart_required'.
    """
    _ensure_local(request.client.host if request.client else "")
    _check_origin(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Cuerpo JSON invalido")
    values = (body or {}).get("values")
    if not isinstance(values, dict) or not values:
        raise HTTPException(status_code=400, detail="No hay campos para guardar")
    for v in values.values():
        if not isinstance(v, str):
            raise HTTPException(status_code=400, detail="Valores deben ser texto")
    ok, detalle = _validate_props(values)
    if not ok:
        raise HTTPException(status_code=400, detail=detalle)
    written = _write_props_values(values)
    manager.add_log(f"[GUI] Configuracion actualizada: {', '.join(sorted(written))}", "system")
    return {"status": "ok", "written": written, "restart_required": True}


@app.post("/api/action/{action_name}")
async def handle_action(action_name: str, request: Request):
    _ensure_local(request.client.host if request.client else "")
    _check_origin(request)
    action = action_name.lower()
    if action == "start":
        # Chequeo + marcado de estado ATOMICOS bajo op_lock (sin bloqueo: si
        # hay una restauracion o actualizacion en curso, se rechaza con 'busy'
        # en vez de esperar). Dos requests simultaneos ya no pueden ver ambos
        # is_running == False y lanzar dos wrappers.
        if not manager.op_lock.acquire(blocking=False):
            return {"status": "busy", "message": "Operación en curso (restauración/actualización)"}
        try:
            if manager.is_running:
                return {"status": "already_running"}
            # FIX G1: el subproceso del wrapper se crea BAJO el lock, de modo
            # que wrapper_process existe antes de liberarlo: update_bds y
            # restore ya no pueden ver is_running=True con wrapper_process
            # None y saltarse la detencion del servidor durante el arranque.
            try:
                proc = _spawn_wrapper_process()
            except Exception as e:
                manager.add_log(L(f"[GUI Backend] Error al iniciar el wrapper: {e}", f"[GUI Backend] Error starting the wrapper: {e}"), "error")
                return {"status": "error", "message": str(e)}
            # FIX G2: wrapper_process se asigna BAJO el lock (el hilo lo
            # re-afirma al arrancar): tras la respuesta de start, /stop ya
            # nunca ve is_running=True con wrapper_process=None.
            manager.wrapper_process = proc
            manager.is_running = True  # el hilo lo reafirma al arrancar
        finally:
            manager.op_lock.release()
        threading.Thread(target=run_wrapper_thread, args=(proc,), daemon=True).start()
        return {"status": "starting"}

    elif action == "stop":
        if not manager.is_running or not manager.wrapper_process:
            return {"status": "not_running"}
        try:
            with manager.stdin_lock:
                manager.wrapper_process.stdin.write("stop\n")
                manager.wrapper_process.stdin.flush()
            manager.add_log(L("[GUI Backend] Comando 'stop' enviado...", "[GUI Backend] 'stop' command sent..."), "system")
        except Exception:
            pass
        return {"status": "stopping"}

    elif action == "restart":
        def do_restart():
            exit_event = manager.wrapper_exit_event
            if manager.is_running and manager.wrapper_process:
                try:
                    with manager.stdin_lock:
                        manager.wrapper_process.stdin.write("stop\n")
                        manager.wrapper_process.stdin.flush()
                except Exception:
                    pass
                manager.add_log(L("[GUI Backend] Reiniciando servidor...", "[GUI Backend] Restarting server..."), "system")
                # G8: espera en DOS fases antes de lanzar otro wrapper (evita
                # dobles instancias y pisado de estado):
                #  Fase 1: que BDS muera (evento propio, independiente del
                #    cierre del wrapper). Antes se esperaba el evento de salida
                #    del wrapper con solo 30s, pero ese evento solo llega tras
                #    el backup final de cierre (tope interno de 240s): con un
                #    mundo grande el reinicio se abortaba siempre aunque el
                #    servidor ya se hubiera detenido.
                if not manager.server_stopped_event.wait(timeout=SERVER_STOP_TIMEOUT_SEC):
                    manager.add_log(
                        L(f"[GUI Backend] El servidor no se detuvo en {SERVER_STOP_TIMEOUT_SEC}s. "
                          "Reinicio cancelado.",
                          f"[GUI Backend] The server did not stop within {SERVER_STOP_TIMEOUT_SEC}s. "
                          "Restart cancelled."),
                        "error",
                    )
                    return
                #  Fase 2: que el wrapper termine del todo (backup final de
                #    cierre incluido) antes de lanzar otro: dos wrappers
                #    comprimiendo el mismo mundo pisarian sus copias.
                if not exit_event.wait(timeout=WRAPPER_EXIT_TIMEOUT_SEC):
                    manager.add_log(
                        L(f"[GUI Backend] El wrapper no termino en {WRAPPER_EXIT_TIMEOUT_SEC}s "
                          "(incluye el backup final de cierre). Reinicio cancelado; "
                          "inicia el servidor manualmente.",
                          f"[GUI Backend] The wrapper did not finish within {WRAPPER_EXIT_TIMEOUT_SEC}s "
                          "(includes the final shutdown backup). Restart cancelled; "
                          "start the server manually."),
                        "error",
                    )
                    return
            # Chequeo + lanzamiento atomicos bajo op_lock: si hay una
            # actualizacion/restauracion/backup en curso, no se re-lanza BDS
            # (arrancar mientras se reemplazan binarios o se copia el mundo
            # corromperia ambos).
            if not manager.op_lock.acquire(blocking=False):
                manager.add_log(L("[GUI Backend] Operación en curso (actualización/restauración/backup); reinicio abortado.", "[GUI Backend] Operation in progress (update/restore/backup); restart aborted."), "error")
                return
            try:
                # Alguien más pudo arrancar el servidor mientras esperábamos; no duplicar
                if manager.is_running:
                    manager.add_log(L("[GUI Backend] Otro inicio detectado durante el reinicio. Abortando.", "[GUI Backend] Another start detected during restart. Aborting."), "error")
                    return
                # FIX G1: crear el subproceso bajo el lock (igual que start)
                proc = _spawn_wrapper_process()
                # FIX G2: wrapper_process asignado bajo el lock
                manager.wrapper_process = proc
                # H1: marcar en marcha bajo el lock (igual que start). Sin
                # esto, dos restarts simultaneos podian ver is_running=False
                # tras el spawn y lanzar dos wrappers que pisarian el mundo.
                manager.is_running = True
                threading.Thread(target=run_wrapper_thread, args=(proc,), daemon=True).start()
            except Exception as e:
                manager.add_log(L(f"[GUI Backend] Error al iniciar el wrapper: {e}", f"[GUI Backend] Error starting the wrapper: {e}"), "error")
            finally:
                manager.op_lock.release()

        threading.Thread(target=do_restart, daemon=True).start()
        return {"status": "restarting"}

    elif action == "backup":
        if not manager.is_running or not manager.wrapper_process:
            # FIX G5: un backup en frio ya en curso -> rechazar con 409
            # (antes cada clic apilaba un hilo y dos backups del mismo
            # segundo podian pisarse por compartir nombre).
            if manager.backup_in_progress:
                return {"status": "busy", "message": L("Ya hay un backup en curso", "A backup is already in progress")}
            def manual_off_backup():
                # op_lock durante TODA la copia: un start inmediato modificaria
                # el mundo mientras se comprime, dando un backup inconsistente.
                with manager.op_lock:
                    # Re-chequeo atomico bajo el lock: `start` pudo ganar la
                    # carrera entre la decision del handler (servidor apagado)
                    # y la adquisicion del lock. Un backup en frio sobre un
                    # mundo vivo seria inconsistente.
                    if manager.is_running:
                        manager.add_log(
                            L("[GUI Backend] El servidor se encendió; backup en frío cancelado (usa el backup en caliente).", "[GUI Backend] The server started; cold backup cancelled (use the hot backup)."),
                            "error",
                        )
                        return
                    # Re-chequeo atomico bajo el lock (FIX G5): dos clics
                    # simultaneos pueden pasar el check del handler; aqui se
                    # descarta el segundo con op_lock ya adquirido.
                    if manager.backup_in_progress:
                        manager.add_log(
                            L("[GUI Backend] Ya hay un backup en frío en curso; solicitud ignorada.", "[GUI Backend] A cold backup is already in progress; request ignored."),
                            "error",
                        )
                        return
                    manager.backup_in_progress = True
                    manager.update_status()
                    manager.add_log(L("[GUI Backend] Ejecutando backup en frío...", "[GUI Backend] Running cold backup..."), "backup")
                    try:
                        zip_path = auto_backup.create_backup("gui_manual")
                        if zip_path:
                            manager.last_backup_time = time.strftime("%H:%M:%S")
                            manager.add_log(L(f"[GUI Backend] Backup exitoso: {os.path.basename(zip_path)}", f"[GUI Backend] Backup successful: {os.path.basename(zip_path)}"), "backup")
                        else:
                            manager.add_log(L("[GUI Backend] Error en backup: no se produjo un ZIP (revisa la consola del servidor).", "[GUI Backend] Backup error: no ZIP was produced (check the server console)."), "error")
                    except Exception as e:
                        manager.add_log(L(f"[GUI Backend] Error en backup: {e}", f"[GUI Backend] Backup error: {e}"), "error")
                    finally:
                        manager.backup_in_progress = False
                        manager.update_status()

            threading.Thread(target=manual_off_backup, daemon=True).start()
            return {"status": "backup_dispatched"}
        else:
            try:
                with manager.stdin_lock:
                    manager.wrapper_process.stdin.write("backup\n")
                    manager.wrapper_process.stdin.flush()
                manager.add_log(L("[GUI Backend] Disparando backup en caliente (comando backup)...", "[GUI Backend] Triggering hot backup (backup command)..."), "backup")
            except Exception as e:
                raise HTTPException(status_code=500, detail=L(f"Error al iniciar backup: {e}", f"Error starting backup: {e}"))
            return {"status": "hot_backup_dispatched"}

    elif action == "update_bds":
        # Guard anti doble actualización: dos threads pisándose bds_update.zip corromperían la instalación
        if manager.update_in_progress:
            return {"status": "already_updating"}
        # Flag sincrónico para que el frontend sepa que hay una actualización en curso
        manager.update_in_progress = True
        manager.update_status()

        def do_update():
            temp_zip = os.path.join(BASE_DIR, "bds_update.zip")
            downloaded_version = None
            staging_dir = None
            # op_lock durante TODO el ciclo de actualizacion (detener el
            # servidor, backup preventivo, descarga, extraccion): un start o
            # restart durante cualquiera de esas fases arrancaria BDS mientras
            # se reemplazan los binarios. El finally libera en todos los caminos.
            manager.op_lock.acquire()
            try:
                manager.add_log(L("[Actualizador BDS] Iniciando proceso de actualización de Mojang...", "[Actualizador BDS] Starting Mojang update process..."), "system")
                if manager.is_running and manager.wrapper_process:
                    manager.add_log(L("[Actualizador BDS] Deteniendo servidor de Minecraft...", "[Actualizador BDS] Stopping Minecraft server..."), "system")
                    try:
                        with manager.stdin_lock:
                            manager.wrapper_process.stdin.write("stop\n")
                            manager.wrapper_process.stdin.flush()
                    except Exception:
                        pass
                    # G8: espera en DOS fases antes de tocar binarios:
                    #  Fase 1: BDS muerto (evento propio; antes se esperaba la
                    #    salida del wrapper con 30s, que no llega hasta terminar
                    #    el backup final de cierre y abortaba la actualizacion
                    #    con un mensaje enganoso).
                    if not manager.server_stopped_event.wait(timeout=SERVER_STOP_TIMEOUT_SEC):
                        # D6: comportamiento intencional (nunca actualizar con el
                        # servidor vivo); el mensaje deja claro el estado y como seguir.
                        # H1: si vencio la fase 1, BDS puede seguir deteniendose:
                        # el mensaje no da por hecho que quedo detenido.
                        manager.add_log(
                            L(f"[Actualizador BDS] El servidor no se detuvo en {SERVER_STOP_TIMEOUT_SEC}s. "
                              "Actualización cancelada; "
                              "si el servidor quedó detenido, reinícialo con ▶ Iniciar.",
                              f"[Actualizador BDS] The server did not stop within {SERVER_STOP_TIMEOUT_SEC}s. "
                              "Update cancelled; "
                              "if the server ended up stopped, restart it with ▶ Start."),
                            "error",
                        )
                        return
                    #  Fase 2: wrapper completamente terminado (backup final de
                    #    cierre incluido) antes de reemplazar binarios o lanzar
                    #    el backup preventivo.
                    if not manager.wrapper_exit_event.wait(timeout=WRAPPER_EXIT_TIMEOUT_SEC):
                        manager.add_log(
                            L(f"[Actualizador BDS] El wrapper no termino en {WRAPPER_EXIT_TIMEOUT_SEC}s "
                              "(incluye el backup final de cierre). Actualización cancelada; "
                              "el servidor quedó detenido. Reinícialo con ▶ Iniciar.",
                              f"[Actualizador BDS] The wrapper did not finish within {WRAPPER_EXIT_TIMEOUT_SEC}s "
                              "(includes the final shutdown backup). Update cancelled; "
                              "the server ended up stopped. Restart it with ▶ Start."),
                            "error",
                        )
                        return

                manager.add_log(L("[Actualizador BDS] Ejecutando backup preventivo de seguridad...", "[Actualizador BDS] Running preventive safety backup..."), "backup")
                try:
                    zip_b = auto_backup.create_backup("pre_update_backup")
                    manager.add_log(L(f"[Actualizador BDS] Backup de seguridad listo: {os.path.basename(zip_b)}", f"[Actualizador BDS] Safety backup ready: {os.path.basename(zip_b)}"), "backup")
                except Exception as e:
                    manager.add_log(L(f"[Actualizador BDS] Error en backup preventivo: {e}", f"[Actualizador BDS] Error in preventive backup: {e}"), "error")

                # Obtener la URL oficial de descarga (API que usa la web de Mojang)
                url, downloaded_version = _fetch_latest_bedrock_download()
                if not url:
                    manager.add_log(L("[Actualizador BDS] No se pudo obtener la URL de descarga oficial. Abortando.", "[Actualizador BDS] Could not get the official download URL. Aborting."), "error")
                    return

                manager.add_log(L("[Actualizador BDS] Descargando binarios desde Mojang...", "[Actualizador BDS] Downloading binaries from Mojang..."), "system")
                # S3: límite de tamaño de descarga para no llenar el disco
                max_bytes = 400 * 1024 * 1024
                dl = requests.get(url, headers=_UA_HEADERS, stream=True, timeout=30)
                content_length = dl.headers.get("Content-Length")
                try:
                    if content_length and int(content_length) > max_bytes:
                        manager.add_log(L(f"[Actualizador BDS] Descarga demasiado grande ({content_length} bytes). Abortando.", f"[Actualizador BDS] Download too large ({content_length} bytes). Abortando."), "error")
                        return
                except (TypeError, ValueError):
                    pass
                total_bytes = 0
                with open(temp_zip, "wb") as f:
                    for chunk in dl.iter_content(chunk_size=8192):
                        total_bytes += len(chunk)
                        if total_bytes > max_bytes:
                            manager.add_log(L("[Actualizador BDS] Descarga excede el límite de 400 MB. Abortando.", "[Actualizador BDS] Download exceeds the 400 MB limit. Aborting."), "error")
                            return
                        f.write(chunk)

                manager.add_log(L("[Actualizador BDS] Descomprimiendo y actualizando ejecutable...", "[Actualizador BDS] Extracting and updating executable..."), "system")
                preserve_files = {"server.properties", "permissions.json", "allowlist.json", "whitelist.json"}
                preserve_dirs = {"worlds", "backups", "web", "gui_frontend"}

                # Staging: nunca se toca la instalacion con un zip a medias.
                # (op_lock ya cubre todo el ciclo desde el inicio de do_update.)
                staging_dir = os.path.join(BASE_DIR, "bds_update_staging")
                shutil.rmtree(staging_dir, ignore_errors=True)
                os.makedirs(staging_dir, exist_ok=True)
                with zipfile.ZipFile(temp_zip, "r") as z:
                    for item in z.infolist():
                        name = item.filename
                        # S2: anti zip-slip — rechazar rutas con '..', absolutas o con backslash malicioso
                        if not _is_safe_zip_entry(name):
                            manager.add_log(L(f"[Actualizador BDS] Entrada insegura en el zip ignorada: {name}", f"[Actualizador BDS] Unsafe zip entry ignored: {name}"), "error")
                            continue
                        z.extract(item, staging_dir)

                # D3: raiz efectiva del staging (zip plano actual o una unica
                # carpeta raiz historica); falla cerrada ante estructuras ambiguas.
                update_root = _resolve_update_root(staging_dir)

                # Aplica con rollback: si algo falla a mitad, la instalacion
                # vuelve a los binarios anteriores (sin versiones mezcladas).
                _apply_staged_update(update_root, BASE_DIR, preserve_files, preserve_dirs)
                if downloaded_version:
                    manager.installed_version = downloaded_version

                manager.add_log(L("[Actualizador BDS] ¡Servidor actualizado exitosamente a la versión oficial de Mojang!", "[Actualizador BDS] Server successfully updated to the official Mojang version!"), "system")
            except Exception as e:
                manager.add_log(L(f"[Actualizador BDS] Error al actualizar: {e}", f"[Actualizador BDS] Error updating: {e}"), "error")
            finally:
                manager.op_lock.release()
                if os.path.exists(temp_zip):
                    try: os.remove(temp_zip)
                    except Exception: pass
                if staging_dir and os.path.exists(staging_dir):
                    shutil.rmtree(staging_dir, ignore_errors=True)
                manager.update_in_progress = False
                manager.update_status()
                manager.add_log(L("[Actualizador BDS] Proceso de actualización finalizado.", "[Actualizador BDS] Update process finished."), "system")

        threading.Thread(target=do_update, daemon=True).start()
        return {"status": "update_dispatched"}

    else:
        raise HTTPException(status_code=400, detail="Acción no válida")


@app.get("/api/check_update")
async def check_update(request: Request):
    _ensure_local(request.client.host if request.client else "")

    # FIX F1: la version instalada REAL se captura del log de BDS
    # (run_wrapper_thread). Fallback al release-notes.txt (formato antiguo).
    current_ver = manager.installed_version
    if not current_ver:
        release_notes = os.path.join(BASE_DIR, "release-notes.txt")
        if os.path.exists(release_notes):
            try:
                with open(release_notes, "r", encoding="utf-8") as f:
                    content = f.read()
                    match = re.search(r"(\d+\.\d+\.\d+\.\d+)", content)
                    if match:
                        current_ver = match.group(1)
            except Exception:
                pass

    latest_ver = None
    download_url = None
    has_update = None  # True/False solo cuando ambas versiones son conocidas
    unavailable = False
    reason = None

    # API oficial que usa la web de Mojang (la pagina HTML ya no expone el zip)
    download_url, latest_ver = _fetch_latest_bedrock_download()
    if latest_ver:
        unavailable = False
    else:
        # Se reporta NO DISPONIBLE en vez de mentir con has_update=False.
        unavailable = True
        reason = "la API de Mojang no devolvio el link de descarga de Windows"

    if latest_ver and current_ver:
        # Comparación semántica numérica (evita falsos 'has_update' con versiones más nuevas)
        has_update = _version_tuple(latest_ver) > _version_tuple(current_ver)

    return {
        "current_version": current_ver,
        "latest_version": latest_ver,
        "download_url": download_url,
        "has_update": has_update,
        "unavailable": unavailable,
        "reason": reason,
    }


_CORRUPT_MARKERS = ("_CORRUPTO", "_EXCEDIDO")


def _resolve_update_root(staging_dir):
    """Resuelve la raiz efectiva del staging extraido (D3).

    El zip oficial actual es plano (validado con bedrock-server-1.26.33.2:
    9761 entradas, bedrock_server.exe en la raiz), pero algunas distribuciones
    envuelven el contenido en una unica carpeta raiz (p.ej.
    'bedrock-server-X.Y.Z.W/'). Se acepta solo esa forma inequivoca; cualquier
    estructura ambigua sigue fallando cerrada. Lanza RuntimeError si no hay
    bedrock_server.exe en ninguna de las dos formas.
    """
    update_root = staging_dir
    if not os.path.exists(os.path.join(update_root, "bedrock_server.exe")):
        top_entries = os.listdir(staging_dir)
        top_dirs = [
            name for name in top_entries
            if os.path.isdir(os.path.join(staging_dir, name))
        ]
        top_files = [
            name for name in top_entries
            if os.path.isfile(os.path.join(staging_dir, name))
        ]
        if len(top_dirs) == 1 and not top_files:
            candidate = os.path.join(staging_dir, top_dirs[0])
            if os.path.exists(os.path.join(candidate, "bedrock_server.exe")):
                update_root = candidate

    if not os.path.exists(os.path.join(update_root, "bedrock_server.exe")):
        raise RuntimeError(
            "El zip descargado no contiene bedrock_server.exe; se aborta sin tocar la instalacion."
        )
    return update_root


def _is_preserved_update_path(rel, preserve_files, preserve_dirs):
    """True si una ruta relativa del zip de actualizacion no debe reemplazarse."""
    rel_norm = rel.replace("\\", "/")
    return rel_norm in preserve_files or any(
        rel_norm.startswith(d + "/") for d in preserve_dirs
    )


_UPDATE_MANIFEST_NAME = ".bds_update_manifest.json"


def recover_interrupted_updates(base_dir=BASE_DIR):
    """Recupera una actualización interrumpida antes de aceptar operaciones.

    `_apply_staged_update` escribe un manifiesto antes de mover el primer
    binario. Si el proceso muere entre las dos fases, el manifiesto permite
    quitar archivos nuevos y devolver exactamente los archivos que existían.
    Un directorio antiguo sin manifiesto se conserva para inspección manual.
    """
    pattern = os.path.join(base_dir, "bds_update_prev_*")
    for prev_dir in glob.glob(pattern):
        if not os.path.isdir(prev_dir):
            continue
        manifest_path = os.path.join(prev_dir, _UPDATE_MANIFEST_NAME)
        if not os.path.isfile(manifest_path):
            continue
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                entries = json.load(f)
            if not isinstance(entries, list):
                raise ValueError("manifiesto no es una lista")

            for entry in entries:
                rel = entry.get("path") if isinstance(entry, dict) else None
                had_previous = entry.get("had_previous") if isinstance(entry, dict) else None
                if not isinstance(rel, str) or not isinstance(had_previous, bool) or not _is_safe_zip_entry(rel):
                    raise ValueError("entrada invalida en manifiesto")
                target = os.path.abspath(os.path.join(base_dir, rel.replace("/", os.sep)))
                if os.path.commonpath([os.path.abspath(base_dir), target]) != os.path.abspath(base_dir):
                    raise ValueError("ruta fuera de la instalacion")
                if os.path.isfile(target):
                    os.remove(target)
                if had_previous:
                    old_path = os.path.join(prev_dir, rel.replace("/", os.sep))
                    if os.path.isfile(old_path):
                        os.makedirs(os.path.dirname(target), exist_ok=True)
                        os.replace(old_path, target)
            shutil.rmtree(prev_dir, ignore_errors=True)
        except Exception as exc:
            # No borrar un resguardo que no se pudo interpretar: conserva la
            # posibilidad de recuperación manual y evita agravar el incidente.
            print(f"[Actualizador BDS] No se pudo recuperar {os.path.basename(prev_dir)}: {exc}")


def _apply_staged_update(staging_dir, base_dir, preserve_files, preserve_dirs):
    """Aplica un staging extraido a base_dir con rollback ante fallo.

    Fase 1: mueve los archivos actuales que seran reemplazados a un dir
    temporal (mismo volumen). Fase 2: mueve los nuevos desde el staging
    (os.replace, atomico por archivo). Si algo falla en la fase 2, se restauran
    los archivos resguardados y se eliminan los parcialmente aplicados: la
    instalacion nunca queda con binarios de versiones mezcladas.
    """
    prev_dir = tempfile.mkdtemp(prefix="bds_update_prev_", dir=base_dir)
    applied = []  # rutas relativas ya movidas del staging al destino
    try:
        manifest = []
        for root, _dirs, names in os.walk(staging_dir):
            for n in names:
                rel = os.path.relpath(os.path.join(root, n), staging_dir)
                if _is_preserved_update_path(rel, preserve_files, preserve_dirs):
                    continue
                target = os.path.join(base_dir, rel)
                manifest.append({
                    "path": rel.replace("\\", "/"),
                    "had_previous": os.path.isfile(target),
                })
        manifest_tmp = os.path.join(prev_dir, _UPDATE_MANIFEST_NAME + ".tmp")
        with open(manifest_tmp, "w", encoding="utf-8") as f:
            json.dump(manifest, f)
        os.replace(manifest_tmp, os.path.join(prev_dir, _UPDATE_MANIFEST_NAME))

        # Fase 1: resguardar los actuales que seran reemplazados
        for root, _dirs, names in os.walk(staging_dir):
            for n in names:
                rel = os.path.relpath(os.path.join(root, n), staging_dir)
                if _is_preserved_update_path(rel, preserve_files, preserve_dirs):
                    continue
                target = os.path.join(base_dir, rel)
                if os.path.isfile(target):
                    prev_target = os.path.join(prev_dir, rel)
                    os.makedirs(os.path.dirname(prev_target), exist_ok=True)
                    os.replace(target, prev_target)

        # Fase 2: aplicar los nuevos
        for root, _dirs, names in os.walk(staging_dir):
            for n in names:
                rel = os.path.relpath(os.path.join(root, n), staging_dir)
                if _is_preserved_update_path(rel, preserve_files, preserve_dirs):
                    continue
                target = os.path.join(base_dir, rel)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                os.replace(os.path.join(root, n), target)
                applied.append(rel)
    except Exception:
        # Rollback: quitar lo parcialmente aplicado y restaurar lo resguardado
        for rel in applied:
            try:
                os.remove(os.path.join(base_dir, rel))
            except OSError:
                pass
        for root, _dirs, names in os.walk(prev_dir):
            for n in names:
                rel = os.path.relpath(os.path.join(root, n), prev_dir)
                if rel.replace("\\", "/") == _UPDATE_MANIFEST_NAME:
                    continue
                target = os.path.join(base_dir, rel)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                os.replace(os.path.join(root, n), target)
        raise
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
        shutil.rmtree(prev_dir, ignore_errors=True)


def _list_backup_files(backup_dir):
    """Zips de backup visibles para restauracion.

    Excluye los marcados como corruptos/excedidos (mismos criterios que
    auto_backup.rotate_backups): restaurar un backup corrupto siempre falla.
    """
    return [
        z for z in glob.glob(os.path.join(backup_dir, "*.zip"))
        if not any(marker in os.path.basename(z) for marker in _CORRUPT_MARKERS)
    ]


@app.get("/api/backups")
async def list_backups(request: Request):
    _ensure_local(request.client.host if request.client else "")
    backup_dir = auto_backup.BACKUP_DIR
    if not os.path.exists(backup_dir):
        return {"backups": []}

    zips = _list_backup_files(backup_dir)
    backups_info = []
    for z in sorted(zips, key=os.path.getmtime, reverse=True):
        size_mb = round(os.path.getsize(z) / (1024 * 1024), 2)
        mtime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(z)))
        backups_info.append({
            "filename": os.path.basename(z),
            "size_mb": size_mb,
            "date": mtime
        })
    return {"backups": backups_info}


@app.post("/api/restore")
async def restore_backup(request: Request):
    """Restaura un backup al mundo. Rechaza si el servidor esta encendido.

    La restauracion (I/O pesada) se ejecuta en un threadpool para no
    bloquear el event loop de los WebSockets.
    """
    _ensure_local(request.client.host if request.client else "")
    _check_origin(request)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Cuerpo JSON invalido")
    filename = (body or {}).get("filename", "")

    if not filename or os.path.basename(filename) != filename:
        raise HTTPException(status_code=400, detail="Nombre de backup invalido")

    if manager.is_running:
        raise HTTPException(
            status_code=409,
            detail="Debes apagar el servidor antes de reestablecer un backup",
        )

    manager.add_log(L(f"[GUI] Restaurando backup: {filename}", f"[GUI] Restoring backup: {filename}"), "backup")

    def _restore_with_running_guard():
        # Re-chequeo ATOMICO dentro del threadpool: op_lock excluye a start y
        # update, y bajo el lock se verifica is_running. Sin esto, un inicio
        # simultaneo podria lanzar BDS mientras se reemplaza el mundo.
        with manager.op_lock:
            if manager.is_running:
                raise HTTPException(
                    status_code=409,
                    detail="El servidor se encendió durante la restauración; operación cancelada",
                )
            return auto_backup.restore_backup(filename)

    try:
        restored_path = await run_in_threadpool(_restore_with_running_guard)
    except HTTPException:
        # El guard interno (409 si el servidor se encendio) debe propagarse
        # tal cual; no dejarlo caer en el except Exception -> 500.
        raise
    except FileNotFoundError as e:
        manager.add_log(L(f"[GUI] Error al restaurar {filename}: {e}", f"[GUI] Error restoring {filename}: {e}"), "error")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        manager.add_log(L(f"[GUI] Error al restaurar {filename}: {e}", f"[GUI] Error restoring {filename}: {e}"), "error")
        raise HTTPException(status_code=500, detail=str(e))

    manager.add_log(L(f"[GUI] Backup restaurado: {os.path.basename(restored_path)}", f"[GUI] Backup restored: {os.path.basename(restored_path)}"), "backup")
    manager.last_backup_time = time.strftime("%H:%M:%S")
    return {"status": "ok", "backup": filename}


@app.get("/api/backups/{filename}/download")
async def download_backup(filename: str, request: Request):
    """Descarga un backup ZIP ya existente en el directorio de backups.

    Misma validacion de nombre que /api/restore (solo basename, sin
    traversal): el archivo debe estar dentro de BACKUP_DIR.
    """
    _ensure_local(request.client.host if request.client else "")
    _check_origin(request)
    if not filename or os.path.basename(filename) != filename:
        raise HTTPException(status_code=400, detail="Nombre de backup invalido")
    full = os.path.join(auto_backup.BACKUP_DIR, filename)
    if not os.path.isfile(full):
        raise HTTPException(status_code=404, detail="Backup no encontrado")
    return FileResponse(full, filename=filename, media_type="application/zip")


@app.post("/api/backups/{filename}/delete")
async def delete_backup(filename: str, request: Request):
    """Elimina un backup ZIP.

    Rechaza mientras haya un backup en curso (el archivo podria estar
    escribiendose) y con el mismo filtro de nombre que /api/restore.
    """
    _ensure_local(request.client.host if request.client else "")
    _check_origin(request)
    if not filename or os.path.basename(filename) != filename:
        raise HTTPException(status_code=400, detail="Nombre de backup invalido")
    if manager.backup_in_progress:
        raise HTTPException(
            status_code=409,
            detail="Hay un backup en curso; espera a que termine antes de eliminar",
        )
    full = os.path.join(auto_backup.BACKUP_DIR, filename)
    if not os.path.isfile(full):
        raise HTTPException(status_code=404, detail="Backup no encontrado")
    try:
        os.remove(full)
    except OSError as e:
        manager.add_log(L(f"[GUI] Error al eliminar backup {filename}: {e}", f"[GUI] Error deleting backup {filename}: {e}"), "error")
        raise HTTPException(status_code=500, detail=str(e))
    manager.add_log(L(f"[GUI] Backup eliminado: {filename}", f"[GUI] Backup deleted: {filename}"), "backup")
    return {"status": "ok", "backup": filename}


@app.post("/api/backups/{filename}/verify")
async def verify_backup(filename: str, request: Request):
    """Verifica la integridad de un backup ZIP (testzip: CRC de todas las
    entradas). Lento en zips grandes: corre en el threadpool para no bloquear
    el event loop de los WebSockets.
    """
    _ensure_local(request.client.host if request.client else "")
    _check_origin(request)
    if not filename or os.path.basename(filename) != filename:
        raise HTTPException(status_code=400, detail="Nombre de backup invalido")
    full = os.path.join(auto_backup.BACKUP_DIR, filename)
    if not os.path.isfile(full):
        raise HTTPException(status_code=404, detail="Backup no encontrado")

    def _verify():
        with zipfile.ZipFile(full, "r") as zf:
            bad = zf.testzip()
        return bad

    try:
        bad = await run_in_threadpool(_verify)
    except zipfile.BadZipFile as e:
        # Archivo truncado/cabecera rota: es el resultado "corrupto", no un error
        manager.add_log(L(f"[GUI] Backup corrupto: {filename} ({e})", f"[GUI] Corrupt backup: {filename} ({e})"), "error")
        return {"status": "corrupt", "filename": filename, "entry": str(e)}
    except Exception as e:
        manager.add_log(L(f"[GUI] Error al verificar {filename}: {e}", f"[GUI] Error verifying {filename}: {e}"), "error")
        raise HTTPException(status_code=500, detail=str(e))
    if bad:
        manager.add_log(L(f"[GUI] Backup corrupto: {filename} ({bad})", f"[GUI] Corrupt backup: {filename} ({bad})"), "error")
        return {"status": "corrupt", "filename": filename, "entry": bad}
    manager.add_log(L(f"[GUI] Backup verificado: {filename}", f"[GUI] Backup verified: {filename}"), "backup")
    return {"status": "ok", "filename": filename}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # S1: solo conexiones desde la propia máquina
    if websocket.client is None or websocket.client.host not in ("127.0.0.1", "::1"):
        await websocket.close(code=1008)
        return
    # S3: rechazar handshakes de navegador con Origin externo (anti-CSRF)
    if not _is_allowed_origin(websocket.headers.get("origin")):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    manager.active_websockets.add(websocket)

    # Idioma de la consola: query param (primer arranque) o mensaje set_lang
    # (cambios en vivo). Fija WRAPPER_LANG, que usan L() y el wrapper.
    _set_lang(websocket.query_params.get("lang"))

    with manager.lock:
        logs = list(manager.log_history)
        players = list(manager.players_online)

    await websocket.send_json({
        "type": "init",
        "logs": logs,
        "status": {
            "running": manager.is_running,
            "players": players,
            "player_count": len(players),
            "last_backup": manager.last_backup_time,
            "backup_in_progress": manager.backup_in_progress,
            "update_in_progress": manager.update_in_progress,
            "uptime": int(time.time() - manager.start_time) if (manager.is_running and manager.start_time) else 0,
            "hardware": get_hardware_metrics()
        }
    })

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "command":
                    cmd = msg.get("command", "").strip()
                    if cmd and manager.is_running and manager.wrapper_process:
                        with manager.stdin_lock:
                            manager.wrapper_process.stdin.write(cmd + "\n")
                            manager.wrapper_process.stdin.flush()
                        manager.add_log(f"> {cmd}", "command")
                elif msg.get("type") == "ping":
                    # Medición real de latencia del frontend
                    await websocket.send_json({"type": "pong"})
                elif msg.get("type") == "set_lang":
                    _set_lang(msg.get("lang"))
            except Exception:
                pass
    except WebSocketDisconnect:
        manager.active_websockets.discard(websocket)


def _puerto_libre(puerto: int) -> bool:
    """Comprueba si un puerto local está disponible para enlazar.

    Sin SO_REUSEADDR a propósito: uvicorn no lo usa, y en Windows ese flag
    permite a un socket "hijackear" un puerto ya ocupado (falso positivo).
    """
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", puerto))
            return True
        except OSError:
            return False


if __name__ == "__main__":
    import webbrowser

    try:
        puerto = int(os.environ.get("GUI_PORT", "8000"))
        if not (1 <= puerto <= 65535):
            raise ValueError
    except ValueError:
        print("[AVISO] GUI_PORT no es un puerto válido. Usando 8000.")
        puerto = 8000

    # Si el puerto pedido está ocupado (p. ej. SillyTavern en 8000),
    # saltar al siguiente puerto libre para no chocar con la otra app.
    while not _puerto_libre(puerto):
        print(f"[AVISO] El puerto {puerto} ya está en uso. Probando el siguiente libre...")
        puerto += 1

    url = f"http://127.0.0.1:{puerto}"
    print("=================================================================")
    print("  MINECRAFT BEDROCK WRAPPER GUI - REACTBITS DASHBOARD")
    print(f"  Abriendo en: {url}")
    print("=================================================================")
    try:
        webbrowser.open(url)
    except Exception:
        pass  # sin navegador disponible no es crítico
    try:
        uvicorn.run("server_gui_server:app", host="127.0.0.1", port=puerto, reload=False, log_level="info")
    except OSError:
        print(f"\n[AVISO] El puerto {puerto} se ocupó justo al abrir. Reintentando en el siguiente libre...")
        time.sleep(2)
        uvicorn.run("server_gui_server:app", host="127.0.0.1", port=puerto + 1, reload=False, log_level="info")
