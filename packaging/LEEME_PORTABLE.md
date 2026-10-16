# SuiteMinecraft portable — uso personal

1. Extrae TODA la carpeta en una ubicacion escribible, por ejemplo Documentos.
   Conserva `SuiteMinecraft.exe`, `SuiteMinecraftHost.exe` y `_internal` juntos.
2. Abre **SuiteMinecraft.exe**. El panel aparece en su propia ventana. El motor
   Chromium viene incluido; no necesitas Python, Node.js, Electron ni WebView2.
   No aparece una consola adicional. El asistente IA esta oculto en esta version.
3. La copia empieza vacia: no contiene BDS, mundos, packs ni configuraciones
   privadas. Puedes descargar BDS con el boton del asistente, o copiar TODOS
   los archivos de una instalacion de BDS a esta carpeta y pulsar
   **Ya copie BDS: comprobar instalacion**. Nada se descarga automaticamente.
4. Completa la configuracion y pulsa **Iniciar servidor** cuando quieras jugar.
   Abrir la aplicacion no arranca Minecraft automaticamente.
5. Al cerrar la ventana, si hay jugadores se pide confirmacion. Despues se
   detiene el servidor y se espera el backup final mostrando el progreso.
   Si falla el backup, la ventana permanece abierta para reintentarlo o salir
   sin esa copia. Si falla el apagado, se mantiene el panel accesible.
6. **Personalizar** en la cabecera permite elegir fondo, tema y vidrio. La
   consola tiene **Expandir/Reducir** y vuelve con Esc. El aviso del producto
   esta en **Mas acciones → Acerca de**.

Mundos, packs, propiedades y `data/` pertenecen a esta carpeta. Los backups se
guardan en `backups/`; los registros de diagnostico estan en `logs/` y se abren
desde el menu **Aplicacion**. Las preferencias/cache del panel tambien quedan
en `data/`. Deten el servidor antes de trasladar la carpeta completa a otro
equipo Windows de 64 bits. El equipo debe cumplir los requisitos del BDS que
decidas instalar. Un cierre forzado del proceso o de Windows puede interrumpir
las operaciones: el cierre supervisado corresponde al cierre normal de la app.

`SuiteMinecraftHost.exe` es un componente interno para wrapper y compresion,
con pipes de consola y ventanas ocultas. El acceso habitual es SuiteMinecraft.exe.
La GUI de escritorio solo escucha en 127.0.0.1; parte del puerto 8000 y busca
el siguiente libre. `GUI_PORT` y `WRAPPER_LANG` siguen disponibles.

No se toca ninguna instalacion vecina. Generar este paquete no lo publica.
No incluye el ejecutable de Mojang, modelos IA ni firma digital de
Windows. `MANIFIESTO.json` contiene los hashes y versiones de compilacion.
Las licencias de las dependencias acompanian el paquete en `LICENCIAS/`.
