@echo off
title Minecraft Bedrock Server - Servidor de Guapo
color 0a

echo.
echo  ==========================================
echo  ^|                                        ^|
echo  ^|   MINECRAFT BEDROCK SERVER             ^|
echo  ^|   Servidor de Guapo                    ^|
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

cd /d "%~dp0"
python server_wrapper.py

echo.
echo  El servidor se ha detenido.
pause
