# Contrato API HTTP / WebSocket — GUI Bedrock Wrapper

Línea base capturada antes del refactor (`server_gui_server.py`, commit `af71b99`).
Durante el refactor **no pueden cambiar** rutas, códigos HTTP, textos de respuesta ni el protocolo WS.
Este documento es la referencia para detectar regresiones de comportamiento.

## Modelo de seguridad (todos los endpoints)

| Guard | Dónde se aplica | Resultado al fallar |
|---|---|---|
| `_ensure_local` (IP loopback: `127.0.0.1`, `::1`) | Todos los endpoints REST y el WS | REST: `403 {"detail": "Acceso denegado: solo conexiones locales"}`; WS: `close(1008)` |
| `_check_origin` (header `Origin` local o ausente; anti-CSRF) | Solo endpoints de escritura y el WS | `403 {"detail": "Acceso denegado: origen no permitido"}`; WS: `close(1008)` |

Endpoint solo con `_ensure_local` (lectura): `GET /api/status`, `GET /api/server_properties`, `GET /api/setup_status`, `GET /api/check_update`, `GET /api/backups`, `GET /`, `GET /favicon.svg`.
Endpoint con `_ensure_local` + `_check_origin` (escritura): `POST /api/command`, `POST /api/server_properties`, `POST /api/setup/install_bds`, `POST /api/setup/complete`, `POST /api/action/{action_name}`, `POST /api/restore`, `GET /api/backups/{filename}/download`, `POST /api/backups/{filename}/delete`, `POST /api/backups/{filename}/verify`, `WS /ws`.

## Estado público (payload `status` — compartido por `/api/status`, WS `init` y WS `status`)

```json
{
  "running": false,
  "players": ["NombreJugador"],
  "player_count": 0,
  "last_backup": "HH:MM:SS | Ninguno",
  "backup_in_progress": false,
  "update_in_progress": false,
  "uptime": 0,
  "hardware": {
    "ram_mb": 0.0, "ram_pct": 0.0, "cpu_pct": 0.0,
    "total_ram_gb": 0.0, "system_used_gb": 0.0, "system_available_gb": 0.0,
    "system_used_pct": 0.0, "disk_total_gb": 0.0, "disk_free_gb": 0.0, "disk_used_pct": 0.0
  }
}
```

## Entrada de log (WS `log` y WS `init`)

```json
{"id": 1, "time": "HH:MM:SS", "text": "...", "type": "info|command|error|system|backup"}
```

## Endpoints REST

### `GET /favicon.svg`
- 200: `FileResponse` de `gui_frontend/public/favicon.svg`; si no existe, `web/index.html`.

### `GET /`
- 200: `index.html` de `gui_frontend/dist` (si existe), si no `web/index.html`, si no HTML literal `"<h1>Cargando GUI...</h1>"`.

### `GET /api/status`
- 200: payload `status` (arriba).

### `POST /api/command`
- Body: `{"command": "<str>"}`.
- 200 `{"status": "ok"}` — vacío o enviado.
- 200 `{"status": "ok", "command": "<cmd>"}` — enviado al servidor.
- 200 `{"status": "offline", "message": "El servidor no está en ejecución"}` — servidor apagado (además añade 2 entradas de log).
- 200 `{"status": "error", "message": "<str>"}` — excepción al escribir stdin (añade log de error).

### `GET /api/server_properties`
- 200: `{"fields": {clave: valor}, "server_running": <bool>}` (solo las claves de `PROPS_FIELDS`).

### `POST /api/server_properties`
- Body: `{"values": {"clave": "<str>", ...}}`.
- 400 `"Cuerpo JSON invalido"` / `"No hay campos para guardar"` / `"Valores deben ser texto"` / detalle de validación por campo.
- 200: `{"status": "ok", "written": [<claves>], "restart_required": true}` + log de sistema.

### `GET /api/setup_status`
- 200: `{"required": <bool>, "bds_installed": <bool>}`.

### `POST /api/setup/install_bds`
- 409 `"El servidor esta en ejecucion; detenlo antes de instalar"` — con servidor corriendo.
- 200 `{"status": "busy", "message": "Operación en curso (actualización/restauración/backup)"}` — `op_lock` ocupado.
- 200 `{"status": "install_dispatched"}` — hilo lanzado (logs `[Setup]`).

### `POST /api/setup/complete`
- 409 `"Instala BDS antes de finalizar el setup"` — sin `bedrock_server.exe`.
- 500 `"No se pudo escribir el marcador de setup: <e>"` — error de escritura.
- 200 `{"status": "ok"}` + log de sistema.

### `POST /api/action/{action_name}`  (acción en minúsculas)

