@echo off
setlocal
cd /d "%~dp0"
if not exist "data\suite_updates\recovery\journal.json" exit /b 0
rem Los lanzadores pasan --sin-pausa y muestran su propio aviso.
set "SIN_PAUSA="
if /i "%~1"=="--sin-pausa" set "SIN_PAUSA=1"
set "HELPER_PY=data\suite_updates\recovery\helper\runtime\python.exe"
if not exist "%HELPER_PY%" (
  echo [ERROR] Falta el runtime de recuperacion. No se modificaron los resguardos.
  goto :fallo
)
rem Una actualizacion terminada o revertida no deja nada que recuperar. Se mira
rem aqui y no solo en el auxiliar: el auxiliar se copio de la version que hizo
rem la actualizacion, y el de 2.2.0 o anterior fallaba si la carpeta de la
rem instalacion se habia movido o copiado (2026-10-21).
"%HELPER_PY%" -B -c "import json,sys; sys.exit(0 if json.load(open(sys.argv[1], encoding='utf-8')).get('phase') in ('complete', 'rolled_back') else 3)" "data\suite_updates\recovery\journal.json" >nul 2>&1
if not errorlevel 1 exit /b 0
"%HELPER_PY%" -B "data\suite_updates\recovery\helper\suite_updater.py" --recover "%~dp0."
if errorlevel 1 goto :fallo
exit /b 0

:fallo
echo.
echo [ERROR] No se pudo recuperar la actualizacion de la suite. Lee el mensaje de arriba.
if not defined SIN_PAUSA pause
exit /b 1
