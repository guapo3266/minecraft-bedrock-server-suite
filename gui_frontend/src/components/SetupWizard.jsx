import React, { useEffect, useMemo, useRef, useState } from 'react';
import { TriangleAlert, Download, Save } from 'lucide-react';
import Stepper, { Step } from './reactbits/Stepper';
import GlassSelect from './GlassSelect';
import { FIELDS } from '../propsFields';
import { useI18n } from '../i18n.jsx';

// Subconjunto de campos para el setup inicial (los esenciales de primera puesta en marcha)
const WIZARD_KEYS = ['server-name', 'gamemode', 'difficulty', 'server-port', 'max-players'];

// Defaults de BDS cuando el campo viene vacio (instalacion nueva sin archivo):
// el usuario puede cambiarlos, pero sin ellos un campo vacio seria rechazado
// por la validacion del backend ("debe ser un entero").
const WIZARD_DEFAULTS = {
  'gamemode': 'survival',
  'difficulty': 'easy',
  'server-port': '19132',
  'max-players': '10'
};

const inputClass = 'settings-input';

// ── Detección del fin de la instalación ──────────────────────────────────
// El backend reporta el desenlace por logs "[Setup] ..." en ES/EN
// (gui_backend/routers/setup.py, hilo do_install):
//   éxito:   "[Setup] BDS instalado correctamente (v...)" / "BDS installed successfully"
//   fallo:   "[Setup] No se pudo completar la instalacion..." / "The installation could not be completed..."
//   excepción: "[Setup] Error durante la instalacion: ..." / "Error during installation: ..."
// Matchers centralizados y documentados: si el backend cambia la redacción,
// basta con actualizar estas constantes (antes eran literales en línea).
const INSTALL_SUCCESS_MATCHERS = ['instalado correctamente', 'installed successfully'];
const INSTALL_FAILURE_MATCHERS = ['No se pudo completar', 'could not be completed', 'Error durante', 'Error during'];

// Fallback cuando el WS no conecta (los logs no llegan): el contrato expone
// GET /api/setup_status → {"required", "bds_installed"} (docs/API_CONTRACT.md)
// y bds_installed pasa a true en cuanto bedrock_server.exe existe en disco.
const INSTALL_STATUS_ENDPOINT = '/api/setup_status';
const INSTALL_POLL_MS = 5000;
// Sin confirmación en este tiempo se avisa "sigue en progreso" con
// comprobación/reintento MANUAL (la instalación nunca se relanza sola).
const INSTALL_SLOW_NOTICE_MS = 90000;

