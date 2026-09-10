"""Router WebSocket /ws (protocolo: in command/ping/set_lang; out init/log/status/pong)."""

import json

from fastapi import APIRouter, WebSocket

from console_lang import L, set_lang as _set_lang
from gui_backend.security import _get_request_port, _is_allowed_client_host, _is_allowed_origin
from gui_backend.state import manager, build_public_status

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # S1: solo conexiones desde la propia máquina (con GUI_ALLOW_LAN=1 permite LAN privada)
    if websocket.client is None or not _is_allowed_client_host(websocket.client.host):
        await websocket.close(code=1008)
        return
    # S3: rechazar handshakes de navegador con Origin externo o puerto incorrecto
    # (anti-CSRF). Puerto esperado por la MISMA fuente unica que los endpoints
    # HTTP (anti-drift: soporta Host IPv6 "[::1]:8000", Host malformado y cae
    # al puerto por defecto del esquema ws/wss).
    if not _is_allowed_origin(
        websocket.headers.get("origin"),
        expected_port=_get_request_port(websocket),
    ):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    manager.active_websockets.add(websocket)

    # Idioma de la consola: query param (primer arranque) o mensaje set_lang
    # (cambios en vivo). Fija WRAPPER_LANG, que usan L() y el wrapper.
    _set_lang(websocket.query_params.get("lang"))

    try:
        # El init va DENTRO de la sesion registrada: si el cliente muere entre
        # accept() y el primer send, o construir el status lanza (p. ej. primer
        # muestreo de psutil sin cache), el finally debe sacarlo del registro.
        # Fuera del try, la entrada muerta persistia hasta el siguiente
        # broadcast (reintento de envio garantizado contra un socket muerto).
        with manager.lock:
            logs = list(manager.log_history)
            players = list(manager.players_online)

        await websocket.send_json({
            "type": "init",
            "logs": logs,
            "status": build_public_status(manager, players)
        })

        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "command":
                    cmd = msg.get("command", "").strip()
                    if not cmd:
                        continue
                    wrapper_alive = bool(
                        manager.wrapper_process
                        and manager.wrapper_process.poll() is None
                    )
                    if not manager.is_running or not wrapper_alive:
                        # Mismo feedback que el POST /api/command: el usuario ve
                        # por que su comando no hace nada (antes se descartaba
                        # en silencio y la consola parecia rota).
                        manager.add_log(f"> {cmd}", "command")
                        manager.add_log(L(
                            "[SISTEMA] El servidor de Minecraft está APAGADO. Presiona '▶ Iniciar Servidor' primero.",
                            "[SISTEMA] The Minecraft server is OFF. Press '▶ Start Server' first.",
                        ), "error")
                        continue
                    # 'stop' en consola apaga el wrapper entero: es un stop
                    # deliberado y debe marcar stop_requested (igual que
                    # /api/command) o el watchdog lo tomara por crash y
                    # re-lanzara el servidor que el usuario acaba de parar.
                    # Se compara por LINEA: "list\nstop" tambien apaga.
                    if "stop" in {l.strip().lower() for l in cmd.splitlines()}:
                        manager.stop_requested = True
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
    finally:
        # Cualquier salida (disconnect u otro error de transporte) debe sacar
        # el socket del registro; si no, broadcast reintenta contra un socket
        # muerto en cada mensaje.
        manager.active_websockets.discard(websocket)
