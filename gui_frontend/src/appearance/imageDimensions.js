// Lee cabeceras antes de decodificar: un archivo comprimido pequeño puede
// reservar cientos de MB al convertirse en bitmap.
export function imageDimensions(buffer) {
  const bytes = new Uint8Array(buffer), view = new DataView(buffer)
  const tag = offset => String.fromCharCode(...bytes.slice(offset, offset + 4))
  const le24 = offset => bytes[offset] | bytes[offset + 1] << 8 | bytes[offset + 2] << 16
  if (bytes.length >= 24 && bytes[0] === 137 && tag(1) === 'PNG\r' && tag(12) === 'IHDR') {
    return [view.getUint32(16), view.getUint32(20)]
  }
  if (bytes.length >= 12 && tag(0) === 'RIFF' && tag(8) === 'WEBP') {
    for (let chunk = 12; chunk + 8 <= bytes.length;) {
      const type = tag(chunk), length = view.getUint32(chunk + 4, true), data = chunk + 8
      if (data + length > bytes.length) break
      if (type === 'VP8X' && length >= 10) return [le24(data + 4) + 1, le24(data + 7) + 1]
      if (type === 'VP8L' && length >= 5 && bytes[data] === 47) {
        const bits = view.getUint32(data + 1, true)
        return [(bits & 0x3fff) + 1, ((bits >>> 14) & 0x3fff) + 1]
      }
      if (type === 'VP8 ' && length >= 10 && bytes[data + 3] === 157 && bytes[data + 4] === 1 && bytes[data + 5] === 42) {
        return [view.getUint16(data + 6, true) & 0x3fff, view.getUint16(data + 8, true) & 0x3fff]
      }
      chunk = data + length + (length % 2)
    }
  }
  if (bytes.length >= 4 && bytes[0] === 255 && bytes[1] === 216) {
    let offset = 2
    while (offset + 3 < bytes.length && bytes[offset] === 255) {
      while (bytes[offset] === 255) offset++
      const marker = bytes[offset++]
      if (marker === 217 || marker === 218) break
      if (marker === 1 || (marker >= 208 && marker <= 215)) continue
      if (offset + 2 > bytes.length) break
      const length = view.getUint16(offset)
      if (length < 2 || offset + length > bytes.length) break
      if ([192, 193, 194, 195, 197, 198, 199, 201, 202, 203, 205, 206, 207].includes(marker) && length >= 8) {
        return [view.getUint16(offset + 5), view.getUint16(offset + 3)]
      }
      offset += length
    }
  }
  throw new Error('appearanceImageDecodeError')
}
