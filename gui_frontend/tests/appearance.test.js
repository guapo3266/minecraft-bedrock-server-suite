import { describe, expect, it } from 'vitest';
import { DEFAULTS, normalizeSettings, readSettings, resetBackground } from '../src/appearance/settings.js';
import { IMAGE_LIMITS, validateDimensions, validateImageFile } from '../src/appearance/imageStorage.js';
import { imageDimensions } from '../src/appearance/imageDimensions.js';
import { imageLayout } from '../src/appearance/imageLayout.js';
import { SAMPLE, compactPixels } from '../src/appearance/readabilitySamples.js';
import { contrast, protectionOpacity } from '../src/appearance/readability.js';

describe('preferencias de apariencia', () => {
  it('la transparencia inicial es 100 % sin desactivar lectura protegida', () => {
    expect(DEFAULTS.transparency).toBe(100);
    expect(DEFAULTS.readability).toBe(true);
  });
  it.each([null, undefined, [], 'dark', 42, true])('defaults ante datos no estructurados: %s', input => {
    expect(normalizeSettings(input)).toEqual(DEFAULTS);
  });
  it('recorta valores fuera del rango y descarta claves ajenas', () => {
    expect(normalizeSettings({ zoom: 10000, x: -100, y: 200, darkShade: 90, lightShade: -20, transparency: 140, command: 'stop' }))
      .toEqual({ ...DEFAULTS, zoom: 180, x: 0, y: 100, darkShade: 70, lightShade: 0, transparency: 100 });
  });
  it.each([NaN, Infinity, -Infinity, null, true, '75', {}])('no convierte valores corruptos a preferencias numéricas: %s', value => {
    expect(normalizeSettings({ zoom: value, transparency: value })).toEqual(DEFAULTS);
  });
  it('conserva todos los modos válidos', () => {
    const settings = { ...DEFAULTS, theme: 'light', fit: 'cover', backgroundMode: 'free', readability: false, effects: 'reduced', transparency: 0 };
    expect(normalizeSettings(settings)).toEqual(settings);
  });
  it.each(['{', 'null', '[]', '"texto"'])('localStorage corrupto: %s', json => {
    expect(readSettings({ getItem: () => json })).toEqual(DEFAULTS);
  });
  it('almacenamiento inaccesible y preferencia del SO', () => {
    expect(readSettings({ getItem: () => { throw new Error('blocked'); } }, true)).toEqual({ ...DEFAULTS, effects: 'reduced' });
  });
  it('restablece encuadre sin borrar transparencia, tema ni efectos', () => {
    const settings = { ...DEFAULTS, theme: 'light', transparency: 80, effects: 'reduced', backgroundMode: 'free', zoom: 180, fit: 'cover', x: 0, y: 100 };
    expect(resetBackground(settings)).toEqual({ ...settings, zoom: 100, fit: 'contain', x: 50, y: 50 });
  });
});

describe('imágenes locales: límites previos a la decodificación', () => {
  it.each(['image/jpeg', 'image/png', 'image/webp'])('acepta %s dentro del límite', type => {
    expect(() => validateImageFile({ type, size: IMAGE_LIMITS.bytes })).not.toThrow();
  });
  it.each(['image/svg+xml', 'image/gif', 'text/html', ''])('rechaza %s', type => {
    expect(() => validateImageFile({ type, size: 200 })).toThrow('appearanceImageTypeError');
  });
  it.each([0, IMAGE_LIMITS.bytes + 1])('rechaza el tamaño %s', size => {
    expect(() => validateImageFile({ type: 'image/png', size })).toThrow('appearanceImageSizeError');
  });
  it('rechaza cero, dimensiones no enteras y bombas de descompresión', () => {
    for (const [w, h] of [[0, 100], [100, 0], [1.5, 2], [-1, 100], [8001, 8000], [Infinity, 1]]) {
      expect(() => validateDimensions(w, h)).toThrow('appearanceImageDimensionsError');
    }
    expect(() => validateDimensions(8000, 8000)).not.toThrow();
  });
  it('lee PNG antes de reservar un bitmap', () => {
    const bytes = new Uint8Array(24);
    bytes.set([137, 80, 78, 71, 13, 10, 26, 10]);
    bytes.set([73, 72, 68, 82], 12);
    const view = new DataView(bytes.buffer);
    view.setUint32(16, 6000); view.setUint32(20, 4000);
    expect(imageDimensions(bytes.buffer)).toEqual([6000, 4000]);
  });
  it('lee JPEG SOF y WebP VP8X', () => {
    const jpeg = Uint8Array.from([255,216,255,192,0,8,8,1,44,2,88,0]);
    expect(imageDimensions(jpeg.buffer)).toEqual([600, 300]);
    const webp = new Uint8Array(30);
    webp.set([82,73,70,70], 0); webp.set([87,69,66,80,86,80,56,88], 8);
    new DataView(webp.buffer).setUint32(16, 10, true);
    webp[24] = 99; webp[27] = 49;
    expect(imageDimensions(webp.buffer)).toEqual([100, 50]);
  });
  it.each([0, 1, 4, 12, 20])('cabecera truncada de %s bytes', length => {
    expect(() => imageDimensions(new Uint8Array(length).buffer)).toThrow('appearanceImageDecodeError');
  });
});

