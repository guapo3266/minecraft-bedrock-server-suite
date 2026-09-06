# gui_frontend — React + Vite (dashboard de la suite)

Fuente del panel web servido por `server_gui_server.py`. El `dist/` compilado
viaja commiteado y se sirve tal cual (no hace falta Node en runtime).

## Desarrollo

```bash
cd gui_frontend
npm ci        # instalación reproducible (usa package-lock.json)
npm run dev   # entorno local
npm run lint  # oxlint
```

## Build / sincronización de `dist/`

```bash
cd gui_frontend
npm run build   # regenera dist/
```

`dist/` debe reconstruirse siempre que cambie el frontend antes de
sincronizar a `..\Servidor de Guapo` o al repo público
(`..\minecraft-bedrock-server-suite`). No commitear mundos, packs ni
configs del servidor (ver `.gitignore`).
