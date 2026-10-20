import { SAMPLE, compactPixels } from './readabilitySamples.js'
const COLORS = ['text', 'muted', 'muted-2', 'acc', 'green', 'red', 'amber']
export const luminance = rgb => rgb.reduce((sum, value, i) => {
  const s = value / 255
  return sum + (s <= .04045 ? s / 12.92 : ((s + .055) / 1.055) ** 2.4) * [.2126, .7152, .0722][i]
}, 0)
export const contrast = (a, b) => (Math.max(luminance(a), luminance(b)) + .05) / (Math.min(luminance(a), luminance(b)) + .05)
export function protectionOpacity(pixel, foregrounds, dark) {
  const neutral = dark ? 20 : 255, max = dark ? .75 : .85
  // Reserve room for the two subtle white reflections on a panel and control.
  const composed = alpha => pixel.map(value => (value * (1 - alpha) + neutral * alpha) * .94 + 255 * .06)
  const acceptable = alpha => {
    const bg = composed(alpha), light = luminance(bg)
    return foregrounds.every(fg => (dark ? light < luminance(fg) : light > luminance(fg)) && contrast(fg, bg) >= 4.5)
  }
  if (acceptable(.1)) return .1
  let low = .1, high = max
  for (let i = 0; i < 12; i++) { const mid = (low + high) / 2; if (acceptable(mid)) high = mid; else low = mid }
  return Math.min(max, Math.ceil(high * 1000) / 1000)
}

