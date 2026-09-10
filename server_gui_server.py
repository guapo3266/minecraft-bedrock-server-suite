"""
server_gui_server.py — Punto de entrada de la GUI Bedrock Wrapper
=================================================================
Crea la app FastAPI (create_app), monta estáticos, arranca el lifespan
(recuperación de actualizaciones + métricas) y sirve por Uvicorn en loopback
por defecto. Con GUI_ALLOW_LAN=1 o GUI_HOST=0.0.0.0 abre a la LAN (ver
gui_backend/security.py).

Los endpoints y el protocolo WebSocket viven en gui_backend/routers/;
la lógica de dominio en gui_backend/services/ y el estado/locks en
gui_backend/state.py. Este módulo conserva solo los re-exports que los
tests/herramientas aún importan desde aquí (ver docs/ARCHITECTURE.md).
"""

import asyncio
import contextlib
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
import uvicorn

import auto_backup
from console_lang import L

from gui_backend import config
from gui_backend.config import BASE_DIR  # noqa: F401  (re-export: lo usan tests)
from gui_backend.security import _allow_lan, _ensure_local, _check_origin, _is_allowed_origin, _is_safe_zip_entry  # noqa: F401  (dos ultimos: re-exports para tests)
from gui_backend.metrics import get_hardware_metrics
from gui_backend.state import manager
from gui_backend.services import external_probe as external_probe_service
from gui_backend.services import bds_update as bds_update_service
from gui_backend.services import watchdog as watchdog_service
from gui_backend.services import history as history_service
from gui_backend.routers import system, properties, setup, actions, backups, websocket, schedule, players, history


async def hardware_metrics_loop():
    tick = 0
    _metric_errs = 0
    _metric_last_log = 0.0
    while True:
        try:
            # Sonda psutil (itera procesos) y muestreo de hardware: fuera del
            # event loop para no congelar WebSockets/endpoints cada 2s.
            await run_in_threadpool(external_probe_service.update_external_instance_state)
            manager.update_status()
            tick += 1
            if tick % 15 == 0:  # cada ~30s: persistir metricas + retencion diaria
                hw = await run_in_threadpool(get_hardware_metrics)
                history_service.record_metrics(hw, manager.is_running)
                history_service.maybe_sweep()
        except Exception as e:
            # Antes: pass silencioso y la GUI mostraba métricas congeladas
            # como si fueran actuales. Ahora: print throttled a consola
            # (no add_log: cada 2s inundaría SQLite/WS y cogería lock).
            _metric_errs += 1
            now = time.time()
            if now - _metric_last_log >= 300:
                _metric_last_log = now
                print(L(f"[Métricas] Muestreo degradado ({_metric_errs} fallos): {type(e).__name__}: {e}",
                        f"[Metrics] Degraded sampling ({_metric_errs} failures): {type(e).__name__}: {e}"))
        await asyncio.sleep(2.0)

@asynccontextmanager
async def lifespan(app: FastAPI):
    manager.loop = asyncio.get_running_loop()
    try:
        auto_backup.recover_interrupted_restores(config.BASE_DIR)
    except Exception as exc:
        manager.add_log(L(f"[Backups] Error en recuperación de restauraciones: {exc}", f"[Backups] Error in restore recovery: {exc}"), "error")
    try:
        bds_update_service.recover_interrupted_updates()
    except Exception as exc:
        manager.add_log(L(f"[Actualizador BDS] No se pudo revisar una actualizacion interrumpida: {exc}", f"[Actualizador BDS] Could not check for an interrupted update: {exc}"), "error")
    task = asyncio.create_task(hardware_metrics_loop())
    # Watchdog opt-in (sin config no actua nunca). Hilo daemon: muere con la GUI.
    try:
        watchdog_service.start()
    except Exception as exc:
        manager.add_log(L(f"[Watchdog] No se pudo iniciar el watchdog: {exc}", f"[Watchdog] Could not start the watchdog: {exc}"), "error")
    # Historial persistente: precarga log_history y registra los sinks
    try:
        history_service.start()
    except Exception as exc:
        manager.add_log(L(f"[Historial] No se pudo inicializar el historial: {exc}", f"[History] Could not initialize history: {exc}"), "error")
    yield
    task.cancel()
    # Esperar la cancelacion del task de metricas evita "Task was destroyed but
    # it is pending" y corrutinas huerfanas en el cierre del loop.
    with contextlib.suppress(asyncio.CancelledError):
        await task
    # El loop muere con este lifespan: dejar manager.loop apuntandolo deja un
    # loop CERRADO como global y convierte cada add_log/update_status posterior
    # (hilos de fondo en la ventana de apagado; tests tras un TestClient) en
    # RuntimeError con corrutina huerfana. _schedule_broadcast tolera None.
    manager.loop = None


