import { imageLayout } from './imageLayout'

const layers = new WeakMap()
function drawFeatheredImage(canvas, ctx, image, frame, width, height, dpr) {
  let layer = layers.get(canvas)
  if (!layer) { layer = document.createElement('canvas'); layers.set(canvas, layer) }
  layer.width = canvas.width; layer.height = canvas.height
  const lc = layer.getContext('2d')
  lc.scale(dpr, dpr)
  lc.drawImage(image, frame.x, frame.y, frame.width, frame.height)
  const edge = Math.min(80, Math.max(16, Math.min(frame.width, frame.height) * .08))
  lc.globalCompositeOperation = 'destination-in'
  for (const [x1,y1,x2,y2,start,end] of [
    [frame.x,0,frame.x+edge,0,0,1], [frame.x+frame.width-edge,0,frame.x+frame.width,0,1,0],
    [0,frame.y,0,frame.y+edge,0,1], [0,frame.y+frame.height-edge,0,frame.y+frame.height,1,0],
  ]) {
    const mask = lc.createLinearGradient(x1,y1,x2,y2)
    mask.addColorStop(0, `rgba(0,0,0,${start})`); mask.addColorStop(1, `rgba(0,0,0,${end})`)
    lc.fillStyle = mask; lc.fillRect(0,0,width,height)
  }
  ctx.drawImage(layer, 0, 0, width, height)
}

export function paintBackground(canvas, settings, image) {
  const width = window.innerWidth, height = window.innerHeight, dpr = Math.min(window.devicePixelRatio || 1, 2)
  canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr)
  const ctx = canvas.getContext('2d')
  ctx.scale(dpr, dpr)
  const dark = settings.theme === 'dark'
  ctx.fillStyle = image ? (dark ? '#141414' : '#e7e7e7') : (dark ? '#081820' : '#dcebf1'); ctx.fillRect(0, 0, width, height)
  if (image) {
    const frame = imageLayout(width, height, image.width, image.height, settings)
    if (settings.backgroundMode === 'free') ctx.drawImage(image, frame.x, frame.y, frame.width, frame.height)
    else drawFeatheredImage(canvas, ctx, image, frame, width, height, dpr)
  } else {
    const clouds = dark
      ? [[0.04, 0.03, '#256776'], [0.96, 0.28, '#153449'], [0.7, 1.05, '#327875']]
      : [[0.04, 0.03, '#a5dce7'], [0.96, 0.28, '#c2cbed'], [0.7, 1.05, '#92c8c1']]
    for (const [x, y, color] of clouds) {
      const g = ctx.createRadialGradient(width * x, height * y, 0, width * x, height * y, width * 0.75)
      g.addColorStop(0, color); g.addColorStop(1, 'transparent'); ctx.fillStyle = g; ctx.fillRect(0, 0, width, height)
    }
    ctx.save(); ctx.translate(width * 0.85, height * 0.45); ctx.rotate(-0.5)
    for (let i = 0; i < 7; i++) {
      ctx.strokeStyle = dark ? `rgba(163,229,227,${0.07 - i * 0.006})` : `rgba(34,95,116,${0.1 - i * 0.008})`
      ctx.lineWidth = 1; ctx.beginPath(); ctx.ellipse(0, 0, width * (0.32 + i * 0.045), height * (0.2 + i * 0.04), 0, 0, Math.PI * 2); ctx.stroke()
    }
    ctx.restore()
  }
  if (settings.backgroundMode !== 'free') {
    const color = dark ? '20,20,20' : '231,231,231'
    const fade = ctx.createLinearGradient(0, 0, 0, height)
    for (const [offset, alpha] of [[0, .02], [.25, .15], [.55, .62], [.85, .94], [1, 1]]) {
      fade.addColorStop(offset, `rgba(${color},${alpha})`)
    }
    ctx.fillStyle = fade; ctx.fillRect(0, 0, width, height)
  }
  ctx.fillStyle = `rgba(0,0,0,${(dark ? settings.darkShade : settings.lightShade) / 100})`; ctx.fillRect(0, 0, width, height)
  if (!image) {
    const vignette = ctx.createRadialGradient(width / 2, height / 3, 0, width / 2, height / 3, Math.max(width, height) * 0.9)
    vignette.addColorStop(0, 'transparent'); vignette.addColorStop(1, dark ? 'rgba(0,0,0,.45)' : 'rgba(255,255,255,.35)')
    ctx.fillStyle = vignette; ctx.fillRect(0, 0, width, height)
  }
}
