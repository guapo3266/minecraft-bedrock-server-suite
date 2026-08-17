@echo off
echo ============================================
echo  Configurando Firewall para Minecraft Bedrock
echo ============================================
echo.

netsh advfirewall firewall add rule name="Minecraft Bedrock Server UDP" dir=in action=allow protocol=UDP localport=19132,19133
if errorlevel 1 goto :fw_error
netsh advfirewall firewall add rule name="Minecraft Bedrock Server TCP" dir=in action=allow protocol=TCP localport=19132,19133
if errorlevel 1 goto :fw_error

echo.
echo ============================================
echo  Firewall configurado correctamente!
echo  Puertos 19132 y 19133 abiertos (UDP/TCP)
echo ============================================
echo.
pause
exit /b 0

:fw_error
echo.
echo ============================================
echo  [ERROR] netsh fallo y el firewall NO quedo
echo  configurado. Casi siempre es falta de
echo  permisos: clic derecho -^> "Ejecutar como
echo  administrador" y vuelve a probar.
echo ============================================
echo.
pause
exit /b 1
