@echo off
chcp 65001 >nul
title Minecraft Bedrock Wrapper - ReactBits Dashboard [MODO LAN]
color 0A
:: Trabajar SIEMPRE sobre la carpeta de este .bat
cd /d "%~dp0"
cls
echo ================================================================
echo   MINECRAFT BEDROCK WRAPPER - MODO LAN (movil en misma WiFi)
echo ================================================================
echo.

:: [0/3] Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] No se encontro Python 3.
    pause
    exit /b 1
)

:: Activar modo LAN: la GUI escuchara en 0.0.0.0 y permitira IPs privadas
set GUI_ALLOW_LAN=1
:: Opcional: fija puerto (si lo cambias, abre ese puerto en el firewall)
if "%GUI_PORT%"=="" set GUI_PORT=8000

echo [LAN] GUI_ALLOW_LAN=1 - la GUI sera accesible desde la red local
echo       Puerto: %GUI_PORT%
echo       URL local: http://127.0.0.1:%GUI_PORT%
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
    for /f "tokens=1" %%b in ("%%a") do set LAN_IP=%%b
)
if defined LAN_IP echo       URL en movil: http://%LAN_IP%:%GUI_PORT%  (misma WiFi)
echo.
echo [LAN] Intentando abrir puerto %GUI_PORT% en Firewall de Windows...
netsh advfirewall firewall show rule name="Minecraft GUI LAN" >nul 2>&1
if errorlevel 1 (
    netsh advfirewall firewall add rule name="Minecraft GUI LAN" dir=in action=allow protocol=TCP localport=%GUI_PORT% >nul 2>&1
    if not errorlevel 1 (
        echo [LAN] Regla de firewall creada: permite TCP %GUI_PORT% (solo red privada)
    ) else (
        echo [AVISO] No se pudo crear regla de firewall (ejecuta como Administrador si falla el acceso desde el movil).
    )
) else (
    echo [LAN] Regla de firewall ya existe.
)
echo.

:: Reusar logica de iniciar_gui.bat para venv
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
timeout /t 2 /nobreak >nul 2>&1
goto :check_venm
:venv_recreate
echo [1/3] .venv invalido: se recreara...
rmdir /s /q "%~dp0.venv"
:venv_create
if not exist "%VENV_PY%" (
    echo [1/3] Creando entorno virtual .venv...
    python -m venv "%~dp0.venv" >nul 2>&1
)
:venv_ready
if exist "%VENV_PY%" (
    set "RUN_PY=%VENV_PY%"
) else (
    echo [AVISO] No se pudo crear .venv: se usara el Python global.
)

"%RUN_PY%" -c "import fastapi, uvicorn, websockets, psutil, requests" >nul 2>&1
if errorlevel 1 (
    echo [1/3] Instalando dependencias...
    "%RUN_PY%" -m pip install -r requirements.txt
    "%RUN_PY%" -c "import fastapi, uvicorn, websockets, psutil, requests" >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Dependencias no se pudieron instalar.
        call :bootstrap_unlock
        pause
        exit /b 1
    )
) else (
    echo [1/3] Dependencias listas.
)

call :bootstrap_unlock

if not exist "gui_frontend\dist\index.html" (
    echo [2/3] dist no encontrado: compilando frontend...
    cd gui_frontend
    call npm run build
    cd ..
) else (
    echo [2/3] Frontend React listo.
)

echo.
echo [3/3] Iniciando servidor FastAPI en modo LAN (0.0.0.0:%GUI_PORT%)...
echo       Abre en tu movil: http://%LAN_IP%:%GUI_PORT%
echo       (Debe estar en la misma WiFi que este PC)
echo.
"%RUN_PY%" server_gui_server.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Error al ejecutar la GUI.
)
echo.
pause
exit /b 0

:bootstrap_lock
2>nul md "%LOCK_DIR%" && goto :eof
echo [1/3] Otro arranque esta preparando el entorno; esperando...
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
echo [AVISO] Lock abandonado; se reutiliza.
rd /s /q "%LOCK_DIR%" >nul 2>&1
2>nul md "%LOCK_DIR%"
goto :eof

:bootstrap_unlock
rd /s /q "%LOCK_DIR%" >nul 2>&1
goto :eof