describe('encuadre: equivalencia con contain/cover del origen', () => {
  it('contain muestra la imagen entera y cover llena la pantalla', () => {
    expect(imageLayout(1000, 500, 500, 500, DEFAULTS)).toEqual({ x: 250, y: 0, width: 500, height: 500 });
    expect(imageLayout(1000, 500, 500, 500, { ...DEFAULTS, fit: 'cover' })).toEqual({ x: 0, y: -250, width: 1000, height: 1000 });
  });
  it('zoom relativo al ajuste y posición en los extremos', () => {
    for (const fit of ['contain', 'cover']) for (const x of [0, 50, 100]) for (const y of [0, 50, 100]) {
      const normal = imageLayout(1200, 800, 1600, 900, { ...DEFAULTS, fit, x, y });
      const half = imageLayout(1200, 800, 1600, 900, { ...DEFAULTS, fit, x, y, zoom: 50 });
      expect(half.width).toBe(normal.width / 2); expect(half.height).toBe(normal.height / 2);
      expect(half.x).toBe((1200 - half.width) * x / 100); expect(half.y).toBe((800 - half.height) * y / 100);
    }
  });
});

describe('lectura protegida: no suavizar píxeles extremos hasta ocultarlos', () => {
  it('cada tile conserva su mínimo y máximo, incluso un píxel aislado', () => {
    const rgba = new Uint8ClampedArray(SAMPLE.width * SAMPLE.height * 4).fill(120);
    rgba.set([255, 255, 255, 255], 0); rgba.set([0, 0, 0, 255], 4);
    const compact = compactPixels(rgba);
    expect([...compact.slice(0, 6)]).toEqual([0, 0, 0, 255, 255, 255]);
    expect([...compact.slice(6, 12)]).toEqual([120, 120, 120, 120, 120, 120]);
  });
  it('contraste blanco/negro y simetría', () => {
    expect(contrast([0, 0, 0], [255, 255, 255])).toBe(21);
    expect(contrast([40, 60, 80], [100, 160, 220])).toBe(contrast([100, 160, 220], [40, 60, 80]));
  });
  it('fondo blanco en oscuro y fondo negro en claro mantienen 4.5:1', () => {
    const themes = [
      { dark: true, pixel: [255,255,255], foregrounds: ['f7f7f7','e0e0e0','d0d0d0','b7f3fa','b1f5ce','ffd0d4','ffe8bf'] },
      { dark: false, pixel: [0,0,0], foregrounds: ['171717','303030','3d3d3d','064d60','064b31','851c2d','604013'] }
    ];
    for (const { dark, pixel, foregrounds: hexes } of themes) {
      const foregrounds = hexes.map(hex => [0,2,4].map(i => parseInt(hex.slice(i, i + 2), 16)));
      const alpha = protectionOpacity(pixel, foregrounds, dark);
      expect(alpha).toBeGreaterThanOrEqual(.1); expect(alpha).toBeLessThanOrEqual(dark ? .75 : .85);
      const bg = pixel.map(value => (value * (1 - alpha) + (dark ? 20 : 255) * alpha) * .94 + 255 * .06);
      foregrounds.forEach(foreground => expect(contrast(foreground, bg)).toBeGreaterThanOrEqual(4.5));
    }
  });
});
