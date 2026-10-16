# Verificación y correcciones de la revisión manual — 2026-10-03

Alcance: los cinco hallazgos de la revisión previa. Se contrastaron mediante
lectura de implementación, consumidores, tests existentes e informes históricos.
La revisión y las correcciones iniciales respetaron la restricción de no ejecutar
tests. Después el usuario autorizó su ejecución; los resultados figuran en la
sección de validación. No se arrancó BDS.

## Resultado y evidencia

| Hallazgo | Verificación manual | Corrección |
|---|---|---|
| H1: recovery BDS borra originales aún no resguardados | Confirmado, P1. El manifiesto se escribía antes de la fase 1; el recovery borraba `target` aun cuando `prev/path` no existía. Una caída antes de mover `a.dll` eliminaba su única copia en el siguiente arranque. | Validar todo el manifiesto primero; reemplazar solo cuando existe el original resguardado; conservar destinos aún no movidos o ya recuperados. Si faltan original y resguardo, conservar el manifiesto. |
| H2: cualquier host HTTPS aceptado como oficial | Confirmado como debilidad de autenticidad, P2 condicional. `https://evil.example/bedrock-server-1.2.3.4.zip` pasaba el regex; `requests` seguía redirecciones automáticamente. Requiere manipulación del metadato oficial o redirección: la clasificación P1 de la primera revisión fue excesiva. | Hosts exactos oficiales, HTTPS/443, sin credenciales/fragmentos; validación en la descarga y antes de cada salto, sin redirecciones automáticas y con tope. |
| H3: destino de mundo derivado de `level-name` sin límite | Confirmado, P2 por configuración local. `level-name=../../OtraCarpeta` se usaba en `join(base, "worlds", name)` y llegaba al swap de restore. La GUI no permite editar esta clave: el desencadenante es una edición externa de `server.properties`. | Resolver común con un solo nombre válido para Windows; guard de hijo directo de `worlds/` y de enlaces/junctions. El core vuelve a validar destinos explícitos antes de abrir el ZIP. |
| H4: fallback por copia borra resguardo sin equivalencia | Confirmado, P2. Si active contiene `sobrante.json` y el `.bak` solo `manifest.json`, `copy2` no elimina el sobrante; antes se borraba el `.bak` al no haber errores de copia. Es relevante también para packs. | Mantener siempre el `.bak` cuando se recurre a copiar; avisar que requiere verificación/recuperación exacta manual. Corregir mensajes de CLI y core que prometían integridad pese a un fallo. |
| H5: setup no detecta BDS externo | Confirmado, P2. El endpoint solo comprobaba `manager.is_running`, que es falso para un wrapper/BDS lanzado fuera de la GUI, y llamaba al mismo reemplazo de binarios que update. El endpoint no está limitado server-side a mostrar el wizard. | Re-chequear el estado y sondear la instalación bajo `op_lock` antes del despacho; 409 ante instancia externa. Liberar el lock si falla el guard, la sonda o el arranque del hilo. |

## Detalles necesarios del fix

- H1: el manifiesto se persiste antes de mover originales (`flush` + `fsync`).
  El rollback interno conserva su carpeta de resguardo si no logra completar la
  recuperación. Se usan las rutas del manifiesto para devolver originales,
  evitando un `os.walk` que pueda omitir carpetas inaccesibles y evitando mover
  un manifiesto temporal al directorio activo.
  La recuperación permite reintentos: si ya devolvió `a.dll` y luego falló en
  `b.dll`, la siguiente llamada conserva `a.dll` y recupera lo pendiente.
