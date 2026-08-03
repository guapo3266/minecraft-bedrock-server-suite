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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")
SERVER_EXE = os.path.join(BASE_DIR, "bedrock_server.exe")

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

    return {
        "ram_mb": bds_ram_mb,
        "ram_pct": bds_ram_pct,
        "cpu_pct": bds_cpu_pct,
        "total_ram_gb": total_ram_gb,
        "system_used_gb": system_used_gb,
        "system_available_gb": system_available_gb,
        "system_used_pct": system_used_pct
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
        self.wrapper_exit_event = threading.Event()
        self.wrapper_exit_event.set()  # Sin wrapper en ejecución al inicio
        self.active_websockets: Set[WebSocket] = set()
        self.loop = None
        # Exclusion mutua de operaciones que tocan servidor/mundo/instalacion:
        # start, restore y update no pueden solaparse (evita lanzar BDS mientras
        # se reemplaza el mundo o los binarios). El start lo toma sin bloqueo
        # (rechaza con 'busy' si hay contención); restore/update lo toman
        # bloqueante dentro de sus hilos.
        self.op_lock = threading.Lock()

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
        status_payload = {
            "type": "status",
            "data": {
                "running": self.is_running,
                "players": list(self.players_online),
                "player_count": len(self.players_online),
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
def run_wrapper_thread():
    """Ejecuta server_wrapper.py como un subproceso y redirige su stdout."""
    python_exe = sys.executable
    wrapper_path = os.path.join(BASE_DIR, "server_wrapper.py")

    manager.add_log("[GUI Backend] Iniciando wrapper de Minecraft Bedrock...", "system")
    manager.wrapper_exit_event.clear()
    manager.is_running = True
    manager.start_time = time.time()
    manager.update_status()

    try:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

        process = subprocess.Popen(
            [python_exe, "-u", wrapper_path],
            cwd=BASE_DIR,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
            env=env
        )
        manager.wrapper_process = process

        # Leer stdout en tiempo real
        for line in iter(process.stdout.readline, ''):
            if not line:
                break
            
            line_str = line.strip()
            if not line_str:
                continue

            # Determinar tipo de log para coloreado en la GUI
            log_type = "info"
            if "Player connected:" in line_str:
                log_type = "join"
                try:
                    name = line_str.split("Player connected:")[1].split(",")[0].strip()
                    manager.players_online.add(name)
                    manager.update_status()
                except Exception:
                    pass
            elif "Player disconnected:" in line_str:
                log_type = "leave"
                try:
                    name = line_str.split("Player disconnected:")[1].split(",")[0].strip()
                    manager.players_online.discard(name)
                    manager.update_status()
                except Exception:
                    pass
            elif "backup" in line_str.lower() or "compresión" in line_str.lower() or "save query" in line_str.lower():
                log_type = "backup"
                if "Iniciando compresión" in line_str or "Iniciando proceso de backup" in line_str:
                    manager.backup_in_progress = True
                    manager.update_status()
                elif "Compresión exitosa" in line_str or "Backup completado" in line_str:
                    manager.backup_in_progress = False
                    manager.last_backup_time = time.strftime("%H:%M:%S")
                    manager.update_status()
            elif "ERROR" in line_str or "WARN" in line_str or "Excepcion" in line_str:
                log_type = "error"

            manager.add_log(line_str, log_type)

        process.wait()

    except Exception as e:
        manager.add_log(f"[GUI Backend] Error en el wrapper: {e}", "error")
    finally:
        manager.is_running = False
        manager.backup_in_progress = False
        manager.wrapper_process = None
        manager.players_online.clear()
        manager.wrapper_exit_event.set()
        manager.add_log("[GUI Backend] Servidor de Minecraft detenido.", "system")
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
    return {
        "running": manager.is_running,
        "players": list(manager.players_online),
        "player_count": len(manager.players_online),
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
        manager.add_log("[SISTEMA] El servidor de Minecraft está APAGADO. Presiona '▶ Iniciar Servidor' primero.", "error")
        return {"status": "offline", "message": "El servidor no está en ejecución"}
    
    try:
        manager.wrapper_process.stdin.write(cmd + "\n")
        manager.wrapper_process.stdin.flush()
        manager.add_log(f"> {cmd}", "command")
        return {"status": "ok", "command": cmd}
    except Exception as e:
        manager.add_log(f"[GUI Backend] Error enviando comando: {e}", "error")
        return {"status": "error", "message": str(e)}


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
            manager.is_running = True  # el hilo lo reafirma al arrancar
        finally:
            manager.op_lock.release()
        threading.Thread(target=run_wrapper_thread, daemon=True).start()
        return {"status": "starting"}

    elif action == "stop":
        if not manager.is_running or not manager.wrapper_process:
            return {"status": "not_running"}
        try:
            manager.wrapper_process.stdin.write("stop\n")
            manager.wrapper_process.stdin.flush()
            manager.add_log("[GUI Backend] Comando 'stop' enviado...", "system")
        except Exception:
            pass
        return {"status": "stopping"}

    elif action == "restart":
        def do_restart():
            exit_event = manager.wrapper_exit_event
            if manager.is_running and manager.wrapper_process:
                try:
                    manager.wrapper_process.stdin.write("stop\n")
                    manager.wrapper_process.stdin.flush()
                except Exception:
                    pass
                manager.add_log("[GUI Backend] Reiniciando servidor...", "system")
                # Espera real (con tope) a que el wrapper anterior termine
                # antes de lanzar otro: evita dobles instancias y pisado de estado.
                if not exit_event.wait(timeout=30):
                    manager.add_log("[GUI Backend] El servidor no se detuvo en 30s. Reinicio cancelado.", "error")
                    return
            # Chequeo + lanzamiento atomicos bajo op_lock: si hay una
            # actualizacion/restauracion/backup en curso, no se re-lanza BDS
            # (arrancar mientras se reemplazan binarios o se copia el mundo
            # corromperia ambos).
            if not manager.op_lock.acquire(blocking=False):
                manager.add_log("[GUI Backend] Operación en curso (actualización/restauración/backup); reinicio abortado.", "error")
                return
            try:
                # Alguien más pudo arrancar el servidor mientras esperábamos; no duplicar
                if manager.is_running:
                    manager.add_log("[GUI Backend] Otro inicio detectado durante el reinicio. Abortando.", "error")
                    return
                threading.Thread(target=run_wrapper_thread, daemon=True).start()
            finally:
                manager.op_lock.release()

        threading.Thread(target=do_restart, daemon=True).start()
        return {"status": "restarting"}

    elif action == "backup":
        if not manager.is_running or not manager.wrapper_process:
            def manual_off_backup():
                # op_lock durante TODA la copia: un start inmediato modificaria
                # el mundo mientras se comprime, dando un backup inconsistente.
                with manager.op_lock:
                    manager.backup_in_progress = True
                    manager.update_status()
                    manager.add_log("[GUI Backend] Ejecutando backup en frío...", "backup")
                    try:
                        zip_path = auto_backup.create_backup("gui_manual")
                        if zip_path:
                            manager.last_backup_time = time.strftime("%H:%M:%S")
                            manager.add_log(f"[GUI Backend] Backup exitoso: {os.path.basename(zip_path)}", "backup")
                        else:
                            manager.add_log("[GUI Backend] Error en backup: no se produjo un ZIP (revisa la consola del servidor).", "error")
                    except Exception as e:
                        manager.add_log(f"[GUI Backend] Error en backup: {e}", "error")
                    finally:
                        manager.backup_in_progress = False
                        manager.update_status()

            threading.Thread(target=manual_off_backup, daemon=True).start()
            return {"status": "backup_dispatched"}
        else:
            try:
                manager.wrapper_process.stdin.write("backup\n")
                manager.wrapper_process.stdin.flush()
                manager.add_log("[GUI Backend] Disparando backup en caliente (comando backup)...", "backup")
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Error al iniciar backup: {e}")
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
            # op_lock durante TODO el ciclo de actualizacion (detener el
            # servidor, backup preventivo, descarga, extraccion): un start o
            # restart durante cualquiera de esas fases arrancaria BDS mientras
            # se reemplazan los binarios. El finally libera en todos los caminos.
            manager.op_lock.acquire()
            try:
                manager.add_log("[Actualizador BDS] Iniciando proceso de actualización de Mojang...", "system")
                if manager.is_running and manager.wrapper_process:
                    manager.add_log("[Actualizador BDS] Deteniendo servidor de Minecraft...", "system")
                    try:
                        manager.wrapper_process.stdin.write("stop\n")
                        manager.wrapper_process.stdin.flush()
                    except Exception:
                        pass
                    # Esperar a que el proceso termine de verdad antes de tocar archivos
                    if not manager.wrapper_exit_event.wait(timeout=30):
                        manager.add_log("[Actualizador BDS] El servidor no se detuvo en 30s. Actualización cancelada.", "error")
                        return

                manager.add_log("[Actualizador BDS] Ejecutando backup preventivo de seguridad...", "backup")
                try:
                    zip_b = auto_backup.create_backup("pre_update_backup")
                    manager.add_log(f"[Actualizador BDS] Backup de seguridad listo: {os.path.basename(zip_b)}", "backup")
                except Exception as e:
                    manager.add_log(f"[Actualizador BDS] Error en backup preventivo: {e}", "error")

                # Obtener la URL oficial de descarga (sin fallback hardcodeado obsoleto)
                url = None
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                try:
                    r = requests.get("https://www.minecraft.net/en-us/download/server/bedrock", headers=headers, timeout=5)
                    if r.status_code == 200:
                        match = re.search(r'https://[^\s"]+?bedrock-server-\d+\.\d+\.\d+\.\d+\.zip', r.text)
                        if match:
                            url = match.group(0)
                except Exception:
                    pass
                if not url:
                    manager.add_log("[Actualizador BDS] No se pudo obtener la URL de descarga oficial. Abortando.", "error")
                    return

                manager.add_log("[Actualizador BDS] Descargando binarios desde Mojang...", "system")
                # S3: límite de tamaño de descarga para no llenar el disco
                max_bytes = 400 * 1024 * 1024
                dl = requests.get(url, headers=headers, stream=True, timeout=30)
                content_length = dl.headers.get("Content-Length")
                try:
                    if content_length and int(content_length) > max_bytes:
                        manager.add_log(f"[Actualizador BDS] Descarga demasiado grande ({content_length} bytes). Abortando.", "error")
                        return
                except (TypeError, ValueError):
                    pass
                total_bytes = 0
                with open(temp_zip, "wb") as f:
                    for chunk in dl.iter_content(chunk_size=8192):
                        total_bytes += len(chunk)
                        if total_bytes > max_bytes:
                            manager.add_log("[Actualizador BDS] Descarga excede el límite de 400 MB. Abortando.", "error")
                            return
                        f.write(chunk)

                manager.add_log("[Actualizador BDS] Descomprimiendo y actualizando ejecutable...", "system")
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
                            manager.add_log(f"[Actualizador BDS] Entrada insegura en el zip ignorada: {name}", "error")
                            continue
                        z.extract(item, staging_dir)

                if not os.path.exists(os.path.join(staging_dir, "bedrock_server.exe")):
                    raise RuntimeError(
                        "El zip descargado no contiene bedrock_server.exe; se aborta sin tocar la instalacion."
                    )

                # Aplica con rollback: si algo falla a mitad, la instalacion
                # vuelve a los binarios anteriores (sin versiones mezcladas).
                _apply_staged_update(staging_dir, BASE_DIR, preserve_files, preserve_dirs)

                manager.add_log("[Actualizador BDS] ¡Servidor actualizado exitosamente a la versión oficial de Mojang!", "system")
            except Exception as e:
                manager.add_log(f"[Actualizador BDS] Error al actualizar: {e}", "error")
            finally:
                manager.op_lock.release()
                if os.path.exists(temp_zip):
                    try: os.remove(temp_zip)
                    except Exception: pass
                manager.update_in_progress = False
                manager.update_status()
                manager.add_log("[Actualizador BDS] Proceso de actualización finalizado.", "system")

        threading.Thread(target=do_update, daemon=True).start()
        return {"status": "update_dispatched"}

    else:
        raise HTTPException(status_code=400, detail="Acción no válida")


@app.get("/api/check_update")
async def check_update(request: Request):
    _ensure_local(request.client.host if request.client else "")
    current_ver = "1.21.0.0"
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

    latest_ver = current_ver
    download_url = None
    has_update = False

    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get("https://www.minecraft.net/en-us/download/server/bedrock", headers=headers, timeout=5)
        if resp.status_code == 200:
            match = re.search(r'https://[^\s"]+?bedrock-server-(\d+\.\d+\.\d+\.\d+)\.zip', resp.text)
            if match:
                download_url = match.group(0)
                latest_ver = match.group(1)
                # Comparación semántica numérica (evita falsos 'has_update' con versiones más nuevas)
                if _version_tuple(latest_ver) > _version_tuple(current_ver):
                    has_update = True
    except Exception:
        pass

    return {
        "current_version": current_ver,
        "latest_version": latest_ver,
        "download_url": download_url,
        "has_update": has_update
    }


_CORRUPT_MARKERS = ("_CORRUPTO", "_EXCEDIDO")


def _is_preserved_update_path(rel, preserve_files, preserve_dirs):
    """True si una ruta relativa del zip de actualizacion no debe reemplazarse."""
    rel_norm = rel.replace("\\", "/")
    return rel_norm in preserve_files or any(
        rel_norm.startswith(d + "/") for d in preserve_dirs
    )


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

    manager.add_log(f"[GUI] Restaurando backup: {filename}", "backup")

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
        manager.add_log(f"[GUI] Error al restaurar {filename}: {e}", "error")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        manager.add_log(f"[GUI] Error al restaurar {filename}: {e}", "error")
        raise HTTPException(status_code=500, detail=str(e))

    manager.add_log(f"[GUI] Backup restaurado: {os.path.basename(restored_path)}", "backup")
    manager.last_backup_time = time.strftime("%H:%M:%S")
    return {"status": "ok", "backup": filename}


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

    with manager.lock:
        logs = list(manager.log_history)

    await websocket.send_json({
        "type": "init",
        "logs": logs,
        "status": {
            "running": manager.is_running,
            "players": list(manager.players_online),
            "player_count": len(manager.players_online),
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
                        manager.wrapper_process.stdin.write(cmd + "\n")
                        manager.wrapper_process.stdin.flush()
                        manager.add_log(f"> {cmd}", "command")
                elif msg.get("type") == "ping":
                    # Medición real de latencia del frontend
                    await websocket.send_json({"type": "pong"})
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
