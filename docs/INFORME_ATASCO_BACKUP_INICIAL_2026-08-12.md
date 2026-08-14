# Informe: "Atasco" del backup inicial en Servidor de Guapo (3 min) — no era un cuelgue

**Fecha:** 2026-08-12
**Alcance:** diagnóstico sin cambios de código (Servidor de Guapo, PROD)
**Estado:** RESUELTO — evento transitorio; el servidor quedó online

---

## 1. Resumen ejecutivo

Tras sincronizar los cambios de TESTTEST (consola bilingüe + GUI), el arranque de
Servidor de Guapo se quedó ~3 minutos en el backup inicial (`inicio`), cuando
normalmente tarda ~6 s. Parecía un cuelgue, pero era una **espera por contención
de I/O transitoria** (Windows Defender escaneando los ~100 MB de archivos recién
sincronizados sobre el mismo volumen), no un bug:

- El mismo mundo + mismo código comprimen en **6.4 s**.
- El ZIP producido por el run "lento" es **byte-idéntico** (SHA256) al de un run
  rápido: el trabajo era el mismo, solo a ritmo de espera.

## 2. Síntomas

```
[02:56:20][*] Creando copia de seguridad comprimida (inicio)...
<-- sin más salida durante ~3 minutos -->
[02:59:39] <-- ZIP publicado, BDS arranca, servidor ONLINE
```

## 3. Investigación

| Prueba | Resultado |
|---|---|
| CPU del wrapper (`Get-Process.CPU`, delta 3 s) | **0.19 s/3 s** → casi idle, NO comprimía |
| `.tmp` del backup | 0 bytes durante ~2.5 min → no escribía |
| `create_backup` en proceso contra el mundo real | **6.4 s** (92.44 MB, 56 archivos) |
| Idem con `external_lock` (patrón exacto del wrapper) | Rápido |
| SHA256 del zip "lento" vs zip de un run posterior | **IDÉNTICOS** → contenido correcto |
| Proceso BDS tras el backup | Arrancó a las 02:59:39, uptime estable |

**Cronología del entorno**: sync de ~100 MB de archivos nuevos (el `dist/` de la
GUI pesa ~95 MB) → reinicio de la GUI 12 s después (02:56:08) → wrapper a las
02:56:20. Defender real-time activo, sin exclusiones configuradas. El patrón
(espera con CPU 0, sin escrituras, transitorio, no reproducible) es consistente
con escaneo antivirus en frío; no se pudo probar de forma concluyente a
posteriori.

## 4. Hallazgo adicional: backups "desaparecidos"

Los backups del 08-04 y 08-07 estaban en la **raíz** de
`Backups_Minecraft\auto_backups\` (época pre-H3: los backups se escribían en una
sola carpeta). La versión H3 ("backups por servidor") escribe en
`auto_backups\<nombre del servidor>\`, así que la GUI dejó de listarlos (no se
borraron). Se movieron los 12 ZIP a `auto_backups\Servidor de Guapo\` y volvieron
a ser visibles y restaurables (13 backups en la GUI).

## 5. Lecciones

1. Un backup "lento" no es un cuelgue: **medir CPU y bytes escritos** lo delata
   al instante (mismo método que INFORME_COLGADO_SPAWN_WORKER).
2. Tras sincronizar archivos grandes, el primer arranque puede sufrir contención
   de AV; es transitorio. Si se repite, capturar el stack con
   `faulthandler`/`py-spy` en vez de adivinar.
3. **Recomendado** (requiere admin): exclusiones de Windows Defender para
   `C:\Users\guapo\Downloads\Servidores_Minecraft` y
   `C:\Users\guapo\Downloads\Backups_Minecraft`.
