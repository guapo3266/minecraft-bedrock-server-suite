@echo off
title Minecraft Bedrock Server Suite
color 0a

echo.
echo  ==========================================
echo  ^|                                        ^|
echo  ^|   MINECRAFT BEDROCK SERVER SUITE       ^|
echo  ^|                                        ^|
echo  ==========================================
echo.
echo  Puerto: 19132 (UDP)
echo  Modo: Survival
echo  Dificultad: Normal
echo  Max Jugadores: 20
echo.
echo  Para detener el servidor escribe: stop
echo  ==========================================
echo.

:: Ejecutar el wrapper de ESTA instalacion (la carpeta del propio .bat),
:: no una ruta hardcodeada a otra instalacion.
cd /d "%~dp0"

:: [0/2] Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] No se encontro Python 3.
    echo         Descargalo en https://www.python.org/downloads/
    echo         IMPORTANTE: marca la casilla "Add Python to PATH".
    pause
    exit /b 1
)

:: [1/2] Si falta bedrock_server.exe, preguntar y descargarlo desde Mojang
python tools\bds_first_run.py
if errorlevel 2 (
    exit /b 2
)
if errorlevel 1 (
    echo.
    echo [ERROR] No se pudo preparar bedrock_server.exe. Revisa los mensajes de arriba.
    pause
    exit /b 1
)

:: [2/2] Arrancar el wrapper
python server_wrapper.py

echo.
echo  El servidor se ha detenido.
pause
