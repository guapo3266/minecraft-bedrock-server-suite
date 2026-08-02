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
from typing import Set
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from contextlib import asynccontextmanager
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

def get_hardware_metrics():
    """Mide RAM y CPU de bedrock_server.exe coincidiendo 1 a 1 con el Administrador de Tareas de Windows."""
    sys_mem = psutil.virtual_memory()
    total_ram_gb = round(sys_mem.total / (1024**3), 1)
    system_used_gb = round(sys_mem.used / (1024**3), 1)
    system_available_gb = round(sys_mem.available / (1024**3), 1)
    system_used_pct = round(sys_mem.percent, 1)
    num_cores = psutil.cpu_count() or 1

    bds_ram_mb = 0.0
    bds_ram_pct = 0.0
    bds_cpu_pct = 0.0

    if manager.is_running and manager.wrapper_process and manager.wrapper_process.poll() is None:
        try:
            parent = psutil.Process(manager.wrapper_process.pid)
            children = parent.children(recursive=True)
            
            # Buscar específicamente la instancia ejecutable de bedrock_server.exe
            target_proc = None
            for child in children:
                try:
                    if "bedrock" in child.name().lower():
                        target_proc = child
                        break
                except Exception:
                    pass
            
            if not target_proc:
                target_proc = children[0] if children else parent

            mem = target_proc.memory_info()
            bds_ram_mb = round(mem.rss / (1024 * 1024), 1)
            bds_ram_pct = round((mem.rss / sys_mem.total) * 100, 2)

            # Normalizar CPU dividiendo entre los núcleos de la PC (igual que el Administrador de Tareas de Windows)
            raw_cpu = target_proc.cpu_percent(interval=None)
            bds_cpu_pct = round(raw_cpu / num_cores, 1)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

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
        if manager.is_running:
            return {"status": "already_running"}
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
                # Alguien más pudo arrancar el servidor mientras esperábamos; no duplicar
                if manager.is_running:
                    manager.add_log("[GUI Backend] Otro inicio detectado durante el reinicio. Abortando.", "error")
                    return
            threading.Thread(target=run_wrapper_thread, daemon=True).start()

        threading.Thread(target=do_restart, daemon=True).start()
        return {"status": "restarting"}

    elif action == "backup":
        if not manager.is_running or not manager.wrapper_process:
            def manual_off_backup():
                manager.backup_in_progress = True
                manager.update_status()
                manager.add_log("[GUI Backend] Ejecutando backup en frío...", "backup")
                try:
                    zip_path = auto_backup.create_backup("gui_manual")
                    manager.last_backup_time = time.strftime("%H:%M:%S")
                    manager.add_log(f"[GUI Backend] Backup exitoso: {os.path.basename(zip_path)}", "backup")
                except Exception as e:
                    manager.add_log(f"[GUI Backend] Error en backup: {e}", "error")
                finally:
                    manager.backup_in_progress = False
                    manager.update_status()

            threading.Thread(target=manual_off_backup, daemon=True).start()
            return {"status": "backup_dispatched"}
        else:
            try:
                manager.wrapper_process.stdin.write("save hold\n")
                manager.wrapper_process.stdin.flush()
                manager.add_log("[GUI Backend] Disparando backup en caliente (save hold)...", "backup")
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

                with zipfile.ZipFile(temp_zip, "r") as z:
                    for item in z.infolist():
                        name = item.filename
                        if any(name.startswith(d + "/") for d in preserve_dirs) or name in preserve_files:
                            continue
                        # S2: anti zip-slip — rechazar rutas con '..', absolutas o con backslash malicioso
                        if not _is_safe_zip_entry(name):
                            manager.add_log(f"[Actualizador BDS] Entrada insegura en el zip ignorada: {name}", "error")
                            continue
                        z.extract(item, BASE_DIR)

                manager.add_log("[Actualizador BDS] ¡Servidor actualizado exitosamente a la versión oficial de Mojang!", "system")
            except Exception as e:
                manager.add_log(f"[Actualizador BDS] Error al actualizar: {e}", "error")
            finally:
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


@app.get("/api/backups")
async def list_backups(request: Request):
    _ensure_local(request.client.host if request.client else "")
    backup_dir = auto_backup.BACKUP_DIR
    if not os.path.exists(backup_dir):
        return {"backups": []}

    zips = glob.glob(os.path.join(backup_dir, "*.zip"))
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


if __name__ == "__main__":
    print("=================================================================")
    print("  MINECRAFT BEDROCK WRAPPER GUI - REACTBITS DASHBOARD")
    print("  Abriendo en: http://127.0.0.1:8000")
    print("=================================================================")
    try:
        uvicorn.run("server_gui_server:app", host="127.0.0.1", port=8000, reload=False, log_level="info")
    except OSError:
        print("\n[AVISO] El puerto 8000 estaba en uso. Reintentando apertura...")
        time.sleep(2)
        uvicorn.run("server_gui_server:app", host="127.0.0.1", port=8000, reload=False, log_level="info")
