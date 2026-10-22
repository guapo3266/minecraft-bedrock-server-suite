// Cierre del diálogo de actualizar/revertir BDS (sin React: probado con vitest).
//
// El diálogo se cierra cuando el backend TERMINA la operación: un estado con
// update_in_progress false después de haber visto true, la haya iniciado esta
// pestaña u otra. Antes la marca de "ya la vi empezar" solo existía para la
// operación de esta pestaña y se borraba al reabrir el diálogo: quedaba en
// "Actualizando…" para siempre (2026-10-21).
export function crearSeguimientoBds() {
  let enCurso = false; // último update_in_progress visto
  let esperando = false; // esta pestaña lanzó una operación y espera su fin

  return {
    // Antes del POST de update_bds/rollback_bds.
    iniciar() {
      esperando = true;
    },
    // Cada estado del backend (WebSocket, también el de una reconexión).
    // true = la operación acaba de terminar: cerrar el diálogo.
    estado(updateInProgress) {
      const termino = enCurso && !updateInProgress;
      enCurso = !!updateInProgress;
      if (termino) esperando = false;
      return termino;
    },
    // GET /api/status tras un POST aceptado (null = no se pudo leer).
    // true = ya terminó. El backend marca el flag ANTES de responder al POST:
    // si el estado no dice lo contrario, la operación está en curso aunque el
    // WebSocket no lo haya traído (caído o reconectando), y el primer estado
    // con el flag en false la cierra.
    confirmar(updateInProgress) {
      if (!esperando) return false; // un estado posterior ya la cerró
      if (updateInProgress === false) {
        esperando = false;
        return true;
      }
      enCurso = true;
      return false;
    },
    // POST rechazado o fallido: no hay nada que esperar.
    abandonar() {
      esperando = false;
    }
  };
}
