@echo off
chcp 65001 >nul
title Minecraft Bedrock Wrapper - ReactBits Dashboard
color 0A
:: Trabajar SIEMPRE sobre la carpeta de este .bat (rutas relativas a el)
cd /d "%~dp0"
:: Modelo de LM Studio para el asistente IA (ai_assistant.py: LMSTUDIO_MODEL).
:: Si ya viene definido en el entorno, se respeta el valor existente.
if not defined LMSTUDIO_MODEL set "LMSTUDIO_MODEL=qwen3-minecraft-v3"
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
::        - El bootstrap va serializado con un lock-dir atomico (md falla si
::          ya existe): dos lanzamientos casi simultaneos (doble doble-clic)
::          antes podian pisarse — un rmdir del .venv a medias crear del otro
::          o dos pip install en paralelo sobre el mismo venv lo dejaban roto.
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "RUN_PY=python"
set "LOCK_DIR=%~dp0.venv_bootstrap.lock"

call :bootstrap_lock

if not exist "%VENV_PY%" goto :venv_create
set /a VENV_TRIES=0
:check_venm
"%VENV_PY%" --version >nul 2>&1
if not errorlevel 1 goto :venv_ready
set /a VENV_TRIES+=1
if %VENV_TRIES% GEQ 8 goto :venv_recreate
rem puede haber otra instancia terminando de crearlo: no borrar debajo
timeout /t 2 /nobreak >nul 2>&1
goto :check_venm
:venv_recreate
echo [1/3] .venv invalido: se recreara...
rmdir /s /q "%~dp0.venv"
:venv_create
if not exist "%VENV_PY%" (
    echo [1/3] Creando entorno virtual .venv - solo la primera vez...
    python -m venv "%~dp0.venv" >nul 2>&1
)
:venv_ready
if exist "%VENV_PY%" (
    set "RUN_PY=%VENV_PY%"
) else (
    echo [AVISO] No se pudo crear .venv: se usara el Python global.
)

:: Dependencias: siempre via "python -m pip" (un "pip" desnudo apuntaria
:: al Python global aunque RUN_PY sea el del venv).
:: Refresh condicional: la huella (SHA256) de requirements.txt se guarda en
:: .venv\requirements.sha al instalar; si difiere, requirements.txt ha cambiado
:: y un .venv viejo se actualiza (antes solo se comprobaban los imports y el
:: venv nunca se refrescaba). Sin --upgrade: se respetan los topes de version.
del "%~dp0.venv\requirements.sha.tmp" >nul 2>&1
set "REQ_SHA_FILE=%~dp0.venv\requirements.sha"
set "REQ_SHA_TMP=%~dp0.venv\requirements.sha.tmp"
set "REQ_CAMBIO="
if exist "%VENV_PY%" "%RUN_PY%" -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "%~dp0requirements.txt" > "%REQ_SHA_TMP%" 2>nul
if exist "%REQ_SHA_TMP%" (
    if exist "%REQ_SHA_FILE%" (
        fc /b "%REQ_SHA_FILE%" "%REQ_SHA_TMP%" >nul 2>&1
        if errorlevel 1 set "REQ_CAMBIO=1"
    ) else (
        set "REQ_CAMBIO=1"
    )
)
"%RUN_PY%" -c "import fastapi, uvicorn, websockets, psutil, requests" >nul 2>&1
if errorlevel 1 set "REQ_CAMBIO=1"
if defined REQ_CAMBIO (
    echo [1/3] Instalando dependencias de Python en el entorno...
    "%RUN_PY%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [AVISO] pip no pudo instalar del todo las dependencias; se comprobara el resultado.
    ) else (
        copy /y "%REQ_SHA_TMP%" "%REQ_SHA_FILE%" >nul 2>&1
    )
    "%RUN_PY%" -c "import fastapi, uvicorn, websockets, psutil, requests" >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Las dependencias no se pudieron instalar.
        echo         Revisa tu conexion de red y vuelve a intentarlo.
        call :bootstrap_unlock
        pause
        exit /b 1
    )
) else (
    echo [1/3] Dependencias de Python listas.
)
del "%REQ_SHA_TMP%" >nul 2>&1

call :bootstrap_unlock

:: [2/3] Frontend compilado: NO requiere Node.js (el dist viaja en el repo).
::        Solo se compila si falta (para desarrolladores con Node instalado).
if not exist "gui_frontend\dist\index.html" (
    echo [2/3] dist no encontrado: compilando frontend - requiere Node.js...
    cd gui_frontend
    if errorlevel 1 (
        echo [ERROR] No se pudo entrar en gui_frontend.
        pause
        exit /b 1
    )
    call npm run build
    cd /d "%~dp0"
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
exit /b 0

:bootstrap_lock
2>nul md "%LOCK_DIR%" && goto :eof
echo [1/3] Otro arranque esta preparando el entorno; esperando hasta 120s...
set /a LOCK_WAIT=0
:wait_lock
if not exist "%LOCK_DIR%" (
    2>nul md "%LOCK_DIR%" && goto :eof
)
if %LOCK_WAIT% GEQ 120 goto :steal_lock
timeout /t 2 /nobreak >nul 2>&1
set /a LOCK_WAIT+=2
goto :wait_lock
:steal_lock
echo [AVISO] El lock de bootstrap parecia abandonado; se reutiliza.
rd /s /q "%LOCK_DIR%" >nul 2>&1
2>nul md "%LOCK_DIR%"
goto :eof

:bootstrap_unlock
rd /s /q "%LOCK_DIR%" >nul 2>&1
goto :eof
