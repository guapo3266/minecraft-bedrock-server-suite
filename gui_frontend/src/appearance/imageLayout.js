// Zoom is relative to the chosen fit, not to the source image's pixel size.
export function imageLayout(width, height, imageWidth, imageHeight, settings) {
  const fit = settings.fit === 'cover' ? Math.max : Math.min
  const ratio = fit(width / imageWidth, height / imageHeight) * settings.zoom / 100
  const w = imageWidth * ratio, h = imageHeight * ratio
  return { x: (width - w) * settings.x / 100, y: (height - h) * settings.y / 100, width: w, height: h }
}
