// Resultado de POST /api/command en las acciones de jugadores (sin jsdom).
import { describe, expect, it } from 'vitest';
import { resultadoComando } from '../src/commandLogic.js';

describe('resultadoComando', () => {
  it('devuelve la respuesta del backend cuando el HTTP es 2xx', () => {
    expect(resultadoComando(true, 200, { status: 'ok' })).toEqual({ status: 'ok' });
    expect(resultadoComando(true, 200, { status: 'offline' })).toEqual({ status: 'offline' });
    expect(resultadoComando(true, 200, { status: 'error', message: 'stdin' }))
      .toEqual({ status: 'error', message: 'stdin' });
  });

  it('un rechazo HTTP es un error con su motivo, nunca "enviado"', () => {
    // 409 durante una actualizacion de la suite: antes caia en la rama de exito.
    expect(resultadoComando(false, 409, { detail: 'suite_update_in_progress' }))
      .toEqual({ status: 'error', message: 'suite_update_in_progress' });
    expect(resultadoComando(false, 403, {})).toEqual({ status: 'error', message: 'HTTP 403' });
    expect(resultadoComando(false, 500, null)).toEqual({ status: 'error', message: 'HTTP 500' });
  });

  it('un 2xx sin status reconocible tampoco cuenta como enviado', () => {
    expect(resultadoComando(true, 200, {})).toEqual({ status: 'error', message: 'HTTP 200' });
    expect(resultadoComando(true, 204, null)).toEqual({ status: 'error', message: 'HTTP 204' });
  });
});
