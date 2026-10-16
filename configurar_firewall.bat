@echo off
echo ============================================
echo  Configurando Firewall para Minecraft Bedrock
echo ============================================
echo.

rem BDS solo usa UDP 19132/19133 (no hace falta TCP). Se borra la regla
rem homonima (y la TCP obsoleta de versiones anteriores) y se recrea: una
rem regla vieja con otros puertos nunca se ajustaba con "show rule".
rem profile=private: sin abrir el puerto en redes Publicas/Dominio.
netsh advfirewall firewall delete rule name="Minecraft Bedrock Server UDP" >nul 2>&1
netsh advfirewall firewall delete rule name="Minecraft Bedrock Server TCP" >nul 2>&1
netsh advfirewall firewall add rule name="Minecraft Bedrock Server UDP" dir=in action=allow protocol=UDP localport=19132,19133 profile=private
if errorlevel 1 goto :fw_error

echo.
echo ============================================
echo  Firewall configurado correctamente!
echo  Puertos 19132 y 19133 abiertos (UDP, solo red privada)
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
