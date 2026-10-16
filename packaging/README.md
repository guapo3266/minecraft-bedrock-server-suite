# Construccion privada del portable Windows

Desde la raiz del proyecto, con Python 3.11 de 64 bits y Node.js instalados:

```powershell
powershell -ExecutionPolicy Bypass -File crear_portable.ps1
```

El script prepara `.venv-portable` separado del entorno de desarrollo, instala
`requirements-build.txt`, reconstruye React con Vite y ejecuta PyInstaller en
modo carpeta. No instala BDS, no arranca el servidor, no sincroniza destinos y
no publica ni ejecuta comandos Git. El build solo toma codigo importado y una
lista explicita de recursos en `SuiteMinecraft.spec`.

El nuevo frontend portable oculta la IA; el build habitual de `gui_frontend/dist`
la conserva. Qt WebEngine aporta Chromium y sus recursos. No requiere WebView2
instalado. El build limita PATH a Windows y Python para no recoger DLL homonimas
de otras herramientas locales; el spec rechaza binarios fuera de esos entornos.

Resultados:

- `portable/SuiteMinecraft/SuiteMinecraft.exe`, `SuiteMinecraftHost.exe` y `_internal/`.
- `portable/SuiteMinecraft-portable.zip` con esa carpeta completa.
- `portable/SuiteMinecraft-portable.zip.sha256`.
- `MANIFIESTO.json` dentro del paquete, con hashes y versiones de dependencias.

Un rebuild mueve la carpeta anterior a `SuiteMinecraft_anterior_*` para conservar
cualquier dato de usuario. No migra automaticamente esos datos a la copia nueva.
Si se actualiza una instalacion portable existente, conservar primero toda su
carpeta y reemplazar unicamente el ejecutable y `_internal`; no borrar mundos,
packs, `data/`, propiedades ni backups.

Reconstruir o sincronizar `gui_frontend/dist/` no actualiza un EXE ya generado:
los recursos del portable están en su propio `_internal`. Para incorporar una
modificación de la GUI hay que repetir el build del portable y su verificación.
`portable/`, `.venv-portable/` y `build/portable/` quedan fuera de Git; las fuentes
y las instrucciones de empaquetado sí pertenecen al repositorio.

## Adaptaciones de runtime

`runtime_paths.py` distingue la instalacion del directorio de recursos
`_internal`. Se apoya en el
[contrato de runtime de PyInstaller](https://pyinstaller.org/en/stable/runtime-information.html).
En fuente se conserva la ruta historica de backups; en el portable es
`backups/` junto al ejecutable. Los subprocesos siguen usando `subprocess.Popen`,
pipes, JSON y NDJSON; el lanzador despacha modos internos al wrapper o worker
sin iniciar otra GUI. No se usa `multiprocessing.spawn` para comprimir.

SuiteMinecraft.exe usa el bootloader de ventana; SuiteMinecraftHost.exe mantiene
el modo consola para los pipes del wrapper/worker, con CREATE_NO_WINDOW. El
lanzador habitual aloja Uvicorn en un hilo y el panel en QWebEngineView. El
perfil, cache y registros quedan junto al ejecutable. `--no-browser` en el host
mantiene la superficie HTTP sin ventana para la verificacion automatizada.

El cierre de ventana toma `op_lock`, reutiliza `lifecycle.stop_and_wait` y lee
el evento `final_backup_finished` del canal de la sesion. No deduce exito por
un print ni duplica el backup que ya hizo el wrapper. Un fallo conserva la
ventana y la exclusion para permitir Reintentar/Salir; un fallo de apagado
devuelve al panel. El cierre normal no fuerza procesos para fingir exito.

## Verificacion aislada

```powershell
.\.venv\Scripts\python.exe -m pytest tests -m "not e2e" -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe tools/verify_portable.py
```

La ultima orden copia el paquete bajo `build/portable/qa/` a una ruta con
espacios y acentos, elimina Python/Node del PATH del hijo y arranca el EXE
desde otra carpeta. Comprueba HTTP, recursos React, WebSocket, guards, worker
real, ZIP y restore de bytes sinteticos. Tambien comprueba que el wrapper
emita su evento y libere su sesion cuando falta BDS. No descarga ni ejecuta
BDS y no acredita una partida, backup caliente o apagado real de Minecraft.
El informe HTTP se escribe en `portable/VERIFICACION.json`, fuera del ZIP limpio.
`tools/prepare_desktop_qa.py` prepara otra copia para QA visual con un simulador
C# minimo de stdin/stdout (tests/fixtures/portable_stub.cs). Este simulador NO
contiene Minecraft y NUNCA se agrega al paquete. Permite probar confirmacion
con un jugador sintetico, apagado, fallo de backup y reintento en el EXE real.
