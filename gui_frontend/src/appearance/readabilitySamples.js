export const SAMPLE = { width: 160, height: 100, tile: 4, columns: 40, rows: 25 }

// Keep both extrema in every tile: compression cannot hide a bright/dark pixel.
export function compactPixels(rgba) {
  const tiles = new Uint8Array(SAMPLE.columns * SAMPLE.rows * 6)
  for (let i = 0; i < tiles.length; i += 6) tiles.fill(255, i, i + 3)
  for (let y = 0; y < SAMPLE.height; y++) for (let x = 0; x < SAMPLE.width; x++) {
    const source = (y * SAMPLE.width + x) * 4
    const target = (Math.floor(y / SAMPLE.tile) * SAMPLE.columns + Math.floor(x / SAMPLE.tile)) * 6
    for (let c = 0; c < 3; c++) {
      tiles[target + c] = Math.min(tiles[target + c], rgba[source + c])
      tiles[target + c + 3] = Math.max(tiles[target + c + 3], rgba[source + c])
    }
  }
  return tiles
}
