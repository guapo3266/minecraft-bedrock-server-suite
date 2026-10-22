@echo off
:: Variables locales (RUN_PY, WRAPPER_LANG...): sin setlocal quedaban vivas en
:: la ventana de cmd que lanzo este .bat (2026-10-21).
setlocal
cd /d "%~dp0"
if exist "data\suite_updates\recovery\journal.json" (
    call "%~dp0Recuperar_suite.bat" --sin-pausa
    if errorlevel 1 goto :recuperacion_fallida
)
title Minecraft Bedrock Server Suite
color 0a

echo.
echo  ==========================================
echo  ^|                                        ^|
echo  ^|   MINECRAFT BEDROCK SERVER SUITE       ^|
echo  ^|                                        ^|
echo  ==========================================
echo.
echo  Valores por defecto de BDS (los reales los fija server.properties):
echo  Puerto: 19132 (UDP) / Modo: Survival / Dificultad: Normal
echo  Max Jugadores: 20
echo  Consulta server.properties para la configuracion de tu servidor.
echo.
echo  Para detener el servidor escribe: stop
echo  ==========================================
echo.

:: Ejecutar el wrapper de ESTA instalacion (la carpeta del propio .bat),
:: no una ruta hardcodeada a otra instalacion.
cd /d "%~dp0"

:: El .bat habla espanol: el wrapper arranca en espanol salvo que el usuario
:: ya haya fijado otro idioma con WRAPPER_LANG.
if not defined WRAPPER_LANG set "WRAPPER_LANG=es"

:: ZIP de la Release: Python incluido en runtime\ (sin .venv ni pip). Va al
:: mismo primer arranque que el resto: antes esta rama lanzaba el wrapper
:: directamente y, en un ZIP nuevo sin BDS, terminaba intentando lanzar un
:: ejecutable inexistente en lugar de ofrecer descargarlo (2026-10-20).
:: -B: no escribir __pycache__ en el codigo que gestiona el actualizador.
set "PY_FLAGS="
if exist "%~dp0runtime\python.exe" (
    set "RUN_PY=%~dp0runtime\python.exe"
    set "PY_FLAGS=-B"
    goto :first_run
)

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
::        El bootstrap va serializado con un lock-dir atomico (md falla si
::        ya existe): dos lanzamientos casi simultaneos (doble doble-clic)
::        antes podian pisarse — un rmdir del .venv a medias crear del otro
::        o dos pip install en paralelo sobre el mismo venv lo dejaban roto.
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

:first_run
:: [2/3] Si falta bedrock_server.exe, preguntar y descargarlo desde Mojang
"%RUN_PY%" %PY_FLAGS% tools\bds_first_run.py
if errorlevel 2 (
    echo.
    echo [INFO] Instalacion de BDS cancelada ^(sin respuesta o "no"^). Vuelve a
    echo         ejecutar este .bat cuando quieras instalarla.
    pause
    exit /b 2
)
if errorlevel 1 (
    echo.
    echo [ERROR] No se pudo preparar bedrock_server.exe. Revisa los mensajes de arriba.
    pause
    exit /b 1
)

:: [3/3] Arrancar el wrapper
"%RUN_PY%" %PY_FLAGS% server_wrapper.py

echo.
echo  El servidor se ha detenido.
pause
exit /b 0

:recuperacion_fallida
echo.
echo [ERROR] No se pudo completar la recuperacion de una actualizacion de la suite.
echo         Lee el mensaje de arriba; puedes reintentarla con Recuperar_suite.bat.
pause
exit /b 1

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
