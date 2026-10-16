@echo off
setlocal
cd /d "%~dp0"
if not exist "data\suite_updates\recovery\journal.json" exit /b 0
if not exist "data\suite_updates\recovery\helper\runtime\python.exe" (
  echo [ERROR] Falta el runtime de recuperacion. No se modificaron los resguardos.
  exit /b 1
)
"data\suite_updates\recovery\helper\runtime\python.exe" -B "data\suite_updates\recovery\helper\suite_updater.py" --recover "%~dp0."
exit /b %ERRORLEVEL%