export function createReadability(stage, backdrop, enabled, theme) {
  const root = document.documentElement, dark = theme === 'dark'
  const bodySelector = '.panel, .stat, .section-heading, .notice'
  const floatingSelector = '.glass-menu, .dialog, .toast'
  const sample = document.createElement('canvas')
  sample.width = SAMPLE.width; sample.height = SAMPLE.height
  const ctx = sample.getContext('2d', { willReadFrequently: true })
  let pixels = null, frame = 0, dirty = true, stopped = false
  let worker = null, pending = false, revision = 0, captureStarted = 0
  const floating = new Set(), watched = new Set()
  const metrics = { analyses: 0, samples: 0, durations: [], phases: [], captures: [], pending: false }
  stage.readabilityMetrics = metrics
  let foregrounds = null
  const maximum = dark ? .75 : .85
  const set = (element, name, value) => {
    const text = String(value)
    if (element.style.getPropertyValue(name) !== text) element.style.setProperty(name, text)
  }
  const layers = () => {
    const result = [{ canvas: backdrop, x: 0, y: 0, width: sample.width, height: sample.height }]
    // The shader has already copied its output into these decorative 2D canvases.
    // No DOM text, forms, passwords or WebGL readPixels call enters this sample.
    for (const canvas of stage.querySelectorAll('.glass-surface canvas')) {
      const r = canvas.getBoundingClientRect()
      if (r.width && r.height) result.push({ canvas, x: r.left / innerWidth * sample.width, y: r.top / innerHeight * sample.height, width: r.width / innerWidth * sample.width, height: r.height / innerHeight * sample.height })
    }
    return result
  }
  try {
    if (enabled && typeof OffscreenCanvas !== 'undefined' && typeof createImageBitmap === 'function') {
      worker = new Worker(new URL('./readability.worker.js', import.meta.url), { type: 'module' })
      worker.onmessage = ({ data }) => {
        if (stopped || !worker) return
        pending = metrics.pending = false
        metrics.captures.push({ wall: performance.now() - captureStarted, worker: data.duration || 0 })
        if (metrics.captures.length > 120) metrics.captures.shift()
        if (data.failed) { worker.terminate(); worker = null; dirty = true }
        else if (data.id === revision) { pixels = data.pixels; dirty = false; metrics.samples++ }
        schedule()
      }
      worker.onerror = event => {
        event.preventDefault()
        if (stopped) return
        worker?.terminate(); worker = null; pending = metrics.pending = false; schedule()
      }
    }
  } catch { worker = null }
  const capture = () => {
    if (pending) return
    if (!worker) {
      ctx.clearRect(0, 0, sample.width, sample.height)
      for (const { canvas, x, y, width, height } of layers()) ctx.drawImage(canvas, x, y, width, height)
      pixels = compactPixels(ctx.getImageData(0, 0, sample.width, sample.height).data)
      dirty = false; metrics.samples++
      return
    }
    pending = metrics.pending = true; captureStarted = performance.now()
    const id = revision
    // GPU readback can be slow on software WebGL. Do it off the UI thread.
    // The single in-flight capture coalesces rapid background changes.
    const snapshots = layers().map(async ({ canvas, ...rect }) => ({ ...rect, bitmap: await createImageBitmap(canvas) }))
    Promise.allSettled(snapshots).then(results => {
      const ready = results.filter(r => r.status === 'fulfilled').map(r => r.value)
      if (stopped || !worker || ready.length !== results.length) {
        for (const { bitmap } of ready) bitmap.close()
        if (!stopped) { pending = metrics.pending = false; worker?.terminate(); worker = null; schedule() }
        return
      }
      try { worker.postMessage({ id, layers: ready }, ready.map(layer => layer.bitmap)) }
      catch {
        for (const { bitmap } of ready) bitmap.close()
        pending = metrics.pending = false; worker.terminate(); worker = null; schedule()
      }
    })
  }
  const extrema = (elements, inset = 8) => {
    const result = dark ? [0, 0, 0] : [255, 255, 255]
    const clip = document.querySelector('.main-content')?.getBoundingClientRect()
    for (const element of elements) {
      if (!element.getClientRects().length) continue
      const r = element.getBoundingClientRect(), inMain = element.closest('.main-content')
      const left = Math.max(0, r.left + inset), right = Math.min(innerWidth, r.right - inset)
      const top = Math.max(0, r.top + inset, inMain && clip ? clip.top : 0)
      const bottom = Math.min(innerHeight, r.bottom - inset, inMain && clip ? clip.bottom : innerHeight)
      if (left >= right || top >= bottom) continue
      const x1 = Math.max(0, Math.floor(left / innerWidth * SAMPLE.columns)), x2 = Math.min(SAMPLE.columns, Math.ceil(right / innerWidth * SAMPLE.columns))
      const y1 = Math.max(0, Math.floor(top / innerHeight * SAMPLE.rows)), y2 = Math.min(SAMPLE.rows, Math.ceil(bottom / innerHeight * SAMPLE.rows))
      for (let y = y1; y < y2; y++) for (let x = x1; x < x2; x++) {
        const offset = (y * SAMPLE.columns + x) * 6 + (dark ? 3 : 0)
        for (let c = 0; c < 3; c++) result[c] = dark ? Math.max(result[c], pixels[offset + c]) : Math.min(result[c], pixels[offset + c])
      }
    }
    return result
  }
  const observer = new ResizeObserver(() => schedule())
  const syncGeometry = () => {
    const nodes = new Set(document.querySelectorAll(`${bodySelector}, ${floatingSelector}, .app-header, .dock`))
    for (const node of watched) if (!nodes.has(node)) {
      observer.unobserve(node); watched.delete(node); floating.delete(node)
      node.style.removeProperty('--reading-floating')
    }
    for (const node of nodes) if (!watched.has(node)) { observer.observe(node); watched.add(node) }
    return nodes
  }
  const analyse = () => {
    frame = 0
    if (stopped || document.hidden) return
    const started = performance.now()
    if (!foregrounds) {
      const css = getComputedStyle(root)
      foregrounds = COLORS.map(key => {
        const hex = css.getPropertyValue(`--${key}`).trim()
        return [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16))
      })
    }
    const nodes = syncGeometry()
    const prepared = performance.now()
    let captured = prepared
    try {
      if (enabled && (dirty || !pixels)) capture()
      captured = performance.now()
      const alpha = elements => enabled ? (pixels ? protectionOpacity(extrema(elements), foregrounds, dark) : maximum) : 0
      // Finish every geometry read before changing any root CSS variable.
      // Interleaving those operations forces expensive style/layout flushes.
      const body = alpha([...nodes].filter(n => n.matches(bodySelector)))
      const header = enabled ? (pixels ? protectionOpacity(extrema(document.querySelectorAll('.app-header'), 16), foregrounds, dark) : maximum) : 0
      const dock = enabled ? (pixels ? protectionOpacity(extrema(document.querySelectorAll('.dock'), 16), foregrounds, dark) : maximum) : 0
      const floats = [...nodes].filter(n => n.matches(floatingSelector)).map(node => [node, alpha([node])])
      set(root, '--reading-body', body)
      set(root, '--reading-header', header)
      set(root, '--reading-dock', dock)
      for (const [node, value] of floats) { floating.add(node); set(node, '--reading-floating', value) }
    } catch {
      // Conservative neutral fallback if local canvas sampling is unavailable.
      for (const key of ['body', 'header', 'dock']) set(root, `--reading-${key}`, enabled ? maximum : 0)
      for (const node of nodes) if (node.matches(floatingSelector)) { floating.add(node); set(node, '--reading-floating', enabled ? maximum : 0) }
    }
    metrics.analyses++
    metrics.durations.push(performance.now() - started)
    metrics.phases.push({ prepare: prepared - started, capture: captured - prepared, contrast: performance.now() - captured })
    if (metrics.durations.length > 120) metrics.durations.shift()
    if (metrics.phases.length > 120) metrics.phases.shift()
  }
  const schedule = () => { if (!stopped && !frame && !document.hidden) frame = requestAnimationFrame(analyse) }
  const backdropChanged = () => { revision++; dirty = true; pixels = null; schedule() }
  const mutation = new MutationObserver(records => {
    if (records.some(record => stage.contains(record.target))) { revision++; dirty = true; pixels = null }
    schedule()
  })
  mutation.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['hidden'] })
  stage.addEventListener('suite-backdrop-change', backdropChanged)
  stage.addEventListener('suite-glass-frame', backdropChanged)
  window.addEventListener('resize', backdropChanged)
  window.addEventListener('scroll', schedule, true)
  document.addEventListener('visibilitychange', schedule)
  schedule()
  return { destroy() {
    stopped = true; cancelAnimationFrame(frame); observer.disconnect(); mutation.disconnect()
    worker?.terminate(); worker = null
    stage.removeEventListener('suite-backdrop-change', backdropChanged); stage.removeEventListener('suite-glass-frame', backdropChanged)
    window.removeEventListener('resize', backdropChanged); window.removeEventListener('scroll', schedule, true)
    document.removeEventListener('visibilitychange', schedule)
    for (const key of ['body', 'header', 'dock']) root.style.removeProperty(`--reading-${key}`)
    for (const node of floating) node.style.removeProperty('--reading-floating')
    if (stage.readabilityMetrics === metrics) delete stage.readabilityMetrics
  } }
}
