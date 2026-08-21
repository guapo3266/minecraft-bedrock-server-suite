import React, { useState, useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import { X, Save, TriangleAlert } from 'lucide-react';
import { ServerMotionIcon } from './hover/AnimatedIcons';
import { FilledCheckedIcon } from './hover/AnimatedStatusIcons';
import SpotlightCard from './reactbits/SpotlightCard';
import TiltCard from './hover/TiltCard';
import ShinyText from './reactbits/ShinyText';
import Magnet from './reactbits/Magnet';
import Modal from './Modal';
import { useI18n } from '../i18n.jsx';
import { FIELDS } from '../propsFields';

const inputClass =
  'w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-xs text-white outline-none placeholder:text-slate-400 focus:border-cyan-500/50 transition';

export default function PropsModal({ isOpen, onClose, fields, serverRunning }) {
  const { t } = useI18n();
  const [values, setValues] = useState({});
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState(null); // { ok, message }
  const successIconRef = useRef(null);

  // Animacion del check al guardar correctamente (mismo patron que BackupsSidebar)
  useEffect(() => {
    if (result?.ok && successIconRef.current) {
      successIconRef.current.startAnimation();
    }
  }, [result]);

  useEffect(() => {
    if (isOpen) {
      setValues(fields || {});
      setResult(null);
    }
  }, [isOpen, fields]);

  if (!isOpen) return null;

  const setValue = (key, v) => setValues((prev) => ({ ...prev, [key]: v }));

  const handleSave = async () => {
    setSaving(true);
    setResult(null);
    try {
      const res = await fetch('/api/server_properties', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ values })
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        setResult({ ok: true, message: t('propsSaved') });
      } else {
        setResult({ ok: false, message: data.detail || res.statusText });
      }
    } catch (e) {
      setResult({ ok: false, message: t('propsError') + ': ' + String(e) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal onClose={onClose} label={t('propsTitle')} className="max-w-lg border-cyan-500/40 flex max-h-[85vh] flex-col">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-white/10 pb-4">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-cyan-500/20 border border-cyan-500/40 shadow-[0_0_20px_rgba(6,182,212,0.3)]">
                <ServerMotionIcon className="h-5 w-5 text-cyan-400" />
              </div>
              <div>
                <h2 className="text-lg font-bold text-white">{t('propsTitle')}</h2>
                <p className="text-xs text-slate-400">{t('propsSubtitle')}</p>
              </div>
            </div>
            <button
              onClick={onClose}
              aria-label={t('close')}
              className="rounded-lg p-1.5 text-slate-400 transition hover:bg-white/10 hover:text-white"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          {/* Body: campos dentro de SpotlightCard/TiltCard (idioma visual del proyecto) */}
          <div className="my-4 flex-1 space-y-3 overflow-y-auto overscroll-contain pr-1">
            <TiltCard>
              <SpotlightCard spotlightColor="rgba(6, 182, 212, 0.12)">
                <div className="grid grid-cols-1 gap-3">
                  {FIELDS.map((f) => (
                    <div key={f.key} className="flex items-center justify-between gap-3">
                      <label
                        htmlFor={`props-${f.key}`}
                        className="w-1/2 text-xs font-semibold uppercase tracking-wide text-slate-400"
                      >
                        {t(f.label)}
                      </label>
                      {f.type === 'bool' ? (
                        <button
                          type="button"
                          id={`props-${f.key}`}
                          role="switch"
                          aria-checked={values[f.key] === 'true'}
                          onClick={() => setValue(f.key, values[f.key] === 'true' ? 'false' : 'true')}
                          className={`relative h-6 w-11 shrink-0 rounded-full transition-colors duration-300 ${
                            values[f.key] === 'true'
                              ? 'bg-emerald-500/80 shadow-[0_0_10px_rgba(16,185,129,0.5)]'
                              : 'bg-slate-700'
                          }`}
                        >
                          <motion.span
                            layout
                            transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                            className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow ${
                              values[f.key] === 'true' ? 'left-[22px]' : 'left-0.5'
                            }`}
                          />
                        </button>
                      ) : f.type === 'select' ? (
                        <select
                          id={`props-${f.key}`}
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
                          id={`props-${f.key}`}
                          type={f.type === 'number' ? 'number' : 'text'} autoComplete="off"
                          min={f.min}
                          max={f.max}
                          value={values[f.key] || ''}
                          onChange={(e) => setValue(f.key, e.target.value)}
                          className={inputClass + ' w-1/2'}
                        />
                      )}
                    </div>
                  ))}
                </div>
              </SpotlightCard>
            </TiltCard>

            {/* Resultado del guardado */}
            {result && (
              <div
                aria-live="polite"
                className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-semibold ${
                  result.ok
                    ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
                    : 'border-rose-500/40 bg-rose-500/10 text-rose-300'
                }`}
              >
                {result.ok ? (
                  <FilledCheckedIcon ref={successIconRef} size={18} color="#6ee7b7" />
                ) : (
                  <TriangleAlert className="h-4 w-4 shrink-0" />
                )}
                <span className="break-all">{result.message}</span>
              </div>
            )}

            {/* Aviso de reinicio (mismo patron que el aviso amber de UpdateModal) */}
            {serverRunning && (
              <TiltCard>
                <SpotlightCard spotlightColor="rgba(245, 158, 11, 0.18)">
                  <div className="flex items-center gap-2 text-xs font-bold text-amber-400">
                    <TriangleAlert className="h-4 w-4 shrink-0" />
                    <span>{t('propsRestartNotice')}</span>
                  </div>
                </SpotlightCard>
              </TiltCard>
            )}
          </div>

          {/* Footer Actions (mismo patron que UpdateModal) */}
          <div className="flex justify-end gap-3 border-t border-white/10 pt-4">
            <button
              onClick={onClose}
              className="flex min-h-[44px] items-center rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-xs font-bold text-slate-300 transition duration-200 hover:border-white/25 hover:bg-white/15 hover:text-white active:scale-95 active:bg-white/25"
            >
              {t('cancel')}
            </button>
            <Magnet>
              <button
                onClick={handleSave}
                disabled={saving}
                className="flex min-h-[44px] items-center gap-2 rounded-xl bg-gradient-to-r from-cyan-500 to-emerald-500 px-5 py-2 text-xs font-bold text-black shadow-[0_0_20px_rgba(6,182,212,0.4)] hover:brightness-110 disabled:opacity-50"
              >
                <Save className="h-4 w-4 text-black" />
                <ShinyText text={saving ? t('saving') : t('save')} />
              </button>
            </Magnet>
          </div>
    </Modal>
  );
}
