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

if %errorlevel% neq 0 (
    echo.
    echo [AVISO] Ocurrio un problema al ejecutar PowerShell.
    echo Si cancelaste el aviso de UAC, vuelve a ejecutar este archivo como Administrador.
    echo.
    pause
)
