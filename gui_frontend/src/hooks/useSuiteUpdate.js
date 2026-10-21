import { useCallback, useEffect, useState } from 'react';
import { version } from '../../../version.json';
import { ACTIVE_PHASES, startProgressPolling } from '../suiteUpdateLogic';

const KEY = 'bedrock-suite-updating';
const remembered = () => { try { return sessionStorage.getItem(KEY) === '1'; } catch { return false; } };
const remember = value => { try { if (value) sessionStorage.setItem(KEY, '1'); else sessionStorage.removeItem(KEY); } catch { /* La actualización sigue en el backend. */ } };

export default function useSuiteUpdate() {
  const [open, setOpen] = useState(remembered);
  const [inFlight, setInFlight] = useState(remembered);
  const [submitting, setSubmitting] = useState(false);
  const [info, setInfo] = useState(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState(null);
  const [progress, setProgress] = useState({ phase: remembered() ? 'reconnecting' : 'idle' });
  const check = useCallback(async (refresh = false) => {
    setChecking(true);
    setError(null);
    try {
      const response = await fetch(`/api/suite_update${refresh ? '?refresh=1' : ''}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const value = await response.json();
      setInfo(value);
      if (value.progress?.phase) {
        setProgress(value.progress);
        if (ACTIVE_PHASES.has(value.progress.phase)) {
          setInFlight(true);
          remember(true);
        }
      }
    } catch (failure) { setError(String(failure.message)); }
    finally { setChecking(false); }
  }, []);
  useEffect(() => { check(); }, [check]);
  useEffect(() => {
    if (!inFlight) return undefined;
    return startProgressPolling({
      bundleVersion: version,
      fetchProgress: async () => {
        const response = await fetch('/api/suite_update/progress');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      },
      onProgress: setProgress,
      onReload: () => window.location.reload(),
      onFinish: () => {
        remember(false);
        setInFlight(false);
        check();
      }
    });
  }, [inFlight, check]);
  const install = async () => {
    setError(null);
    setSubmitting(true);
    setProgress({ phase: 'downloading' });
    try {
      const response = await fetch('/api/suite_update', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirmed: true })
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${response.status}`);
      }
      remember(true);
      setInFlight(true);
    } catch (failure) {
      remember(false);
      setInFlight(false);
      setProgress({ phase: 'error' });
      setError(String(failure.message));
    } finally { setSubmitting(false); }
  };
  return { open, setOpen, info, checking, error, progress, inFlight: inFlight || submitting, check, install };
}
