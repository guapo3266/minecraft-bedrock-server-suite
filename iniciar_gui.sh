#!/usr/bin/env bash
# Minecraft Bedrock Wrapper GUI - lanzador Linux/macOS
set -e
cd "$(dirname "$0")"

# Verificar Python 3
if ! command -v python3 >/dev/null 2>&1; then
    echo "[ERROR] Python 3 no encontrado. Instalalo antes."
    exit 1
fi

# Instalar dependencias si faltan (una sola vez)
if ! python3 -c "import fastapi, uvicorn, psutil, requests" >/dev/null 2>&1; then
    echo "[1/3] Instalando dependencias de Python..."
    pip3 install -r requirements.txt
else
    echo "[1/3] Dependencias de Python listas."
fi

if [ ! -f gui_frontend/dist/index.html ]; then
    echo "[2/3] AVISO: dist no encontrado; se usara la GUI clasica de web/ como respaldo."
else
    echo "[2/3] Frontend React listo."
fi

echo "[3/3] Abriendo http://127.0.0.1:8000 ..."
( sleep 2; xdg-open http://127.0.0.1:8000 >/dev/null 2>&1 || open http://127.0.0.1:8000 >/dev/null 2>&1 || true ) &
python3 server_gui_server.py
