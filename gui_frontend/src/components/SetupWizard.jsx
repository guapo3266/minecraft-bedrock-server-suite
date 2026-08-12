import React, { useEffect, useMemo, useState } from 'react';
import { TriangleAlert, Download, Save } from 'lucide-react';
import Stepper, { Step } from './reactbits/Stepper';
import { FIELDS } from '../propsFields';
import { useI18n } from '../i18n.jsx';

// Subconjunto de campos para el setup inicial (los esenciales de primera puesta en marcha)
const WIZARD_KEYS = ['server-name', 'gamemode', 'difficulty', 'server-port', 'max-players'];

const inputClass =
  'w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-xs text-white outline-none placeholder:text-slate-400 focus:border-cyan-500/50 transition-all';

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
  const [completing, setCompleting] = useState(false);
  const [completeError, setCompleteError] = useState(null);
  const [attempt, setAttempt] = useState(0);

  // Precarga de los valores actuales de server.properties (vacio en instalacion nueva)
  useEffect(() => {
    (async () => {
      try {
        const res = await fetch('/api/server_properties');
        const data = await res.json();
        if (data.fields) setValues(data.fields);
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
  useEffect(() => {
    if (!installing) return;
    const texts = setupLogs.map((l) => l.text);
    if (texts.some((x) => x.includes('instalado correctamente') || x.includes('installed successfully'))) {
      setInstalled(true);
      setInstalling(false);
      setInstallResult({ ok: true, message: t('setupInstallOk') });
    } else if (texts.some((x) => x.includes('No se pudo completar') || x.includes('could not be completed') || x.includes('Error durante') || x.includes('Error during'))) {
      setInstalling(false);
      setInstallResult({ ok: false, message: t('setupInstallError') });
    }
  }, [setupLogs, installing, t]);

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
    setInstalling(true);
    setInstallResult(null);
    try {
      const res = await fetch('/api/setup/install_bds', { method: 'POST' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.status === 'busy') {
        setInstalling(false);
        setInstallResult({ ok: false, message: data.detail || data.message || t('setupInstallError') });
      }
      // dispatch ok: installing sigue en true hasta que el log confirme el fin
    } catch (e) {
      setInstalling(false);
      setInstallResult({ ok: false, message: String(e) });
    }
  };

  const handleComplete = async () => {
    setCompleting(true);
    setCompleteError(null);
    try {
      const res = await fetch('/api/setup/complete', { method: 'POST' });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        onDone();
      } else {
        setCompleteError(data.detail || t('setupCompleteError'));
        setAttempt((a) => a + 1); // reset del Stepper al paso 1
      }
    } catch (e) {
      setCompleteError(String(e));
      setAttempt((a) => a + 1);
    } finally {
      setCompleting(false);
    }
  };

  const busy = installing || completing || saving;
  const nextDisabled = (step === 1 && !saved) || (step === 2 && !installed);
  const wizardFields = FIELDS.filter((f) => WIZARD_KEYS.includes(f.key));

  return (
    <div className="relative min-h-screen text-slate-100 font-sans">
      <div className="mx-auto mt-8 w-full max-w-lg rounded-2xl border border-white/10 bg-slate-950 p-6 shadow-2xl">
        <Stepper
          key={attempt}
          initialStep={1}
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
                      className={`rounded-lg px-3 py-1 text-xs font-bold transition-all ${
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
                <div key={f.key} className="flex items-center justify-between gap-3">
                  <label htmlFor={`setup-${f.key}`} className="w-1/2 text-xs font-semibold uppercase tracking-wide text-slate-400">
                    {t(f.label)}
                  </label>
                  {f.type === 'select' ? (
                    <select
                      id={`setup-${f.key}`}
                      value={values[f.key] || ''}
                      onChange={(e) => setValue(f.key, e.target.value)}
                      className={inputClass + ' w-1/2'}
                    >
                      {f.options.map((o) => (
                        <option key={o} value={o} className="bg-slate-900">
                          {o}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      id={`setup-${f.key}`}
                      type={f.type === 'number' ? 'number' : 'text'}
                      min={f.min}
                      max={f.max}
                      value={values[f.key] || ''}
                      onChange={(e) => setValue(f.key, e.target.value)}
                      className={inputClass + ' w-1/2'}
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
                  <div className={`mt-2 rounded-lg border px-3 py-2 text-xs font-semibold ${saveResult.ok ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300' : 'border-rose-500/40 bg-rose-500/10 text-rose-300'}`}>
                    {!saveResult.ok && <TriangleAlert className="mr-1 inline h-3.5 w-3.5" />}
                    {saveResult.message}
                  </div>
                )}
                {!saved && (
                  <p className="mt-2 text-center text-[11px] text-slate-500">{t('setupNextHint')}</p>
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

                {installResult && (
                  <div className={`rounded-lg border px-3 py-2 text-xs font-semibold ${installResult.ok ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300' : 'border-rose-500/40 bg-rose-500/10 text-rose-300'}`}>
                    {!installResult.ok && <TriangleAlert className="mr-1 inline h-3.5 w-3.5" />}
                    {installResult.message}
                  </div>
                )}

                <div className="rounded-lg border border-white/10 bg-black/60 p-2">
                  <p className="mb-1 text-[10px] font-bold uppercase tracking-wide text-slate-500">{t('setupInstallProgress')}</p>
                  <div className="max-h-40 overflow-y-auto font-mono text-[10px] leading-relaxed text-slate-300">
                    {setupLogs.length === 0 ? (
                      <span className="text-slate-600">{installing ? t('setupInstalling') : '—'}</span>
                    ) : (
                      setupLogs.map((l, i) => <div key={i}>{l.time} {l.text}</div>)
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
                <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs font-semibold text-rose-300">
                  <TriangleAlert className="mr-1 inline h-3.5 w-3.5" />
                  {completeError}
                </div>
              )}
            </div>
          </Step>
        </Stepper>
      </div>

      {completing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-md">
          <p className="animate-pulse text-sm font-bold text-white">{t('setupCompleting')}</p>
        </div>
      )}
    </div>
  );
}
