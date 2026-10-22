// Reglas de navegacion del asistente de primera configuracion (sin jsdom).
import { describe, expect, it } from 'vitest';
import { pasoMaximo, ultimoPaso } from '../src/setupLogic.js';

describe('ultimoPaso', () => {
  it('el paso de instalar BDS solo existe si faltaba al abrir el asistente', () => {
    expect(ultimoPaso(true)).toBe(2);
    expect(ultimoPaso(false)).toBe(3);
  });
});

describe('pasoMaximo (indicadores a los que se puede saltar)', () => {
  it('sin guardar la configuracion solo se puede estar en el paso 1', () => {
    expect(pasoMaximo({ saved: false, installed: false, bdsInstalled: false })).toBe(1);
    expect(pasoMaximo({ saved: false, installed: true, bdsInstalled: true })).toBe(1);
  });

  it('sin BDS no se puede saltar al final', () => {
    expect(pasoMaximo({ saved: true, installed: false, bdsInstalled: false })).toBe(2);
  });

  it('con la configuracion guardada y BDS instalado se llega al final', () => {
    expect(pasoMaximo({ saved: true, installed: true, bdsInstalled: false })).toBe(3);
    expect(pasoMaximo({ saved: true, installed: false, bdsInstalled: true })).toBe(2);
    expect(pasoMaximo({ saved: true, installed: true, bdsInstalled: true })).toBe(2);
  });
});
