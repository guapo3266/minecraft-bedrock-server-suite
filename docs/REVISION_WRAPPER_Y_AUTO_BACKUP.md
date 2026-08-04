# Revisión: server_wrapper.py + auto_backup.py

**Alcance**: los 709 + 327 líneas completos, más cobertura existente en `tests/` (test_wrapper_logic.py, test_pbt_properties.py).

---

## Hallazgos por severidad

### ALTO

**1. El parser de `save query` acepta cualquier línea `texto:numero` del stdout → un ciclo de backup aborta ante ruido inesperado** *(severidad revisada: ALTO → MEDIO — el ejemplo original de chat era incorrecto)*
`server_wrapper.py:108` — `re.findall(r"([^,\r\n]+?):(\d+)", line)` captura **cualquier** patrón `texto:numero` de cualquier línea del stdout, no solo la lista de archivos de `save query`. Aclaración: el chat del juego **no** se imprime en la terminal de BDS, así que los ejemplos de mensajes de chat eran inválidos. El ruido realista durante la ventana de recolección (`server_wrapper.py:349-368`, ~5s tras "Data saved") son otras líneas del stdout con `label:número`: estadísticas de `tick time: X ms`, salidas de comandos con `label: valor`, logs de scripts/addons de behavior packs, y líneas `[WARN]`/`[ERROR]` con `id:`/`code:`. La única exclusión es `match_conn/match_disc` (línea 362).
- Consecuencia: en el hijo, `auto_backup.py:165-166` → `os.path.exists` falso → `RuntimeError` → **el backup completo aborta**. Basta una sola línea con `texto:numero` en la ventana para perder el ciclo (reintento recién a los 30 min). Falla silenciosa, y en cadena si la línea se repite (p. ej. logs periódicos de scripts).
- Los tests cubren el caso `xuid:` sin espacio (`test_wrapper_logic.py:109-123`) pero **no** ruido genérico `texto:numero` durante la ventana.
- Fix sugerido: solo aceptar entradas que parezcan rutas del mundo (`db/`, `level.dat`, etc.), o activar la recolección solo para líneas posteriores a "Data saved" y validar formato en `_resolve_snapshot_path` (ya lanza error claro; el problema es que aborta el backup entero).

**2. Un backup válido publicado puede borrarse a sí mismo**
`auto_backup.py:241-261` — `os.replace(tmp, zip)` ocurre en 241, pero `success = True` recién en 244. Si `os.path.getsize` (242) o el `print` (243) lanzan (p. ej. ZIP bloqueado por antivirus), el `finally` (255-261) ejecuta `os.remove(zip_filepath)` con `success=False` → **borra un ZIP íntegro ya publicado**. Fix: setear `success = True` inmediatamente tras `os.replace`, o excluir el zip publicado en el cleanup.

### MEDIO

**3. Ruta normal de "stop" sin timeout → wrapper colgado para siempre**
`server_wrapper.py:608-609` — el loop principal espera `poll()` sin límite tras enviar `stop`. Si BDS cuelga en el apagado, nunca se hace kill ni backup final. La ruta Ctrl+C sí tiene `wait(timeout=15)` + `kill` (616-624), pero es inconsistente: 15s también es poco para mundos grandes a mitad de guardado (riesgo de corrupción). Falta un timeout único en la ruta normal.

**4. Backups marcados corruptos se acumulan sin límite**
`server_wrapper.py:226` marca `_POSIBLEMENTE_CORRUPTO`; `auto_backup.py:274` excluye `_CORRUPTO`/`_EXCEDIDO` de la rotación → nunca se borran → fuga de disco indefinida. Si la intención es conservar evidencia, falta una política (p. ej. rotar los corruptos a los N días).

**5. Watchdog de 60s vs. listas de archivos lentas**
`server_wrapper.py:414, 429-437` — el despacho exige 5s de silencio en el snapshot y el watchdog fuerza `save resume` a los 60s. En mundos grandes donde BDS tarda en emitir la lista, o si la lista llega antes de "Data saved" (snapshot queda vacío, 353-356), el ciclo aborta y se reintenta recién a los 30 min. Degradación operativa silenciosa.

**6. El `except` genérico del worker no mata al hijo vivo**
`server_wrapper.py:244-254` — si algo lanza tras `comp_proc.start()` (177), el proceso hijo daemon sigue comprimiendo y retiene `backup_ipc_lock`; el siguiente ciclo falla con "Ya hay un backup ejecutandose" (`auto_backup.py:95`) hasta que el hijo muera solo. Se autocura, pero se pierden ciclos de backup.

### BAJO

- **7.** `server_wrapper.py:370-374` — el `except` del loop de lectura traga todo; si `readline()` falla permanentemente → busy-loop con spam.
- **8.** `auto_backup.py:28` — `BACKUP_DIR` hardcodeado a `..\..\Backups_Minecraft\auto_backups` (fuera del proyecto): si se mueve la estructura, los backups van a otro lado silenciosamente.
- **9.** No hay verificación de integridad del ZIP (abrir/testzip) antes de reportar éxito.
- **10.** `server_wrapper.py:274-278` — `sys.stdout.write` en consola cp1252 con BDS UTF-8 → `UnicodeEncodeError` tragado → logs invisibles (cosmético).
- **11.** `server_wrapper.py:426` — mensaje "vía timeout de resguardo" obsoleto (ya no hay ruta de despacho inmediato); confunde al operar.

---

## Riesgo residual y huecos de test

- **Lo bueno**: el diseño defensivo es sólido — lock IPC, `os.replace` atómico, validación de cobertura ≥70% del `db/` (auto_backup.py:140-149), guardas anti-traversal con `realpath` (41-73), cancelación cooperativa, y los fixes de regresión en `test_wrapper_logic.py` (xuid sin espacio, ruido entre header/nombres). El guard `if __name__ == "__main__"` evita doble arranque del servidor con spawn.
- **Faltan tests para**: (a) ruido genérico `texto:numero` (tick time, salidas de comandos, logs de scripts) durante la ventana de snapshot (hallazgo 1); (b) `create_backup` con excepción post-`os.replace` (hallazgo 2); (c) rotación con archivos corruptos (hallazgo 4); (d) integración multiproceso spawn+queue+kill (no hay cobertura real del flujo worker).
- **Riesgo residual**: la truncación silenciosa de `.log`/`MANIFEST-` que crecieron (auto_backup.py:172-183) es deliberada para WAL, pero un MANIFEST truncado puede impedir abrir el mundo en restauración — vale una prueba de restauración real antes de confiar en backups en caliente.

---

## Resumen

No hay bugs de corrupción de datos en el camino feliz; la arquitectura (hold → query → snapshot → proceso aislado → resume) es correcta y bien protegida. Los riesgos reales son de **fiabilidad silenciosa**: el parser permisivo (1) puede tumbar un ciclo de backup ante cualquier línea `texto:numero` inesperada en el stdout (tick time, salidas de comandos, logs de addons), y el apagado sin timeout (3) puede colgar el wrapper. El 2 es el único caso de pérdida de un backup ya válido. Recomiendo corregir 2 y 3 antes de producción; aplicar el fix de 1 (validación de rutas en el parser) como endurecimiento de bajo costo; y 4-6 como mejoras operativas.