- H2: la [API oficial de descargas](https://net-secondary.web.minecraft-services.net/api/v1.0/download/links)
  se consultó para comprobar el host de `serverBedrockWindows`: `www.minecraft.net`.
  La lista admite ese host y `minecraft.net`, con máximo cinco redirecciones.
  No se descargó BDS. Los streams, incluidos los de redirección, se cierran.
  Si Mojang cambia de dominio, se falla de forma segura y se debe revisar la lista.
  La ausencia de firma/hash ya era un riesgo aceptado en el informe 2026-09-25;
  este fix no añade ni promete autenticidad criptográfica del binario.
- H3: GUI y CLI comparten `server_properties.resolve_world_dir`; se mantiene la
  compatibilidad de globals parcheados en tests y el guard del core sigue siendo
  obligatorio. Las propiedades inválidas se rechazan al operar, sin introducir
  un fallo de import que impida abrir la GUI para diagnosticarlo. La instalación
  puede tener su propia ruta resuelta por Windows; se rechazan redirecciones de
  la raíz `worlds/` o del mundo.
- H4: se conserva la copia de recuperación completa aunque todas las copias de
  archivos hayan funcionado. El recuperador existente puede renombrarla después
  a `.bak_huerfano_*`; esa evidencia sigue requiriendo revisión manual.
- H5: se utiliza la sonda existente; no se rediseñan locks ni las seis escrituras
  protegidas a stdin. El guard comprueba instancias presentes al despachar y no
  constituye un lock entre procesos que impida arranques externos posteriores.

## Regresiones preparadas y documentación

`tests/test_revision_manual_2026-10-03.py` cubre estados de caída antes/durante
el resguardo, reintentos de recovery, manifiestos inválidos, originales ausentes,
fallo del rollback interno, URLs/redirecciones, cierre de streams, rutas de mundo,
junctions simuladas, fallback con archivos sobrantes y guards/liberación de locks
del instalador. Todos usan datos temporales y red simulada.

Se ajustaron los mocks de URLs en los tests existentes, la expectativa del
fallback (ahora conserva `.bak`) y el inventario i18n para `server_properties.py`.
La primera ejecución completa detectó otros nueve casos pendientes de adaptar:
fixtures con mundos fuera de `BASE_DIR/worlds/`, una URL ficticia que impedía
alcanzar el escenario HTTP 404 y una expectativa antigua de eliminación del
resguardo ante archivos abiertos. Se corrigieron en `test_packs_in_backup.py`,
`test_review_hallazgos.py`, `test_ronda_2026-09-11.py` y `test_backup_fixes.py`,
manteniendo las comprobaciones originales de integridad, rollback y error HTTP.
README (ES/EN), AGENTS.md, ARCHITECTURE.md y API_CONTRACT.md reflejan únicamente
los contratos y procedimientos que cambiaron.

## Validación y límites

- Revisión estática del flujo y del diff.
- Comprobación de sintaxis con `ast.parse`, sin importar los módulos.
- Revisión de espacios del diff con `git diff --check`.
- Tests ejecutados tras autorización posterior del usuario, usando
  `.venv\Scripts\python.exe` (pytest 9.1.1, Hypothesis 6.165.10 y httpx 0.28.1).
  `httpx` estuvo disponible: los tests HTTP de la GUI no se saltaron por su ausencia.
  - `-m pytest tests/test_revision_manual_2026-10-03.py -m "not e2e" -q`:
    **40 aprobados**.
  - Tests focalizados de update/rollback BDS, setup, ZIP, resolvers, restore e i18n:
    **82 aprobados**.
  - Primera suite completa: **847 aprobados, 9 fallidos, 2 e2e excluidos**.
    Los nueve fallos se debían a los fixtures y expectativas descritos arriba;
    su reejecución focalizada tras adaptarlos dio **9 aprobados**.
  - `-m pytest tests -m "not e2e" -q --durations=10`:
    **856 aprobados, 2 e2e excluidos**, 139,71 s, sin tests saltados ni warnings.
  - `-m ruff check .`: **sin incidencias**.
- GUI interactiva, BDS y frontend no ejecutados. Los tests ejercitan la lógica
  y las rutas HTTP/WS con datos temporales y dependencias simuladas; no validan
  una descarga real ni el comportamiento con BDS en ejecución.
- Los archivos experimentales sin seguimiento que ya existían no forman parte
  de esta ronda.

## Sincronización posterior a producción

Por pedido del usuario se sincronizó únicamente `../Servidor de Guapo`, después
de leer los AGENTS.md de ambos destinos. `npm run build` terminó correctamente;
se actualizaron 19 archivos y se verificaron por SHA256 los 120 archivos de la
lista permitida, incluido `dist/`. Los hashes de los archivos protegidos de raíz
y el inventario (rutas, tamaños, fechas de escritura) de mundos, packs y datos
permanecieron iguales. El AGENTS.md propio de producción se conservó.

No había GUI ni BDS ejecutándose, por lo que no hizo falta reiniciar. `tests/`
y `docs/` ya estaban ausentes. La revisión automática bloqueó la eliminación
de cuatro carpetas `__pycache__` con «blocked by policy», sin motivo detallado;
esas carpetas quedaron presentes. También se encontró el residuo previo
`tools/test_gui_e2e.py`: no se copió, y su eliminación explícita fue bloqueada
por la misma revisión. No se sincronizó ni publicó el repo público.
