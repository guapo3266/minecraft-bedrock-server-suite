import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { LanguageProvider, STRINGS } from '../src/i18n.jsx';
import AboutModal from '../src/components/AboutModal.jsx';
import { version } from '../../version.json';

vi.mock('../src/components/Modal', () => ({
  default: ({ children }) => <section>{children}</section>
}));

afterEach(() => vi.unstubAllGlobals());

describe('versión de la suite en Acerca de', () => {
  for (const lang of ['es', 'en']) {
    it(`muestra la versión del manifiesto con su etiqueta ${lang}`, () => {
      vi.stubGlobal('localStorage', { getItem: () => lang });
      const html = renderToStaticMarkup(<LanguageProvider><AboutModal onClose={() => {}} /></LanguageProvider>);
      expect(html).toContain(STRINGS[lang].suiteVersion);
      expect(html).toContain(`<strong>${version}</strong>`);
      expect(html).toContain('Minecraft Bedrock Server Suite');
      expect(html).toContain('Not an official Minecraft product.');
    });
  }
});
