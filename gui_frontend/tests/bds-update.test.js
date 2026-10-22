// Cierre del dialogo de actualizar/revertir BDS (sin jsdom).
import { describe, expect, it } from 'vitest';
import { crearSeguimientoBds } from '../src/bdsUpdateLogic.js';

describe('crearSeguimientoBds', () => {
  it('cierra al ver el flag pasar de true a false', () => {
    const s = crearSeguimientoBds();
    s.iniciar();
    expect(s.estado(true)).toBe(false);
    expect(s.estado(true)).toBe(false); // otros estados durante la operacion
    expect(s.estado(false)).toBe(true);
    expect(s.estado(false)).toBe(false); // una sola vez
  });

  it('reabrir el dialogo durante la operacion no la olvida', () => {
    // El fallo original: reabrir el modal borraba la marca de "vista empezar".
    // Aqui el seguimiento no depende del modal: la vio empezar y la ve acabar.
    const s = crearSeguimientoBds();
    expect(s.estado(true)).toBe(false);
    expect(s.estado(false)).toBe(true);
  });

  it('una operacion de otra pestana tambien cierra el dialogo al terminar', () => {
    const s = crearSeguimientoBds();
    expect(s.estado(false)).toBe(false);
    expect(s.estado(true)).toBe(false);
    expect(s.estado(false)).toBe(true);
  });

  it('con el WebSocket caido, /api/status y el estado de la reconexion la cierran', () => {
    const s = crearSeguimientoBds();
    s.iniciar();
    expect(s.confirmar(true)).toBe(false); // POST aceptado, sigue en curso
    // El WebSocket reconecta cuando ya termino: el primer estado trae false.
    expect(s.estado(false)).toBe(true);
  });

  it('sin poder leer /api/status, el POST aceptado cuenta como en curso', () => {
    const s = crearSeguimientoBds();
    s.iniciar();
    expect(s.confirmar(null)).toBe(false);
    expect(s.estado(false)).toBe(true);
  });

  it('si ya termino cuando llega /api/status, cierra en ese momento', () => {
    const s = crearSeguimientoBds();
    s.iniciar();
    expect(s.confirmar(false)).toBe(true);
  });

  it('un /api/status atrasado no reabre una operacion ya cerrada por el WebSocket', () => {
    const s = crearSeguimientoBds();
    s.iniciar();
    expect(s.estado(true)).toBe(false);
    expect(s.estado(false)).toBe(true);
    expect(s.confirmar(true)).toBe(false); // respuesta leida antes del final
    expect(s.estado(false)).toBe(false); // y no vuelve a cerrar otro dialogo
  });

  it('un POST rechazado no deja nada pendiente', () => {
    const s = crearSeguimientoBds();
    s.iniciar();
    s.abandonar();
    expect(s.confirmar(true)).toBe(false);
    expect(s.estado(false)).toBe(false);
  });
});
