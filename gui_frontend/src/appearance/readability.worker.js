// Only decorative bitmap snapshots enter this worker, never DOM content.
import { SAMPLE, compactPixels } from './readabilitySamples.js'
const canvas = new OffscreenCanvas(SAMPLE.width, SAMPLE.height)
const context = canvas.getContext('2d', { willReadFrequently: true })
self.onmessage = ({ data: { id, layers } }) => {
  const started = performance.now()
  try {
    context.clearRect(0, 0, canvas.width, canvas.height)
    for (const { bitmap, x, y, width, height } of layers) context.drawImage(bitmap, x, y, width, height)
    const pixels = compactPixels(context.getImageData(0, 0, canvas.width, canvas.height).data)
    self.postMessage({ id, pixels, duration: performance.now() - started }, [pixels.buffer])
  } catch {
    self.postMessage({ id, failed: true })
  } finally {
    for (const { bitmap } of layers) bitmap.close()
  }
}
