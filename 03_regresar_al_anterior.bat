@echo off
setlocal enabledelayedexpansion
title [3/3] REGRESAR AL ANTERIOR - Servidor de Guapo
color 0c

:: ====================================================
::  CONFIGURACION
:: ====================================================
set BASE_DIR=%~dp0
set WORLD_DIR=%BASE_DIR%worlds\Bedrock level
set BACKUP_BASE=%BASE_DIR%..\..\Backups_Minecraft

:: ====================================================
::  HEADER
:: ====================================================
cls
echo.
echo  =====================================================
echo  ^|  [3 de 3] REGRESAR AL ANTERIOR - Srv. de Guapo ^|
echo  =====================================================
echo.

:: ====================================================
::  VERIFICAR QUE EXISTA LA CARPETA DE BACKUPS
:: ====================================================
if not exist "%BACKUP_BASE%" (
    echo  [ERROR] No se encontro la carpeta de backups:
    echo  %BACKUP_BASE%
    echo.
    pause
    exit /b 1
)

:: ====================================================
::  BUSCAR EL BACKUP MAS RECIENTE (numero mas alto)
:: ====================================================
set MAX_NUM=0
set MAX_STR=
for /d %%D in ("%BACKUP_BASE%\backup_???") do (
    set FNAME=%%~nxD
    set NUMSTR=!FNAME:backup_=!
    set /a NUMVAL=1!NUMSTR! - 1000
    if !NUMVAL! GTR !MAX_NUM! (
        set MAX_NUM=!NUMVAL!
        set MAX_STR=!NUMSTR!
    )
)

if "!MAX_STR!"=="" (
    echo  [ERROR] No hay backups disponibles.
    echo  Ejecuta 01_hacer_backup.bat primero.
    echo.
    pause
    exit /b 1
)

set SELECTED_DIR=%BACKUP_BASE%\backup_!MAX_STR!

:: ====================================================
::  MOSTRAR INFO DEL BACKUP MAS RECIENTE
:: ====================================================
echo  Backups encontrados: !MAX_NUM!
echo  Ultimo backup:       backup_!MAX_STR!
echo.

if exist "!SELECTED_DIR!\BACKUP_INFO.txt" (
    echo  Informacion del backup:
    echo  -------------------------------------------------------
    type "!SELECTED_DIR!\BACKUP_INFO.txt"
    echo  -------------------------------------------------------
) else (
    echo  (sin informacion adicional)
)

echo.

:: ====================================================
::  VERIFICAR SI EL SERVIDOR ESTA ENCENDIDO
:: ====================================================
tasklist /FI "IMAGENAME eq bedrock_server.exe" 2>nul | find /I "bedrock_server.exe" >nul
if %ERRORLEVEL%==0 (
    echo  [!] El servidor esta ENCENDIDO.
    echo  [!] Debes apagarlo antes de restaurar.
    echo  [!] Escribe "stop" en la consola del servidor y ejecuta este bat de nuevo.
    echo.
    pause
    exit /b 1
)

echo  El servidor esta APAGADO. Listo para restaurar.
echo.

:: ====================================================
::  CONFIRMAR
:: ====================================================
echo  ATENCION: Se sobreescribira el mundo actual con
echo  el backup numero !MAX_STR! (el mas reciente).
echo.
set CONFIRM=
set /p CONFIRM=  Escribe "SI" para confirmar: 

if /i "!CONFIRM!" NEQ "SI" (
    echo.
    echo  Operacion cancelada.
    pause
    exit /b 0
)

:: ====================================================
::  GUARDAR ESTADO ACTUAL COMO BACKUP ANTES DE RESTAURAR
:: ====================================================
echo.
echo  Guardando estado actual antes de restaurar...

set /a NEXT=!MAX_NUM!+1
if !NEXT! LSS 10   set NEXT_STR=00!NEXT!
if !NEXT! GEQ 10  if !NEXT! LSS 100  set NEXT_STR=0!NEXT!
if !NEXT! GEQ 100 set NEXT_STR=!NEXT!

set AUTO_BACKUP_DEST=%BACKUP_BASE%\backup_!NEXT_STR!
robocopy "%WORLD_DIR%" "!AUTO_BACKUP_DEST!" /E /Z /R:1 /W:1 /NP /NFL /NDL
echo Numero:   !NEXT_STR!>"!AUTO_BACKUP_DEST!\BACKUP_INFO.txt"
echo Nombre:   backup_!NEXT_STR! (auto-antes-de-regresar)>>"!AUTO_BACKUP_DEST!\BACKUP_INFO.txt"
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set DT=%%I
echo Fecha:    !DT:~6,2!/!DT:~4,2!/!DT:~0,4! !DT:~8,2!:!DT:~10,2!>>"!AUTO_BACKUP_DEST!\BACKUP_INFO.txt"
echo  [OK] Estado actual guardado como backup_!NEXT_STR! (seguridad)

:: ====================================================
::  RESTAURAR EL BACKUP MAS RECIENTE (ANTERIOR AL GUARDADO)
:: ====================================================
echo.
echo  Restaurando backup_!MAX_STR!...
echo.

robocopy "!SELECTED_DIR!" "%WORLD_DIR%" /E /IS /IT /R:3 /W:2 /NP /NFL /NDL /PURGE

:: Limpiar archivo de metadata si se copio al mundo
if exist "%WORLD_DIR%\BACKUP_INFO.txt" del "%WORLD_DIR%\BACKUP_INFO.txt" >nul

if %ERRORLEVEL% LEQ 7 (
    echo.
    echo  =====================================================
    echo  [OK] REGRESADO AL BACKUP #!MAX_STR! EXITOSAMENTE
    echo  =====================================================
    echo  Puedes iniciar el servidor con iniciar_servidor.bat
) else (
    echo.
    echo  [ERROR] Fallo la restauracion. Codigo: %ERRORLEVEL%
)

echo.
pause
endlocal