def create_app() -> FastAPI:
    """Construye la app: lifespan, estáticos y todos los routers."""
    app = FastAPI(title="ReactBits Minecraft Bedrock Wrapper GUI", lifespan=lifespan)

    @app.middleware("http")
    async def _guard_api_local_only(request, call_next):
        """Guarda temprana para /api/*: cliente local + Origin permitido.

        Corre ANTES del routing y de la validación del body: sin esto, un
        cliente externo a loopback podía recibir un 422 de esquema pydantic
        (p. ej. POST /api/command sin body) y enumerar rutas/campos sin pasar
        por `_ensure_local`/`_check_origin`, que viven dentro de los endpoints.
        Los endpoints conservan sus chequeos (defensa en profundidad) y el
        WebSocket valida en el handshake (aquí no pasa por middleware HTTP).
        """
        if request.url.path.startswith("/api/"):
            try:
                _ensure_local(request.client.host if request.client else "")
                _check_origin(request)
            except HTTPException as exc:
                return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        return await call_next(request)

    DIST_DIR = os.path.join(config.BASE_DIR, "gui_frontend", "dist")
    STATIC_TARGET = DIST_DIR if os.path.exists(DIST_DIR) else config.WEB_DIR

    if not os.path.exists(STATIC_TARGET):
        os.makedirs(STATIC_TARGET)

    if os.path.exists(DIST_DIR):
        app.mount("/assets", StaticFiles(directory=os.path.join(DIST_DIR, "assets")), name="assets")

    app.mount("/static", StaticFiles(directory=config.WEB_DIR), name="static")

    app.include_router(system.router)
    app.include_router(properties.router)
    app.include_router(setup.router)
    app.include_router(actions.router)
    app.include_router(backups.router)
    app.include_router(schedule.router)
    app.include_router(players.router)
    app.include_router(history.router)
    app.include_router(websocket.router)

    return app


app = create_app()


def _puerto_libre(puerto: int, host: str = "127.0.0.1") -> bool:
    """Comprueba si un puerto local está disponible para enlazar.

    Sin SO_REUSEADDR a propósito: uvicorn no lo usa, y en Windows ese flag
    permite a un socket "hijackear" un puerto ya ocupado (falso positivo).
    Si host es 0.0.0.0 comprueba en todas las interfaces. Un host con ":"
    (IPv6 literal, p. ej. "::1") enlaza por AF_INET6: con AF_INET el bind
    falla SIEMPRE (familia sin soporte) y la búsqueda de puerto no
    encontraría jamás uno libre.
    """
    import socket
    bind_host = host if host not in ("", "localhost") else "127.0.0.1"
    family = socket.AF_INET6 if ":" in bind_host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as s:
        try:
            s.bind((bind_host, puerto))
            return True
        except OSError:
            return False


def _resolver_host_gui(allow_lan: bool, gui_host_env) -> str:
    """Host efectivo del entrypoint a partir de GUI_ALLOW_LAN y GUI_HOST.

    - Sin LAN: loopback (o el GUI_HOST explícito, p. ej. una IP concreta).
    - Con LAN: 0.0.0.0 salvo que se pida un host específico no-loopback.
      Pedir LAN dejando loopback es contradictorio: se fuerza la apertura.
    """
    gui_host = (gui_host_env or "").strip()
    if not gui_host:
        return "0.0.0.0" if allow_lan else "127.0.0.1"
    if allow_lan and gui_host in ("127.0.0.1", "localhost"):
        return "0.0.0.0"
    return gui_host


def _url_para_navegador(host: str, puerto: int) -> str:
    """URL http:// lista para el navegador.

    Normaliza loopback/localhost a 127.0.0.1 y CORCHETEA los IPv6 literales
    ('::1' -> 'http://[::1]:8000'): sin corchetes la URL es inválida y
    `webbrowser.open` falla en silencio.
    """
    h = (host or "").strip()
    if h in ("", "localhost", "127.0.0.1"):
        h = "127.0.0.1"
    elif ":" in h and not h.startswith("["):
        h = f"[{h}]"
    return f"http://{h}:{puerto}"