export default function SetupWizard({ bdsInstalled, logs, onDone }) {
  const { t, lang, setLang } = useI18n();
  const [step, setStep] = useState(1);
  const [values, setValues] = useState({});
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveResult, setSaveResult] = useState(null);
  const [installed, setInstalled] = useState(!!bdsInstalled);
  const [installing, setInstalling] = useState(false);
  const [installResult, setInstallResult] = useState(null);
  const [installSlow, setInstallSlow] = useState(false);
  const [completing, setCompleting] = useState(false);
  const [completeError, setCompleteError] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const [resetStep, setResetStep] = useState(1);
  // Watermark de ids de log: el fin de la instalacion solo se detecta por
  // logs NUEVOS (id > marca del intento actual). Sin esto, un reintento tras
  // un fallo re-leia el log de error del intento ANTERIOR (replayeado por el
  // init del WS) y se marcaba como fallado al instante; si el reintento
  // terminaba bien, 'installed' jamas pasaba a true y el wizard quedaba
  // atascado en el paso 2.
  const installStartIdRef = useRef(0);

  // Precarga de los valores actuales de server.properties (vacio en instalacion nueva).
  // Los campos sin valor toman el default de BDS (WIZARD_DEFAULTS): un valor
  // vacio en port/max-players seria rechazado por la validacion del backend.
  useEffect(() => {
    (async () => {
      try {
        const res = await fetch('/api/server_properties');
        const data = await res.json();
        if (data.fields) {
          const vals = { ...data.fields };
          Object.entries(WIZARD_DEFAULTS).forEach(([k, v]) => {
            if (!vals[k]) vals[k] = v;
          });
          setValues(vals);
        }
      } catch (e) {
        console.error(e);
      }
    })();
  }, []);

  const setupLogs = useMemo(
    () => logs.filter((l) => (l.text || '').includes('[Setup]')).slice(-60),
    [logs]
  );

  // El fin de la instalacion se detecta por los logs del backend ([Setup] ...)
  // SOLO los posteriores al inicio del intento en curso (ver installStartIdRef).
  // Matchers centralizados en INSTALL_SUCCESS/FAILURE_MATCHERS.
  useEffect(() => {
    if (!installing) return;
    const texts = setupLogs
      .filter((l) => typeof l.id === 'number' && l.id > installStartIdRef.current)
      .map((l) => l.text);
    if (texts.some((x) => INSTALL_SUCCESS_MATCHERS.some((m) => x.includes(m)))) {
      setInstalled(true);
      setInstalling(false);
      setInstallResult({ ok: true, message: t('setupInstallOk') });
    } else if (texts.some((x) => INSTALL_FAILURE_MATCHERS.some((m) => x.includes(m)))) {
      setInstalling(false);
      setInstallResult({ ok: false, message: t('setupInstallError') });
    }
  }, [setupLogs, installing, t]);

  // Fallback sin logs (WS sin conectar / logs perdidos): se sondea
  // GET /api/setup_status y se considera completada cuando bds_installed
  // pasa a true (el ejecutable ya existe en disco). Si en
  // INSTALL_SLOW_NOTICE_MS no hay confirmacion por ningun canal, se avisa
  // "sigue en progreso" con comprobacion/reintento manual (nunca automatico).
  useEffect(() => {
    if (!installing) return;
    let cancelled = false;

    const checkStatus = async () => {
      try {
        const res = await fetch(INSTALL_STATUS_ENDPOINT);
        if (!res.ok) return;
        const data = await res.json();
        if (!cancelled && data.bds_installed) {
          setInstalled(true);
          setInstalling(false);
          setInstallResult({ ok: true, message: t('setupInstallOk') });
        }
      } catch {
        // sin backend ahora mismo: se reintenta en el siguiente tick
      }
    };

    checkStatus();
    const pollTimer = setInterval(checkStatus, INSTALL_POLL_MS);
    const slowTimer = setTimeout(() => {
      if (!cancelled) setInstallSlow(true);
    }, INSTALL_SLOW_NOTICE_MS);
    return () => {
      cancelled = true;
      clearInterval(pollTimer);
      clearTimeout(slowTimer);
    };
  }, [installing, t]);

  const setValue = (key, v) => setValues((prev) => ({ ...prev, [key]: v }));

  const handleSave = async () => {
    setSaving(true);
    setSaveResult(null);
    try {
      const res = await fetch('/api/server_properties', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ values })
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        setSaved(true);
        setSaveResult({ ok: true, message: t('setupSaved') });
      } else {
        setSaveResult({ ok: false, message: data.detail || res.statusText });
      }
    } catch (e) {
      setSaveResult({ ok: false, message: String(e) });
    } finally {
      setSaving(false);
    }
  };

  const handleInstall = async () => {
    installStartIdRef.current = logs.reduce(
      (m, l) => (typeof l.id === 'number' && l.id > m ? l.id : m),
      0
    );
    setInstalling(true);
    setInstallResult(null);
    setInstallSlow(false);
    try {
      const res = await fetch('/api/setup/install_bds', { method: 'POST' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setInstalling(false);
        setInstallResult({ ok: false, message: data.detail || data.message || t('setupInstallError') });
      } else if (data.status === 'busy') {
        // Otra operacion tiene el op_lock (puede ser la propia instalacion en
        // curso si el usuario reintentó): se muestra el aviso pero se MANTIENE
        // la observacion de logs/estado en vez de dar el intento por muerto.
        setInstallResult({ ok: false, message: data.message || t('setupInstallError') });
      }
      // install_dispatched: installing sigue en true hasta que el log o el
      // fallback de estado confirmen el fin
    } catch (e) {
      setInstalling(false);
      setInstallResult({ ok: false, message: String(e) });
    }
  };

  // Comprobacion manual del fallback de estado (sin relanzar la instalacion)
  const handleCheckInstallStatus = async () => {
    try {
      const res = await fetch(INSTALL_STATUS_ENDPOINT);
      if (!res.ok) throw new Error(res.statusText || `HTTP ${res.status}`);
      const data = await res.json();
      if (data.bds_installed) {
        setInstalled(true);
        setInstalling(false);
        setInstallSlow(false);
        setInstallResult({ ok: true, message: t('setupInstallOk') });
      } else {
        // sigue en curso: se mantiene el aviso "en progreso"
        setInstallResult({ ok: false, message: t(installing ? 'setupInstallSlow' : 'setupBdsNotFoundManual') });
      }
    } catch (e) {
      setInstallResult({ ok: false, message: t('setupNetError') + ` (${String(e)})` });
    }
  };

  const handleComplete = async () => {
    // Pre-chequeo local: sin BDS instalado no hay nada que finalizar. Evita
    // una llamada inutil a la API (409) y el salto de pasos por los
    // indicadores: vuelve al paso 2 (instalacion) con mensaje claro.
    if (!installed) {
      setCompleteError(t('setupNeedInstall'));
      setResetStep(2);
      setAttempt((a) => a + 1);
      return;
    }
    setCompleting(true);
    setCompleteError(null);
    try {
      const res = await fetch('/api/setup/complete', { method: 'POST' });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        onDone();
      } else {
        setCompleteError(data.detail || t('setupCompleteError'));
        setResetStep(1);
        setAttempt((a) => a + 1);
      }
    } catch {
      setCompleteError(t('setupNetError'));
      setResetStep(1);
      setAttempt((a) => a + 1);
    } finally {
      setCompleting(false);
    }
  };

  const busy = installing || completing || saving;
  const nextDisabled = (step === 1 && !saved) || (step === 2 && !installed);
  const wizardFields = FIELDS.filter((f) => WIZARD_KEYS.includes(f.key));

  return (
    <div className="setup-view legacy-ui">
      <div className="panel setup-panel">
        <Stepper
          key={attempt}
          initialStep={resetStep}
          onStepChange={(s) => setStep(s)}
          onFinalStepCompleted={handleComplete}
          backButtonText={t('setupBack')}
          nextButtonText={t('setupNext')}
          completeButtonText={t('setupCompleteButton')}
          disableStepIndicators={busy}
          nextButtonProps={{ disabled: nextDisabled || busy }}
          stepCircleContainerClassName="bg-slate-900/60"
        >
          {/* ── Paso 1: Configuracion ── */}
          <Step>
            <div className="space-y-3">
              <div className="mb-4 text-center">
                <h1 className="text-lg font-bold text-white">{t('setupTitle')}</h1>
                <p className="mt-1 text-xs text-slate-400">{t('setupSubtitle')}</p>
              </div>
              <div className="flex items-center justify-between gap-3">
                <label className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                  {t('setupLangLabel')}
                </label>
                <div className="flex gap-2">
                  {['es', 'en'].map((code) => (
                    <button
                      key={code}
                      type="button"
                      onClick={() => setLang(code)}
                      className={`rounded-lg px-3 py-1 text-xs font-bold transition ${
                        lang === code
                          ? 'bg-[#5227FF] text-white shadow-[0_0_14px_rgba(82,39,255,0.45)]'
                          : 'bg-white/5 text-slate-300 hover:bg-white/10'
                      }`}
                    >
                      {code.toUpperCase()}
                    </button>
                  ))}
                </div>
              </div>

              {wizardFields.map((f) => (
                <div key={f.key} className="settings-field">
                  <label htmlFor={`setup-${f.key}`} className="w-1/2 text-xs font-semibold uppercase tracking-wide text-slate-400">
                    {t(f.label)}
                  </label>
                  {f.type === 'select' ? (
                    <GlassSelect
                      id={`setup-${f.key}`}
                      label={t(f.label)}
                      value={values[f.key] || ''}
                      onChange={value => setValue(f.key, value)}
                      options={f.options.map(value => ({ id: value, label: value }))}
                    />
                  ) : (
                    <input
                      id={`setup-${f.key}`}
                      type={f.type === 'number' ? 'number' : 'text'} autoComplete="off"
                      min={f.min}
                      max={f.max}
                      value={values[f.key] || ''}
                      onChange={(e) => setValue(f.key, e.target.value)}
                      className={inputClass}
                    />
                  )}
                </div>
              ))}

              <div className="pt-2">
                <button
                  type="button"
                  onClick={handleSave}
                  disabled={saving}
                  className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-cyan-500 to-emerald-500 px-4 py-2 text-xs font-bold text-black shadow-[0_0_20px_rgba(6,182,212,0.4)] hover:brightness-110 disabled:opacity-50"
                >
                  <Save className="h-4 w-4 text-black" />
                  {saving ? t('saving') : t('setupSaveConfig')}
                </button>
                {saveResult && (
                  <div aria-live="polite" className={`mt-2 rounded-lg border px-3 py-2 text-xs font-semibold ${saveResult.ok ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300' : 'border-rose-500/40 bg-rose-500/10 text-rose-300'}`}>
                    {!saveResult.ok && <TriangleAlert className="mr-1 inline h-3.5 w-3.5" />}
                    {saveResult.message}
                  </div>
                )}
                {!saved && (
                  <p className="mt-2 text-center text-[11px] text-slate-400">{t('setupNextHint')}</p>
                )}
              </div>
            </div>
          </Step>

          {/* ── Paso 2: Instalar BDS (solo instalaciones sin ejecutable) ── */}
          {!bdsInstalled && (
            <Step>
              <div className="space-y-3">
                <p className="text-xs text-slate-300">
                  {t('setupBdsMissing')}
                </p>
                <button
                  type="button"
                  onClick={handleInstall}
                  disabled={installing || installed}
                  className="flex w-full items-center justify-center gap-2 rounded-xl bg-[#5227FF] px-4 py-2 text-xs font-bold text-white shadow-[0_0_20px_rgba(82,39,255,0.45)] hover:brightness-110 disabled:opacity-50"
                >
                  <Download className="h-4 w-4" />
                  {installing ? t('setupInstalling') : installed ? t('setupBdsPresent') : t('setupInstall')}
                </button>

                {!installed && !installing && <button type="button" onClick={handleCheckInstallStatus}
                  className="button secondary w-full">{t('setupCheckManual')}</button>}

                {installResult && (
                  <div aria-live="polite" className={`rounded-lg border px-3 py-2 text-xs font-semibold ${installResult.ok ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300' : 'border-rose-500/40 bg-rose-500/10 text-rose-300'}`}>
                    {!installResult.ok && <TriangleAlert className="mr-1 inline h-3.5 w-3.5" />}
                    {installResult.message}
                  </div>
                )}

                {/* Sin confirmacion tras INSTALL_SLOW_NOTICE_MS: "sigue en
                    progreso" + comprobacion/reintento MANUAL (el backend nunca
                    se relanza automaticamente desde aqui) */}
                {installing && installSlow && (
                  <div role="status" className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs">
                    <p className="font-semibold text-amber-300">
                      <TriangleAlert className="mr-1 inline h-3.5 w-3.5" />
                      {t('setupInstallSlow')}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={handleCheckInstallStatus}
                        className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 font-bold text-slate-200 transition hover:bg-white/15 hover:text-white"
                      >
                        {t('setupCheckStatus')}
                      </button>
                      <button
                        type="button"
                        onClick={handleInstall}
                        className="rounded-lg border border-amber-500/40 bg-amber-500/15 px-3 py-1.5 font-bold text-amber-200 transition hover:bg-amber-500/25"
                      >
                        {t('setupInstallRetry')}
                      </button>
                    </div>
                  </div>
                )}

                <div className="rounded-lg border border-white/10 bg-black/60 p-2">
                  <p className="mb-1 text-[10px] font-bold uppercase tracking-wide text-slate-400">{t('setupInstallProgress')}</p>
                  <div className="max-h-40 overflow-y-auto font-mono text-[10px] leading-relaxed text-slate-300">
                    {setupLogs.length === 0 ? (
                      <span className="text-slate-600">{installing ? t('setupInstalling') : '—'}</span>
                    ) : (
                      setupLogs.map((l) => <div key={l.id ?? `${l.time}-${l.text}`}>{l.time} {l.text}</div>)
                    )}
                  </div>
                </div>
              </div>
            </Step>
          )}

          {/* ── Paso final: Finalizar ── */}
          <Step>
            <div className="space-y-3 text-center">
              <p className="text-xs text-slate-300">{t('setupFinalText')}</p>
              {completeError && (
                <div aria-live="polite" className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs font-semibold text-rose-300">
                  <TriangleAlert className="mr-1 inline h-3.5 w-3.5" />
                  {completeError}
                </div>
              )}
            </div>
          </Step>
        </Stepper>
      </div>

      {completing && (
        <div role="status" className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-md">
          <p className="animate-pulse text-sm font-bold text-white">{t('setupCompleting')}</p>
        </div>
      )}
    </div>
  );
}
