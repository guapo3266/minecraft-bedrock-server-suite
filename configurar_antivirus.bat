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

if "%PS_ERR%"=="0" (
    echo.
    echo [OK] Exclusiones de antivirus configuradas.
) else (
    echo.
    echo [AVISO] Ocurrio un problema al configurar las exclusiones. Codigo: %PS_ERR%.
    echo Si cancelaste el aviso de UAC, vuelve a ejecutar este archivo como Administrador.
    echo.
    pause
)
exit /b %PS_ERR%