| acción | Respuestas 200 | Respuestas de error |
|---|---|---|
| `start` | `{"status": "starting"}` / `{"status": "already_running"}` / `{"status": "busy", "message": "Operación en curso (restauración/actualización)"}` / `{"status": "error", "message": "<e>"}` | — |
| `stop` | `{"status": "stopping"}` / `{"status": "not_running"}` | — |
| `restart` | `{"status": "restarting"}` (progreso solo por logs) | — |
| `backup` | `{"status": "hot_backup_dispatched"}` (caliente) / `{"status": "backup_dispatched"}` (frío) / `{"status": "busy", "message": "Ya hay un backup en curso"}` | 500 `"Error al iniciar backup: <e>"` (caliente) |
| `update_bds` | `{"status": "update_dispatched"}` / `{"status": "already_updating"}` | — |
| otra | — | 400 `"Acción no válida"` |

### `GET /api/check_update`
- 200: `{"current_version": <str|null>, "latest_version": <str|null>, "download_url": <str|null>, "has_update": <bool|null>, "unavailable": <bool>, "reason": <str|null>}`.

### `GET /api/backups`
- 200: `{"backups": [{"filename": "<str>", "size_mb": <float>, "date": "YYYY-MM-DD HH:MM:SS"}, ...]}` ordenado por mtime desc.
- 200 `{"backups": []}` si no existe `auto_backup.BACKUP_DIR`.
- Excluye nombres que contengan `_CORRUPTO` o `_EXCEDIDO`.

### `POST /api/restore`
- Body: `{"filename": "<str>"}`.
- 400 `"Cuerpo JSON invalido"` / `"Nombre de backup invalido"` (basename != nombre).
- 409 `"Debes apagar el servidor antes de reestablecer un backup"` / `"El servidor se encendió durante la restauración; operación cancelada"` (recheck bajo `op_lock`).
- 404: `FileNotFoundError` (texto del error).
- 500: error genérico.
- 200: `{"status": "ok", "backup": "<filename>"}` + log.

### `GET /api/backups/{filename}/download`
- 400 `"Nombre de backup invalido"`; 404 `"Backup no encontrado"`.
- 200: `FileResponse` ZIP (`media_type="application/zip"`).

### `POST /api/backups/{filename}/delete`
- 400 `"Nombre de backup invalido"`; 404 `"Backup no encontrado"`.
- 409 `"Hay un backup en curso; espera a que termine antes de eliminar"` — si `backup_in_progress`.
- 500: error OSError.
- 200: `{"status": "ok", "backup": "<filename>"}` + log.

### `POST /api/backups/{filename}/verify`
- 400 `"Nombre de backup invalido"`; 404 `"Backup no encontrado"`; 500 error genérico.
- 200 `{"status": "ok", "filename": "<filename>"}` — CRC correcto.
- 200 `{"status": "corrupt", "filename": "<filename>", "entry": "<str>"}` — `testzip` o `BadZipFile` (no es error HTTP).

## WebSocket `/ws`

Handshake:
- `close(1008)` si `client.host` no es `127.0.0.1`/`::1` o si `Origin` no es local.
- Query param `?lang=es|en` fija el idioma al conectar.

Servidor → cliente:

| `type` | Payload | Cuándo |
|---|---|---|
| `init` | `{"type":"init","logs":[...],"status":{...}}` | Al conectar (snapshot de historial + estado) |
| `log` | `{"type":"log","data":{entrada}}` | Cada nueva línea del servidor/log |
| `status` | `{"type":"status","data":{...}}` | Cada ~2s (bucle `hardware_metrics_loop`) |
| `pong` | `{"type":"pong"}` | Respuesta a `ping` |

Cliente → servidor:

| `type` | Payload | Efecto |
|---|---|---|
| `command` | `{"type":"command","command":"<str>"}` | Escribe en stdin del wrapper bajo `stdin_lock` (solo si corriendo) + log `> cmd` |
| `ping` | `{"type":"ping"}` | Latencia del frontend |
| `set_lang` | `{"type":"set_lang","lang":"es|en"}` | Cambia `WRAPPER_LANG` en vivo |

## Invariantes de concurrencia (protegidas por tests, no modificar)

- `manager.lock`: mutaciones/lecturas de `players_online` y `log_history`.
- `manager.stdin_lock`: TODAS las escrituras a `wrapper_process.stdin` (API command, WS command, stop/restart/backup/update) — 6 sitios.
- `manager.op_lock`: exclusión mutua de start/restore/update/backup frío/install.
- Eventos G8: `server_stopped_event` (BDS muerto) ≠ `wrapper_exit_event` (wrapper terminado, backup final incluido).
- `SERVER_STOP_TIMEOUT_SEC=75`, `WRAPPER_EXIT_TIMEOUT_SEC=450`.
- `manager` es un singleton global; nunca crear instancias por petición.

## Arranque (no modificar)

- `iniciar_gui.bat` → `python server_gui_server.py`.
- Puerto `GUI_PORT` (default 8000), salto al siguiente libre (`_puerto_libre`).
- `uvicorn.run("server_gui_server:app", host="127.0.0.1", ...)`.
- Estáticos: `/assets` desde `gui_frontend/dist/assets` (si existe) y `/static` desde `web/`.
- `lifespan`: `manager.loop`, `recover_interrupted_updates()` y bucle de métricas (2s).
