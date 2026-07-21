@echo off
echo ============================================
echo  Configurando Firewall para Minecraft Bedrock
echo ============================================
echo.

netsh advfirewall firewall add rule name="Minecraft Bedrock Server UDP" dir=in action=allow protocol=UDP localport=19132,19133
netsh advfirewall firewall add rule name="Minecraft Bedrock Server TCP" dir=in action=allow protocol=TCP localport=19132,19133

echo.
echo ============================================
echo  Firewall configurado correctamente!
echo  Puertos 19132 y 19133 abiertos (UDP/TCP)
echo ============================================
echo.
pause
