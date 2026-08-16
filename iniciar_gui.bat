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

:: [1/3] Entorno virtual aislado (.venv) + dependencias.
::        - Las dependencias viven en .venv\, no en el Python global del
::          usuario (no contaminar ni chocar con otras herramientas).
::        - Si el venv falta o queda invalido (p. ej. carpeta movida),
::          se (re)crea una sola vez con el python del PATH.
::        - Si la creacion falla, se avisa y se usa el Python global.
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
"%RUN_PY%" server_gui_server.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Se produjo un error al ejecutar el servidor de la GUI.
    echo         Revisa la consola de arriba para ver el motivo exacto.
)
echo.
pause
