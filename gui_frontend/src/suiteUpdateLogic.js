export const ACTIVE_PHASES = new Set(['downloading', 'verifying', 'stopping', 'waiting_gui', 'applying', 'checking', 'rolling_back', 'reconnecting']);
export const FINAL_PHASES = new Set(['complete', 'rolled_back', 'restart_failed', 'rollback_failed', 'error']);
export const PHASE_KEYS = {
  idle: 'suitePhaseIdle', downloading: 'suitePhaseDownloading', verifying: 'suitePhaseVerifying',
  stopping: 'suitePhaseStopping', waiting_gui: 'suitePhaseRestarting', applying: 'suitePhaseApplying',
  checking: 'suitePhaseChecking', rolling_back: 'suitePhaseRollingBack', reconnecting: 'suitePhaseReconnecting',
  complete: 'suitePhaseComplete', rolled_back: 'suitePhaseRolledBack', restart_failed: 'suitePhaseRestartFailed',
  rollback_failed: 'suitePhaseRollbackFailed', error: 'suitePhaseError'
};
