// Sistema visual adaptado de Nokia WiFi Manager. Claves propias: las
// preferencias de ambas aplicaciones nunca se mezclan en el mismo navegador.
export const SETTINGS_KEY = 'bedrock-appearance';
export const IMAGE_DB = 'bedrock-appearance';
export const DEFAULTS = Object.freeze({
  zoom: 100, x: 50, y: 50, darkShade: 35, lightShade: 15, transparency: 100,
  backgroundMode: 'integrated', readability: true, fit: 'contain',
  theme: 'dark', effects: 'full'
});

const LIMITS = {
  zoom: [25, 180], x: [0, 100], y: [0, 100],
  darkShade: [0, 70], lightShade: [0, 70], transparency: [0, 100]
};

export function normalizeSettings(saved, reducedMotion = false) {
  const source = saved && typeof saved === 'object' && !Array.isArray(saved) ? saved : {};
  const numbers = Object.fromEntries(Object.entries(LIMITS).map(([key, [min, max]]) => {
    const value = source[key];
    return [key, typeof value === 'number' && Number.isFinite(value)
      ? Math.max(min, Math.min(max, value)) : DEFAULTS[key]];
  }));
  return {
    ...numbers,
    backgroundMode: source.backgroundMode === 'free' ? 'free' : 'integrated',
    readability: source.readability !== false,
    fit: source.fit === 'cover' ? 'cover' : 'contain',
    theme: source.theme === 'light' ? 'light' : 'dark',
    effects: source.effects === 'reduced' || (!source.effects && reducedMotion) ? 'reduced' : 'full'
  };
}

export function readSettings(storage, reducedMotion = false) {
  try { return normalizeSettings(JSON.parse(storage.getItem(SETTINGS_KEY) || '{}'), reducedMotion); }
  catch { return normalizeSettings(null, reducedMotion); }
}

// Restablecer fondo no altera tema, transparencia, efectos ni lectura protegida.
export function resetBackground(settings) {
  return { ...settings, zoom: 100, x: 50, y: 50, darkShade: 35, lightShade: 15, fit: 'contain' };
}
