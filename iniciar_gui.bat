@echo off
chcp 65001 >nul
title Minecraft Bedrock Wrapper - ReactBits Dashboard
color 0A
:: Trabajar SIEMPRE sobre la carpeta de este .bat (rutas relativas a el)
cd /d "%~dp0"
cls
echo ================================================================
echo   MINECRAFT BEDROCK WRAPPER - REACTBITS REACT DASHBOARD
echo ================================================================
echo.

:: [0/3] Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] No se encontro Python 3.
    echo         Descargalo en https://www.python.org/downloads/
    echo         IMPORTANTE: marca la casilla "Add Python to PATH".
    pause
    exit /b 1
)

:: [1/3] Instalar dependencias de Python si faltan (una sola vez)
python -c "import fastapi, uvicorn, psutil, requests" >nul 2>&1
if errorlevel 1 (
    echo [1/3] Instalando dependencias de Python...
    pip install -r requirements.txt
) else (
    echo [1/3] Dependencias de Python listas.
)

:: [2/3] Frontend compilado: NO requiere Node.js (el dist viaja en el repo).
::        Solo se compila si falta (para desarrolladores con Node instalado).
if not exist "gui_frontend\dist\index.html" (
    echo [2/3] dist no encontrado: compilando frontend - requiere Node.js...
    cd gui_frontend
    call npm run build
    cd ..
) else (
    echo [2/3] Frontend React de produccion listo.
)

:: [3/3] Servidor
echo.
echo [3/3] Iniciando servidor FastAPI + WebSockets...
echo Si el puerto 8000 esta ocupado (p. ej. SillyTavern), la GUI usara
echo automaticamente el siguiente puerto libre y abrira el navegador ahi.
echo Para forzar un puerto fijo: set GUI_PORT=8001  antes de ejecutar.
echo.
python server_gui_server.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Se produjo un error al ejecutar el servidor de la GUI.
    echo         Revisa la consola de arriba para ver el motivo exacto.
)
echo.
pause
