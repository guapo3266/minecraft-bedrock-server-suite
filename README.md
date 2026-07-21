# Minecraft Bedrock Server Suite

<div align="right">
  <a href="#español">🇪🇸 Español</a> | <a href="#english">🇬🇧 English</a>
</div>

<h2 id="español">🇪🇸 Español</h2>

Un par de scripts sencillos que armé en Python para manejar mi servidor de Bedrock en Windows. Lo hice principalmente porque estaba cansado de tener que echar a mis amigos del servidor cada vez que quería hacer una copia de seguridad. 

Usa los comandos nativos de Minecraft (`save hold`, `save query`, `save resume`) para hacer backups en segundo plano sin apagar el servidor (creo que a esto le dicen "backups en caliente").

Lo estuve probando un buen rato en Windows 10/11 y parece que funciona bien, siempre que tengas Python 3.10 o más reciente.

### ¿Qué intenté hacer con esto?

- Hacer backups automáticos cada 30 minutos sin molestar a los jugadores.
- Borrar automáticamente los backups viejos (guarda los últimos 15 y 1 diario por una semana, creo).
- Hace un backup apenas arranca el server y otro al apagarlo.
- Tiene un menú interactivo con `.bat` para que restaurar el mundo no sea tan molesto.
- También metí un script para abrir los puertos del firewall si les sirve.

### Archivos
* `iniciar_servidor.bat` - Para arrancar el server con el wrapper.
* `01_hacer_backup.bat` - Por si quieres hacer un backup a mano usando robocopy.
* `02_restaurar_backup.bat` - El menú para restaurar un backup.
* `03_regresar_al_anterior.bat` - Este deshace los cambios y vuelve al backup más reciente rápido.
* `server_wrapper.py` - Es el script principal que lee la consola y maneja lo de los backups.
* `auto_backup.py` - El que comprime la base de datos a ZIP.
* `restore_backup.py` - Script para restaurar.
* `enable_beta_apis.py` - Un script medio experimental que hice para toquetear el `level.dat`.

### Para usarlo:
1. Necesitas tener Python instalado.
2. Clonas esto o descargas el zip.
3. Copias el `server.properties.example` y le pones `server.properties`.
4. Tiras el `bedrock_server.exe` original (y sus DLLs) adentro.
5. Le das doble clic a `iniciar_servidor.bat`.

### Algunos detalles técnicos:
Me dio bastantes dolores de cabeza la parte donde la compresión del ZIP se quedaba colgada cuando el disco estaba lento, así que tuve que usar `multiprocessing` con candados (locks) para ponerle un timeout de seguridad. Si tarda más de 2 minutos comprimiendo, simplemente mata el proceso para que el servidor no se quede congelado para siempre. Espero haber tapado todos los huecos de concurrencia. Si ven algún bug me avisan.

---

<h2 id="english">🇬🇧 English</h2>

Just some simple Python scripts I put together to manage my Bedrock server on Windows. Honestly, I mostly built this because I got annoyed having to kick my friends out of the server every time I wanted to run a backup.

It uses the native Minecraft commands (`save hold`, `save query`, `save resume`) to do zero-downtime hot backups in the background. 

I tested it on Windows 10/11 for a bit and it seems to be working fine as long as you have Python 3.10+.

### What I tried to add:

- Hot backups every 30 mins without kicking anyone.
- Auto-deletes old backups so the drive doesn't fill up (keeps like 15 recent ones and 1 daily for a week I think).
- Does a backup when the server starts and when it stops.
- A basic `.bat` interactive menu to restore backups easily.
- A quick script to open firewall ports in case you need it.

### Files
* `iniciar_servidor.bat` - Starts the server wrapper.
* `01_hacer_backup.bat` - If you wanna run a manual backup with robocopy.
* `02_restaurar_backup.bat` - Menu to restore a zip.
* `03_regresar_al_anterior.bat` - Reverts to the last backup in one click.
* `server_wrapper.py` - The main script that reads the console and handles the backup logic.
* `auto_backup.py` - Zips the files.
* `restore_backup.py` - Restores the zip.
* `enable_beta_apis.py` - An experimental script to mess with `level.dat`.

### How to use:
1. You need Python installed.
2. Clone this or download it.
3. Copy `server.properties.example` to `server.properties`.
4. Drop your `bedrock_server.exe` and dlls inside.
5. Just double click `iniciar_servidor.bat`.

### Random technical notes:
I had some serious headaches with the ZIP compression getting stuck on slow disks, so I ended up using `multiprocessing` and IPC locks to add a hard timeout. If it takes more than 2 minutes to compress, it just forcefully kills the worker so the server doesn't stay frozen forever. Hopefully I covered all the concurrency edge cases. Let me know if you find any bugs.
