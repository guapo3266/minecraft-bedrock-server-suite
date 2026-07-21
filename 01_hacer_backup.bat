@echo off
setlocal enabledelayedexpansion
title [1/3] HACER BACKUP - Servidor de Guapo
color 0b

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
echo  ^|  [1 de 3] HACER BACKUP - Servidor de Guapo     ^|
echo  =====================================================
echo.

:: ====================================================
::  CREAR CARPETA DE BACKUPS SI NO EXISTE
:: ====================================================
if not exist "%BACKUP_BASE%" mkdir "%BACKUP_BASE%"

:: ====================================================
::  VERIFICAR QUE EL MUNDO EXISTE
:: ====================================================
if not exist "%WORLD_DIR%" (
    echo  [ERROR] No se encontro la carpeta del mundo:
    echo  %WORLD_DIR%
    echo.
    pause
    exit /b 1
)

:: ====================================================
::  BUSCAR EL NUMERO MAS ALTO DE BACKUP EXISTENTE
:: ====================================================
set MAX_NUM=0
for /d %%D in ("%BACKUP_BASE%\backup_???") do (
    set FNAME=%%~nxD
    set NUMSTR=!FNAME:backup_=!
    set /a NUMVAL=1!NUMSTR! - 1000
    if !NUMVAL! GTR !MAX_NUM! set MAX_NUM=!NUMVAL!
)

:: ====================================================
::  CALCULAR SIGUIENTE NUMERO Y APLICAR CEROS
:: ====================================================
set /a NEXT=!MAX_NUM!+1
if !NEXT! LSS 10   set NEXT_STR=00!NEXT!
if !NEXT! GEQ 10  if !NEXT! LSS 100  set NEXT_STR=0!NEXT!
if !NEXT! GEQ 100 set NEXT_STR=!NEXT!

set BACKUP_NAME=backup_!NEXT_STR!
set BACKUP_DEST=%BACKUP_BASE%\!BACKUP_NAME!

:: ====================================================
::  DETECTAR ESTADO DEL SERVIDOR
:: ====================================================
tasklist /FI "IMAGENAME eq bedrock_server.exe" 2>nul | find /I "bedrock_server.exe" >nul
if %ERRORLEVEL%==0 (
    set ESTADO=ENCENDIDO
    echo  [!] Servidor ENCENDIDO - se hara backup en caliente.
) else (
    set ESTADO=APAGADO
    echo  [OK] Servidor APAGADO - backup seguro.
)

echo.
echo  Nuevo backup:  !BACKUP_NAME!
echo  Destino:       !BACKUP_DEST!
echo  Backups prev:  !MAX_NUM!
echo.
echo  Presiona cualquier tecla para iniciar...
pause >nul

:: ====================================================
::  EJECUTAR BACKUP CON ROBOCOPY
::  /E   = incluye subcarpetas y vacias
::  /Z   = modo reiniciable (archivos abiertos)
::  /R:3 = 3 reintentos
::  /W:2 = 2 seg espera entre reintentos
::  /NP  = sin porcentaje en consola
::  /NFL = no lista archivos
::  /NDL = no lista directorios
:: ====================================================
echo.
echo  Copiando mundo...
echo.
robocopy "%WORLD_DIR%" "!BACKUP_DEST!" /E /Z /R:3 /W:2 /NP /NFL /NDL

if %ERRORLEVEL% LEQ 7 (
    :: Guardar metadata del backup
    set /p ="">"!BACKUP_DEST!\BACKUP_INFO.txt" 2>nul
    echo Numero:   !NEXT_STR!>>"!BACKUP_DEST!\BACKUP_INFO.txt"
    echo Nombre:   !BACKUP_NAME!>>"!BACKUP_DEST!\BACKUP_INFO.txt"
    echo Servidor: !ESTADO!>>"!BACKUP_DEST!\BACKUP_INFO.txt"
    for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set DT=%%I
    echo Fecha:    !DT:~6,2!/!DT:~4,2!/!DT:~0,4! !DT:~8,2!:!DT:~10,2!>>"!BACKUP_DEST!\BACKUP_INFO.txt"

    echo.
    echo  =====================================================
    echo  [OK] BACKUP #!NEXT_STR! COMPLETADO EXITOSAMENTE
    echo  =====================================================
    echo.
    echo  Guardado en: !BACKUP_DEST!
) else (
    echo.
    echo  [ERROR] Fallo el backup. Codigo: %ERRORLEVEL%
)

echo.
pause
endlocal



