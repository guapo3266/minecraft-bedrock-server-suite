# Guía de coherencia visual y general de la GUI

**Fecha:** 2026-08-12 · **Actualizado:** 2026-08-21 (Modal compartido `components/Modal.jsx` + reglas de accesibilidad, retirada de la fuente Outfit, `transition` explícito en vez de `transition-all`; antes: 2026-08-16 botón primario sólido, menú de acciones del header, separador de sesión en consola)
**Alcance:** definición canónica del sistema de diseño de `gui_frontend/` — para que componentes nuevos (y los vendored) mantengan el mismo lenguaje visual
**Estado:** VIGENTE — referenciar antes de crear o modificar cualquier componente

---

## 1. Lenguaje visual en una frase

> Dashboard oscuro "slate-950" con acentos de **esmeralda → cian** (gradiente
> tecnológico), semántica de color por función (emerald=éxito, rose=peligro,
> amber=aviso, purple=comando), tipografía sans del sistema + **mono** para datos,
> micro-animaciones *spring* suaves (framer-motion) y efectos decorativos
> ReactBits/Hover.dev con moderación.

## 2. Tokens de color (fuente: `index.css` y uso real)

| Token | Valor | Uso |
|---|---|---|
| Fondo | `#070a12` | body (bg-dark) |
| Card | `rgba(17,24,39,0.65)` / `bg-slate-900/65` | superficies, header navbar |
| Card modal | `bg-slate-950` | modales |
| Borde | `border-white/10` (rgba 255,255,255,0.08) | separadores, cards, inputs |
| **Primario** | emerald `#10b981` | éxito, online, RAM, jugadores, botón start/send |
| **Secundario** | cyan `#06b6d4` | info, sistema, settings, backups, terminal |
| **Acento** | violet `#8b5cf6` | decorativo (gradientes CPU) |
| **Comando** | purple `#a855f7` | restart, filtro command, logs de comando |
| **Aviso** | amber `#f59e0b` | backup en proceso, disco, protección |
| **Peligro** | rose `#f43f5e` | stop, offline, errores, disco bajo |
| Acento externo | `#5227FF` | **SÓLO** Stepper del wizard (excepción deliberada, ver §7) |

**Regla de oro:** los colores se usan con opacidad + borde + glow:
`bg-<c>-500/15..25` + `border-<c>-500/40..50` + `text-<c>-300/400` +
`shadow-[0_0_15..20px_rgba(<c>,0.25..0.3)]`. Nunca colores planos saturados
sobre el fondo.

## 3. Tipografía

- **Sans:** sans-serif del sistema (body). `Outfit` fue retirada el 2026-08-21: se declaraba en `index.css` pero nunca se cargó (sin `<link>` ni `@font-face`), así que la GUI siempre usó el fallback. Si algún día se quiere una fuente propia, bundlearla con `@fontsource` (la GUI corre en loopback y puede estar sin internet: nada de CDN).
- **Mono:** `font-mono` para *datos*: métricas (RAM/CPU/disco), timestamps de log, comandos, valores numéricos, prompt `>`.
- Escalas en uso:
  - H1 hero: `text-2xl font-extrabold` + gradiente `from-white via-emerald-200 to-cyan-300` (text-transparent bg-clip-text).
  - Números de métrica: `text-2xl font-extrabold` con `CountUp`.
  - Labels de campo/sección: `text-xs font-semibold uppercase tracking-wider text-slate-400`.
  - Cuerpo secundario: `text-xs text-slate-400/500`.
  - Terminal: `text-xs font-mono leading-relaxed`.

## 4. Superficies y radios

| Elemento | Receta |
|---|---|
| Card principal | `rounded-2xl border border-white/10 bg-slate-900/65 backdrop-blur-xl shadow-2xl` |
| Tarjeta de dato | `TiltCard` > `SpotlightCard` (spotlightColor = color semántico `rgba(c,0.18..0.2)`) |
| Modal | implementación canónica: `components/Modal.jsx` (portal a body) — overlay `fixed inset-0 z-50 bg-black/75 backdrop-blur-md` + card `rounded-2xl border border-<c>-500/40 bg-slate-950 p-6 shadow-2xl` |
| Input | `rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-xs ... focus:border-cyan-500/50` |
| Botón ghost | `rounded-xl border border-white/10 bg-white/5 text-slate-300 hover:bg-white/15` |
| Botón primario sólido | `bg-emerald-500 text-black border-emerald-400 hover:bg-emerald-400` + glow emerald — la acción principal de una botonera ("Iniciar", "Enviar" de la consola); texto plano, sin `ShinyText` (blanco no da contraste sobre el relleno) |
| Botón acción fuerte | gradiente `from-cyan-500 to-emerald-500` + texto negro + glow cyan |
| Botón variante | `rounded-xl border bg-<c>-500/20 border-<c>-500/50 text-<c>-300 hover:bg-<c>-500/30 shadow-glow` |
| Target táctil | `min-h-[44px]` en botones de formularios |
| Badge estado | `rounded-full border px-4 py-2 text-sm font-bold` + dot `h-2.5 w-2.5 rounded-full animate-pulse` con glow |
| Barra de progreso | `h-2 rounded-full bg-slate-950 border border-white/10` + relleno gradiente del color semántico |

