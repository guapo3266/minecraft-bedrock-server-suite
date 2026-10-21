export const ACTIVE_PHASES = new Set(['downloading', 'verifying', 'stopping', 'waiting_gui', 'applying', 'checking', 'rolling_back', 'reconnecting']);
export const FINAL_PHASES = new Set(['complete', 'rolled_back', 'restart_failed', 'rollback_failed', 'error']);

// Qué hacer con una respuesta de /api/suite_update/progress mientras la pestaña
// espera una actualización: 'continue', 'finish' o 'reload'. "idle" significa que
// el backend no tiene ninguna actualización registrada: antes la pestaña que la
// recordaba (sessionStorage) seguía sondeando para siempre, con Instalar y
// Comprobar deshabilitados (2026-10-20). Una fase desconocida sigue sondeando:
// puede ser una fase activa de un backend más nuevo durante el relevo.
export function nextPollAction(progress, bundleVersion) {
  const phase = progress?.phase;
  if (FINAL_PHASES.has(phase)) {
    const updated = phase === 'complete' || phase === 'restart_failed';
    return updated && progress.version && progress.version !== bundleVersion ? 'reload' : 'finish';
  }
  return phase === 'idle' ? 'finish' : 'continue';
}

// Bucle de sondeo del progreso, sin React para poder probarlo. Devuelve la
// función que lo detiene; un fallo de red se informa como 'reconnecting'.
export function startProgressPolling({
  fetchProgress, onProgress, onFinish, onReload, bundleVersion,
  delayMs = 2000, schedule = setTimeout, cancel = clearTimeout
}) {
  let stopped = false;
  let timer;
  const poll = async () => {
    try {
      const next = await fetchProgress();
      if (stopped) return;
      onProgress(next);
      const action = nextPollAction(next, bundleVersion);
      if (action === 'reload') {
        onReload();
        return;
      }
      if (action === 'finish') {
        onFinish(next);
        return;
      }
    } catch {
      if (!stopped) onProgress({ phase: 'reconnecting' });
    }
    if (!stopped) timer = schedule(poll, delayMs);
  };
  poll();
  return () => {
    stopped = true;
    cancel(timer);
  };
}
export const PHASE_KEYS = {
  idle: 'suitePhaseIdle', downloading: 'suitePhaseDownloading', verifying: 'suitePhaseVerifying',
  stopping: 'suitePhaseStopping', waiting_gui: 'suitePhaseRestarting', applying: 'suitePhaseApplying',
  checking: 'suitePhaseChecking', rolling_back: 'suitePhaseRollingBack', reconnecting: 'suitePhaseReconnecting',
  complete: 'suitePhaseComplete', rolled_back: 'suitePhaseRolledBack', restart_failed: 'suitePhaseRestartFailed',
  rollback_failed: 'suitePhaseRollbackFailed', error: 'suitePhaseError'
};
