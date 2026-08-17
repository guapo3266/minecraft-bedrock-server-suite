"""Router WebSocket /ws (protocolo: in command/ping/set_lang; out init/log/status/pong)."""

import json

from fastapi import APIRouter, WebSocket

from console_lang import set_lang as _set_lang
from gui_backend.security import _is_allowed_origin
from gui_backend.state import manager, build_public_status

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # S1: solo conexiones desde la propia máquina
    if websocket.client is None or websocket.client.host not in ("127.0.0.1", "::1"):
        await websocket.close(code=1008)
        return
    # S3: rechazar handshakes de navegador con Origin externo o puerto incorrecto (anti-CSRF)
    expected_port = websocket.url.port
    if expected_port is None:
        host_hdr = websocket.headers.get("host", "")
        if ":" in host_hdr:
            try:
                expected_port = int(host_hdr.split(":")[-1])
            except ValueError:
                expected_port = None
        else:
            expected_port = 80 if websocket.url.scheme in ("http", "ws") else 443
    if not _is_allowed_origin(websocket.headers.get("origin"), expected_port=expected_port):
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
        "status": build_public_status(manager, players)
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
    finally:
        # Cualquier salida (disconnect u otro error de transporte) debe sacar
        # el socket del registro; si no, broadcast reintenta contra un socket
        # muerto en cada mensaje.
        manager.active_websockets.discard(websocket)
