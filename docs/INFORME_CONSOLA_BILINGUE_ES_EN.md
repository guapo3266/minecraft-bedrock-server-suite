# Informe: Consola bilingüe ES/EN (mensajes del backend adaptados al toggle de la GUI)

**Fecha:** 2026-08-12
**Alcance:** `console_lang.py` (nuevo), `server_wrapper.py`, `server_gui_server.py`, `auto_backup.py`, `backup_worker.py`, `gui_frontend/src/App.jsx`, `tests/test_console_lang_pbt.py` (nuevo)
**Estado:** VERIFICADO (130 tests + prueba real Playwright ES→EN→ES)

---

## 1. Qué hace

El toggle ES/EN del navbar controla también el idioma de los mensajes que genera el backend (wrapper, GUI, auto_backup y el worker de compresión). Antes todo estaba hardcodeado en español.

## 2. Arquitectura

- **`console_lang.py`** (nuevo): `L(es, en)` elige el mensaje según la variable de entorno `WRAPPER_LANG` (`"es"` → español; ausente o cualquier otro valor → inglés, default). `set_lang(lang)` solo acepta `"es"`/`"en"`.
- **Frontend** (`App.jsx`): conecta el WebSocket con `?lang=<idioma>` y reenvía `{type: "set_lang", lang}` cuando el usuario cambia el toggle en vivo.
- **Backend** (`server_gui_server.py`): el WS fija `WRAPPER_LANG` (query param al conectar + mensaje `set_lang`). El wrapper hereda la variable al ser lanzado (`_spawn_wrapper_process` copia el env) y el worker de compresión la hereda por subprocess.
- Todos los mensajes visibles en la consola usan `L("texto es", "texto en")`, con f-strings evaluadas por el llamador.

## 3. Convención obligatoria (modos de fallo SILENCIOSOS)

1. **Todo mensaje nuevo de consola debe usar `L(es, en)`.** Sin `L()`, en modo ES saldrá en inglés sin error.
2. **Ambos argumentos deben ser del mismo tipo** (f-string o string plano) **y con placeholders `{..}` idénticos** — ambos f-strings se evalúan con las mismas variables; si divergieran, el segundo lanzaría `KeyError`. Esta propiedad está protegida por `tests/test_console_lang_pbt.py` (exhaustivo sobre el código fuente + PBT de la extracción).
3. **Los marcadores internos deben coincidir en AMBOS idiomas** en la clasificación de logs de `server_gui_server.py`:
   | Marcador | Efecto |
   |---|---|
   | `"BDS stopped"` / `"BDS detenido"` | `server_stopped_event` → stop/restart/update esperan por él |
   | `"Starting compression in a separate process"` / `"Iniciando compresion de archivos en proceso separado"` | `backup_in_progress = True` |
   | `"Compression successful"` / `"Compresión exitosa"` o `"Backup completed"` / `"Backup completado"` | fin de backup |
   | `"Backup finished"` / `"Backup finalizado"` | fin incondicional del ciclo (H3) |
   | `"Exception"` / `"Excepcion"` / `"Excepción"` | log tipo error |
   | `_is_snapshot_failure` (wrapper): `"cancelled"`/`"cancelado"`, `"exceeds the"`/`"excede el limite"` | clasificación de reintentos de snapshot |

   **Cambiar un marcador a un solo idioma rompe stop/restart y el flag de backup en silencio.**
4. **Default de `WRAPPER_LANG`: inglés.** Los tests unitarios no lanzan el frontend y esperan textos en inglés; el frontend (default ES) fija el idioma real al conectar.
5. Los logs ya emitidos **no se retraducen** al cambiar de idioma; solo los nuevos.

## 4. Verificación

- **130 tests** (incluye 8 PBT nuevos: oráculo de `L()`, validación de `set_lang`, round-trip de placeholders, simetría de claves/placeholders de `i18n.jsx`).
- **Playwright real**: comando con servidor apagado → español; toggle EN → inglés; toggle ES → español. Sin errores de consola JS.
- **Semgrep** (run all, 283+142 reglas): 0 hallazgos en los archivos de este cambio.
