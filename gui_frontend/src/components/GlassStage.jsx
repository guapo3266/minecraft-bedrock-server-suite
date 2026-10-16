import { useEffect, useRef } from 'react'
import { paintBackground } from '../appearance/background'
import { createReadability } from '../appearance/readability'

const CONFIGS = [
  { refraction: 0.55, blurAmount: 0.25, chromAberration: 0.04, edgeHighlight: 0.12, specular: 0.35, fresnel: 1.1, zRadius: 35 },
  { refraction: 0.8, blurAmount: 0.2, chromAberration: 0.06, edgeHighlight: 0.18, specular: 0.45, fresnel: 1.2, zRadius: 40 },
].map(c => ({ ...c, tintStrength: 0, cornerRadius: 24, distortion: 0, floating: false, button: false }))


export default function GlassStage({ settings, imageUrl, headerRef, dockRef, onStatus, layoutKey }) {
  const rootRef = useRef(null), canvasRef = useRef(null), topRef = useRef(null), bottomRef = useRef(null)
  const engine = useRef(null), image = useRef(null), scheduleRef = useRef(null)
  const settingsRef = useRef(settings)
  const { zoom, x, y, darkShade, lightShade, fit, theme, backgroundMode } = settings
  useEffect(() => {
    settingsRef.current = { zoom, x, y, darkShade, lightShade, fit, theme, backgroundMode }
    scheduleRef.current?.()
  }, [zoom, x, y, darkShade, lightShade, fit, theme, backgroundMode])
  useEffect(() => {
    let active = true
    image.current = null
    if (!imageUrl) { scheduleRef.current?.(); return }
    const next = new Image()
    next.onload = () => { if (active) { image.current = next; scheduleRef.current?.() } }
    next.onerror = () => { if (active) scheduleRef.current?.() }
    next.src = imageUrl
    return () => { active = false }
  }, [imageUrl])
  useEffect(() => {
    let frame = 0
    const draw = () => {
      frame = 0
      paintBackground(canvasRef.current, settingsRef.current, image.current)
      const rootBox = rootRef.current.getBoundingClientRect()
      for (const [target, surface] of [[headerRef.current, topRef.current], [dockRef.current, bottomRef.current]]) {
        if (!target || !surface) continue
        const rect = target.getBoundingClientRect()
        surface.hidden = !rect.width || !rect.height
        if (target === headerRef.current) document.documentElement.style.setProperty('--header-bottom', `${rect.bottom}px`)
        Object.assign(surface.style, { left: `${rect.left - rootBox.left}px`, top: `${rect.top - rootBox.top}px`, width: `${rect.width}px`, height: `${rect.height}px` })
      }
      engine.current?.markChanged(canvasRef.current)
      engine.current?.markChanged()
      rootRef.current.dispatchEvent(new Event('suite-backdrop-change'))
    }
    const schedule = () => { if (!frame) frame = requestAnimationFrame(draw) }
    scheduleRef.current = schedule
    const observer = new ResizeObserver(schedule)
    if (headerRef.current) observer.observe(headerRef.current)
    if (dockRef.current) observer.observe(dockRef.current)
    observer.observe(rootRef.current)
    window.addEventListener('resize', schedule)
    draw()
    return () => { observer.disconnect(); window.removeEventListener('resize', schedule); cancelAnimationFrame(frame); scheduleRef.current = null }
  }, [headerRef, dockRef, layoutKey])
  useEffect(() => {
    const controller = createReadability(rootRef.current, canvasRef.current, settings.readability, settings.theme)
    return () => controller.destroy()
  }, [settings.readability, settings.theme])
  useEffect(() => {
    if (settings.effects === 'reduced') { onStatus('reduced'); return }
    let canceled = false, instance = null, timer = 0
    const dispose = () => { instance?.destroy(); if (engine.current === instance) engine.current = null }
    const visibility = () => { if (document.hidden) instance?.pause(); else instance?.resume() }
    const lost = () => {
      if (canceled) return
      canceled = true; clearTimeout(timer)
      document.removeEventListener('visibilitychange', visibility)
      instance?.renderer.canvas.removeEventListener('webglcontextlost', lost)
      dispose(); onStatus('fallback')
    }
    onStatus('loading')
    timer = setTimeout(lost, 3000)
    import('../vendor/liquidglass').then(async ({ LiquidGlass }) => {
      if (canceled) return
      instance = new LiquidGlass({ root: rootRef.current, glassElements: [topRef.current, bottomRef.current].filter(surface => !surface.hidden) })
      engine.current = instance
      await instance.start()
      if (canceled) { dispose(); return }
      clearTimeout(timer)
      instance.renderer.canvas.addEventListener('webglcontextlost', lost)
      document.addEventListener('visibilitychange', visibility)
      visibility(); scheduleRef.current?.(); onStatus('ready')
    }).catch(() => { if (!canceled) lost() })
    return () => {
      canceled = true; clearTimeout(timer)
      document.removeEventListener('visibilitychange', visibility)
      instance?.renderer.canvas.removeEventListener('webglcontextlost', lost)
      dispose()
    }
  }, [settings.effects, onStatus, layoutKey])
  return <div className="glass-stage" ref={rootRef} aria-hidden="true"><canvas ref={canvasRef}/><div className="glass-surface" ref={topRef} data-config={JSON.stringify(CONFIGS[0])}/><div className="glass-surface" ref={bottomRef} data-config={JSON.stringify(CONFIGS[1])}/></div>
}
