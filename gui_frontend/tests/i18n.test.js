// Tests de lógica pura del diccionario i18n (sin jsdom): completitud y
// simetría ES/EN. Si alguien añade una clave a un idioma y olvida el otro,
// este test falla antes de que llegue a producción como texto sin traducir.
import { describe, expect, it } from 'vitest';
import { STRINGS } from '../src/i18n.jsx';

const LOCALES = ['es', 'en'];

describe('diccionario i18n ES/EN', () => {
  it('expone los idiomas es y en con claves', () => {
    for (const locale of LOCALES) {
      expect(typeof STRINGS[locale]).toBe('object');
      expect(Object.keys(STRINGS[locale]).length).toBeGreaterThan(0);
    }
  });

  it('toda clave de un idioma existe en el otro (simetría)', () => {
    const esKeys = Object.keys(STRINGS.es);
    const enKeys = Object.keys(STRINGS.en);
    const missingInEn = esKeys.filter((k) => !Object.hasOwn(STRINGS.en, k));
    const missingInEs = enKeys.filter((k) => !Object.hasOwn(STRINGS.es, k));
    expect({ missingInEn, missingInEs }).toEqual({ missingInEn: [], missingInEs: [] });
  });

  it('no hay claves con valores vacíos o no-string', () => {
    for (const locale of LOCALES) {
      const bad = Object.entries(STRINGS[locale])
        .filter(([, v]) => typeof v !== 'string' || v.trim() === '')
        .map(([k]) => k);
      expect({ locale, bad }).toEqual({ locale, bad: [] });
    }
  });

  it('los placeholders {var} coinciden entre ES y EN', () => {
    const placeholders = (s) => (s.match(/\{[a-zA-Z0-9_]+\}/g) || []).sort();
    const mismatched = Object.keys(STRINGS.es)
      .filter((k) => Object.hasOwn(STRINGS.en, k))
      .filter((k) => placeholders(STRINGS.es[k]).join(',') !== placeholders(STRINGS.en[k]).join(','))
      .map((k) => ({ key: k, es: placeholders(STRINGS.es[k]), en: placeholders(STRINGS.en[k]) }));
    expect(mismatched).toEqual([]);
  });
});
