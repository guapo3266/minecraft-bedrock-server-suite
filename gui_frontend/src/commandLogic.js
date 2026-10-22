// Resultado de POST /api/command tal como lo usan las acciones de jugadores
// (sin React: probado con vitest sin DOM).
//
// El backend responde {status: 'ok' | 'offline' | 'error', message?}. Un
// rechazo HTTP (403 de Host/Origin, 409 suite_update_in_progress, 500) trae
// {detail} y ningun status: antes caia en la rama de exito y la GUI decia
// "Comando enviado" sin haber enviado nada (2026-10-21).
export function resultadoComando(ok, httpStatus, data) {
  if (!ok) {
    return { status: 'error', message: (data && data.detail) || `HTTP ${httpStatus}` };
  }
  if (!data || typeof data.status !== 'string') {
    return { status: 'error', message: `HTTP ${httpStatus}` };
  }
  return data;
}
