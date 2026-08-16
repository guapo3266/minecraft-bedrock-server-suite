@echo off
title Minecraft Bedrock Server Suite
color 0a

echo.
echo  ==========================================
echo  ^|                                        ^|
echo  ^|   MINECRAFT BEDROCK SERVER SUITE       ^|
echo  ^|                                        ^|
echo  ==========================================
echo.
echo  Puerto: 19132 (UDP)
echo  Modo: Survival
echo  Dificultad: Normal
echo  Max Jugadores: 20
echo.
echo  Para detener el servidor escribe: stop
echo  ==========================================
echo.

:: Ejecutar el wrapper de ESTA instalacion (la carpeta del propio .bat),
:: no una ruta hardcodeada a otra instalacion.
cd /d "%~dp0"

:: [0/3] Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] No se encontro Python 3.
    echo         Descargalo en https://www.python.org/downloads/
    echo         IMPORTANTE: marca la casilla "Add Python to PATH".
    pause
    exit /b 1
)

:: [1/3] Entorno virtual aislado (.venv) + dependencias (mismo bloque que
::        iniciar_gui.bat). Necesario aqui porque tools\bds_first_run.py
::        importa requests a traves de gui_backend.services.bds_update:
::        sin esto, una maquina virgen moria con ModuleNotFoundError antes
::        de arrancar. Las dependencias viven en .venv\, no en el Python
::        global del usuario; si la creacion falla, se usa el global.
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "RUN_PY=python"

if exist "%VENV_PY%" (
    "%VENV_PY%" --version >nul 2>&1 || rmdir /s /q "%~dp0.venv"
)

if not exist "%VENV_PY%" (
    echo [1/3] Creando entorno virtual .venv - solo la primera vez...
    python -m venv "%~dp0.venv" >nul 2>&1
)

if exist "%VENV_PY%" (
    set "RUN_PY=%VENV_PY%"
) else (
    echo [AVISO] No se pudo crear .venv: se usara el Python global.
)

:: Dependencias: siempre via "python -m pip" (un "pip" desnudo apuntaria
:: al Python global aunque RUN_PY sea el del venv).
"%RUN_PY%" -c "import fastapi, uvicorn, websockets, psutil, requests" >nul 2>&1
if errorlevel 1 (
    echo [1/3] Instalando dependencias de Python en el entorno...
    "%RUN_PY%" -m pip install -r requirements.txt
    "%RUN_PY%" -c "import fastapi, uvicorn, websockets, psutil, requests" >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Las dependencias no se pudieron instalar.
        echo         Revisa tu conexion de red y vuelve a intentarlo.
        pause
        exit /b 1
    )
) else (
    echo [1/3] Dependencias de Python listas.
)

:: [2/3] Si falta bedrock_server.exe, preguntar y descargarlo desde Mojang
"%RUN_PY%" tools\bds_first_run.py
if errorlevel 2 (
    exit /b 2
)
if errorlevel 1 (
    echo.
    echo [ERROR] No se pudo preparar bedrock_server.exe. Revisa los mensajes de arriba.
    pause
    exit /b 1
)

:: [3/3] Arrancar el wrapper
"%RUN_PY%" server_wrapper.py

echo.
echo  El servidor se ha detenido.
pause