**Estructura de modal (obligatoria):** usar `components/Modal.jsx`, que ya aporta la base (portal a body, `role="dialog"` + `aria-modal` + `aria-label`, cierre con Escape, foco inicial + restauración al cerrar, trampa de Tab, `overscroll-contain` y las animaciones de §6). El consumidor solo aporta el contenido: header con `border-b border-white/10 pb-4` (icono en caja `rounded-xl bg-<c>-500/20 border-<c>-500/40` + título bold + subtítulo `text-xs text-slate-400`), body con `space-y-*`, footer `border-t border-white/10 pt-4 flex justify-end gap-3`. No crear modales copia-pega fuera del componente.

## 5. Semántica por estado

| Estado | Color | Ejemplos |
|---|---|---|
| Online / éxito | emerald | badge ONLINE, start, send, verify ok, guardado ok |
| Offline / error | rose | badge OFFLINE, stop, errores de log, disco bajo |
| Proceso / aviso | amber | BACKUP EN PROCESO, disco, protección, avisos |
| Comando / acción terciaria | purple | restart, filtro command, logs `>` |
| Info / sistema | cyan | settings, filtro all, logs de sistema, backups |

**Log de terminal por tipo** (`TerminalConsole.getLogClass`):
join=emerald, leave=rose, backup=amber, system=cyan, command=purple, error=red con fondo `bg-red-950/40`.
Excepción: el tipo `session_start` no es una línea — se renderiza como divisor horizontal con label ("Logs de la sesión anterior"); llega tras el historial precargado en el `init` del WS y no se persiste.

## 6. Motion (framer-motion + ReactBits + Hover.dev)

- **Botones:** `whileHover scale 1.03`, `whileTap 0.94`, spring `{stiffness:400, damping:17}` + `ClickSpark` del color semántico.
- **Modales:** entrada `{scale:0.8, opacity:0, y:20}` → `{1,1,0}` spring `{stiffness:300, damping:20}`; overlay fade; cierre inverso (`AnimatePresence`).
- **Toggles:** knob con spring `{stiffness:500, damping:30}` + glow emerald cuando activo.
- **Decorativos (reactbits):** `ShinyText` en labels de acción/estado, `DecryptedText` en títulos, `CountUp` en métricas, `SideRays` (OGL) en fondo `top-right` intensidad 2 (`#EAB308`→`#96c8ff`), `Magnet` en CTA.
- **Tarjetas de dato:** `TiltCard` + `SpotlightCard`.
- **Reglas:** duraciones 200–500 ms; `transition duration-200/300` para hover de Tailwind (lista explícita de propiedades — **nunca `transition-all`**; para animar solo el ancho, `transition-[width]`); **respetar `prefers-reduced-motion`** (ya cubierto en `index.css`).
- **Iconos:** `lucide-react` para UI estática + `motion` animados propios (`hover/AnimatedIcons`, `HardwareMotionIcons`, `AnimatedStatusIcons`) con color semántico (`text-<c>-400`).

## 7. Excepción deliberada: Stepper del wizard (morado `#5227FF`)

El `Stepper` vendored de React Bits conserva su paleta original (`#5227FF`,
conectores `#52525b`, botón `next-button` morado) por decisión explícita.
Reglas para convivir con él:

- **No extender el morado `#5227FF` a otros componentes.** El proyecto usa
  violet `#8b5cf6` y purple `#a855f7`; `#5227FF` vive solo en el Stepper.
- El resto del wizard SÍ sigue la guía (card slate-950, border-white/10,
  inputs estándar, gradiente cyan→emerald en "Guardar", toggles ES/EN).
- Si algún día se normaliza, el cambio es: `#5227FF` → `#8b5cf6` (o `#a855f7`)
  en `Stepper.css` y en los `variants` de `StepIndicator`/`StepConnector`.

## 8. Reglas de coherencia para componentes futuros

1. **Todo texto visible** pasa por `t()` de `i18n.jsx` (ES + EN, misma clave, mismos placeholders) — salvo strings de terminal raw.
2. **Paleta:** usar tokens semánticos; cada cosa con color indica función, no decoración.
3. **Sin colores planos:** siempre `bg-<c>-500/xx` + borde + glow.
4. **Componentes vendored** (reactbits/hover.dev): adaptar a esta guía (import `framer-motion`, clases del tema) **salvo excepción explícita**; documentar la excepción aquí.
5. **Campos editables de server.properties:** definidos UNA vez en `propsFields.js`; backend valida con `PROPS_FIELDS` (mismas claves).
6. **Modal = `components/Modal.jsx`** (patrón de §4); botón primario a la derecha, cancelar ghost.
7. **Accesibilidad:** focus visible 2px emerald (`:focus-visible` ya global), targets ≥44px en formularios, `aria-label` en todo botón solo-icono (`title` no cuenta como nombre accesible), toggles con `role="switch"` + `aria-checked`, `aria-live="polite"` en regiones que se actualizan solas (terminal y banners de resultado/errores), spinners decorativos con `aria-hidden="true"`, y **confirmación obligatoria** (modal) para toda acción destructiva: stop, restart, restore, delete de backup, ban y rollback.
8. **Responsive:** dashboard `grid lg:grid-cols-[1fr_340px]`; sidebar colapsa a una columna en móvil; nada de scroll horizontal. La botonera de control es `grid grid-cols-2` en móvil y `lg:flex` a partir de desktop.
9. **Header:** las acciones secundarias (Configuración, Programación, Actualización BDS) viven en el menú "⋯ Más acciones" con trigger ghost neutro — el color del header queda reservado al estado del servidor. El indicador de latencia solo se muestra con el servidor corriendo.