PUERTO_MAX = 65535


def _resolver_puerto(puerto_inicial: int, host: str = "127.0.0.1") -> int:
    """Primer puerto >= puerto_inicial libre para `host`, ACOTADO a 65535.

    Antes el salto de puerto era un `while` sin tope: si nada llegaba a
    enlazar (host que el socket nunca acepta, rango agotado...), el bucle
    giraba infinito imprimiendo avisos — y superado 65535 el bind falla
    siempre. Ahora lanza RuntimeError con un mensaje claro al agotarse.
    """
    puerto = puerto_inicial
    while puerto <= PUERTO_MAX:
        if _puerto_libre(puerto, host):
            return puerto
        print(L(
            f"[AVISO] El puerto {puerto} ya está en uso. Probando el siguiente libre...",
            f"[WARNING] Port {puerto} is already in use. Trying the next free one...",
        ))
        puerto += 1
    raise RuntimeError(L(
        f"No hay puertos libres entre {puerto_inicial} y {PUERTO_MAX} para el host {host}.",
        f"No free ports between {puerto_inicial} and {PUERTO_MAX} for host {host}.",
    ))


if __name__ == "__main__":
    import socket
    import webbrowser

    try:
        puerto = int(os.environ.get("GUI_PORT", "8000"))
        if not (1 <= puerto <= 65535):
            raise ValueError
    except ValueError:
        print("[AVISO] GUI_PORT no es un puerto válido. Usando 8000.")
        puerto = 8000

    # Host / modo LAN opt-in (ver gui_backend/security.py)
    # GUI_ALLOW_LAN=1 abre a 0.0.0.0 y relaja _ensure_local/_is_allowed_origin a IPs privadas.
    # GUI_HOST permite override explícito (p.ej. 0.0.0.0 o 192.168.1.70).
    # Fuente única del parsing de GUI_ALLOW_LAN: security._allow_lan.
    allow_lan = _allow_lan()
    gui_host = _resolver_host_gui(allow_lan, os.environ.get("GUI_HOST"))

    # Si el puerto pedido está ocupado (p. ej. SillyTavern en 8000),
    # saltar al siguiente puerto libre para no chocar con la otra app.
    try:
        puerto = _resolver_puerto(puerto, gui_host)
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        raise SystemExit(1)

    if gui_host == "0.0.0.0":
        # Mostrar tanto loopback como IP de LAN para el móvil
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(2)
            s.connect(("8.8.8.8", 80))
            lan_ip = s.getsockname()[0]
            s.close()
        except Exception:
            lan_ip = "IP_LOCAL"
        url_local = f"http://127.0.0.1:{puerto}"
        url_lan = f"http://{lan_ip}:{puerto}"
        print("=================================================================")
        print("  MINECRAFT BEDROCK WRAPPER GUI - REACTBITS DASHBOARD [MODO LAN]")
        print(f"  Local : {url_local}")
        print(f"  En LAN: {url_lan}  <- abre esta en el movil (misma WiFi)")
        print("  (GUI_ALLOW_LAN=1 activo: permite IPs privadas 192.168/10/172.16)")
        print("=================================================================")
        open_url = url_local
    else:
        url = _url_para_navegador(gui_host, puerto)
        print("=================================================================")
        print("  MINECRAFT BEDROCK WRAPPER GUI - REACTBITS DASHBOARD")
        print(f"  Abriendo en: {url}")
        print("=================================================================")
        open_url = url
    try:
        webbrowser.open(open_url)
    except Exception:
        pass  # sin navegador disponible no es crítico
    try:
        uvicorn.run("server_gui_server:app", host=gui_host, port=puerto, reload=False, log_level="info")
    except OSError:
        print(f"\n[AVISO] El puerto {puerto} se ocupó justo al abrir. Reintentando en el siguiente libre...")
        time.sleep(2)
        # Mismo criterio acotado que el salto inicial: sin esto, un puerto+1
        # también ocupado moriría con traceback en vez de buscar el siguiente.
        try:
            puerto = _resolver_puerto(puerto + 1, gui_host)
        except RuntimeError as exc:
            print(f"[ERROR] {exc}")
            raise SystemExit(1)
        uvicorn.run("server_gui_server:app", host=gui_host, port=puerto, reload=False, log_level="info")
