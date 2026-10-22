@echo off
setlocal
title Configurar Exclusiones de Antivirus - Minecraft Bedrock

echo ========================================================
echo  Configuracion de Exclusiones de Antivirus (Defender)
echo ========================================================
echo.
echo Ejecutando script de configuracion de exclusiones...
echo (Si aparece la ventana de Control de Cuentas de Usuario / UAC, selecciona 'Si')
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup_defender_exclusions.ps1"
rem El .ps1 espera al proceso elevado y propaga su exit code; aqui se captura
rem nada mas volver (echo/pause pueden pisar %errorlevel%) para devolverlo.
set "PS_ERR=%errorlevel%"

rem 2 = Defender no esta activo: no se configuro nada (antes salia 0 y se
rem anunciaba [OK] sin haber anadido ninguna exclusion, 2026-10-21).
if "%PS_ERR%"=="0" (
    echo.
    echo [OK] Exclusiones de antivirus configuradas.
) else if "%PS_ERR%"=="2" (
    echo.
    echo [AVISO] Windows Defender no esta activo: no se configuro ninguna exclusion.
    echo         Anade a tu antivirus las carpetas que se listaron en la otra ventana.
    echo.
    pause
) else (
    echo.
    echo [AVISO] Ocurrio un problema al configurar las exclusiones. Codigo: %PS_ERR%.
    echo Si cancelaste el aviso de UAC, vuelve a ejecutar este archivo como Administrador.
    echo.
    pause
)
exit /b %PS_ERR%
