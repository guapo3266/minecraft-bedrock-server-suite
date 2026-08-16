import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Save, TriangleAlert, CalendarClock } from 'lucide-react';
import { FilledCheckedIcon } from './hover/AnimatedStatusIcons';
import SpotlightCard from './reactbits/SpotlightCard';
import TiltCard from './hover/TiltCard';
import ShinyText from './reactbits/ShinyText';
import Magnet from './reactbits/Magnet';
import { useI18n } from '../i18n.jsx';

const inputClass =
  'w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-xs text-white outline-none placeholder:text-slate-400 focus:border-cyan-500/50 transition-all';

function SectionTitle({ children }) {
  return (
    <p className="pt-1 text-[11px] font-bold uppercase tracking-widest text-cyan-400/80">
      {children}
    </p>
  );
}

function Toggle({ id, on, onClick }) {
  return (
    <button
      type="button"
      id={id}
      onClick={onClick}
      className={`relative h-6 w-11 shrink-0 rounded-full transition-colors duration-300 ${
        on
          ? 'bg-emerald-500/80 shadow-[0_0_10px_rgba(16,185,129,0.5)]'
          : 'bg-slate-700'
      }`}
    >
      <motion.span
        layout
        transition={{ type: 'spring', stiffness: 500, damping: 30 }}
        className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow ${on ? 'left-[22px]' : 'left-0.5'}`}
      />
    </button>
  );
}

export default function ScheduleModal({ isOpen, onClose, config }) {
  const { t } = useI18n();
  const [values, setValues] = useState({});
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState(null); // { ok, message }
  const successIconRef = useRef(null);

  useEffect(() => {
    if (result?.ok && successIconRef.current) {
      successIconRef.current.startAnimation();
    }
  }, [result]);

  // Hora vacia = null (sin hora fijada); se normaliza en ambos sentidos
  useEffect(() => {
    if (isOpen && config) {
      setValues({
        ...config,
        daily_backup_time: config.daily_backup_time || '',
        daily_restart_time: config.daily_restart_time || ''
      });
      setResult(null);
    }
  }, [isOpen, config]);

  if (!isOpen) return null;

  const setValue = (key, v) => setValues((prev) => ({ ...prev, [key]: v }));

  const handleSave = async () => {
    setSaving(true);
    setResult(null);
    const payload = {
      ...values,
      backup_interval_min: Number(values.backup_interval_min) || 30,
      daily_backup_time: values.daily_backup_time?.trim() || null,
      daily_restart_time: values.daily_restart_time?.trim() || null
    };
    try {
      const res = await fetch('/api/schedule', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        setResult({ ok: true, message: t('schedSaved') });
      } else {
        setResult({ ok: false, message: data.detail || res.statusText });
      }
    } catch (e) {
      setResult({ ok: false, message: t('schedError') + ': ' + String(e) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
          className="absolute inset-0 bg-black/75 backdrop-blur-md"
        />

        <motion.div
          initial={{ scale: 0.8, opacity: 0, y: 20 }}
          animate={{ scale: 1, opacity: 1, y: 0 }}
          exit={{ scale: 0.8, opacity: 0, y: 20 }}
          transition={{ type: 'spring', stiffness: 300, damping: 20 }}
          className="relative z-10 flex max-h-[85vh] w-full max-w-lg flex-col rounded-2xl border border-cyan-500/40 bg-slate-950 p-6 shadow-2xl"
        >
          <div className="flex items-center justify-between border-b border-white/10 pb-4">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-cyan-500/20 border border-cyan-500/40 shadow-[0_0_20px_rgba(6,182,212,0.3)]">
                <CalendarClock className="h-5 w-5 text-cyan-400" />
              </div>
              <div>
                <h2 className="text-lg font-bold text-white">{t('schedTitle')}</h2>
                <p className="text-xs text-slate-400">{t('schedSubtitle')}</p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="rounded-lg p-1.5 text-slate-400 transition-all hover:bg-white/10 hover:text-white"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          <div className="my-4 flex-1 space-y-3 overflow-y-auto pr-1">
            <TiltCard>
              <SpotlightCard spotlightColor="rgba(6, 182, 212, 0.12)">
                <div className="grid grid-cols-1 gap-3">
                  <SectionTitle>{t('schedBackupsSection')}</SectionTitle>

                  <div className="flex items-center justify-between gap-3">
                    <label
                      htmlFor="sched-interval"
                      className="w-1/2 text-xs font-semibold uppercase tracking-wide text-slate-400"
                    >
                      {t('schedInterval')}
                    </label>
                    <input
                      id="sched-interval"
                      type="number"
                      min={5}
                      max={1440}
                      value={values.backup_interval_min ?? ''}
                      onChange={(e) => setValue('backup_interval_min', e.target.value)}
                      className={inputClass + ' w-1/2'}
                    />
                  </div>

                  <div className="flex items-center justify-between gap-3">
                    <label
                      htmlFor="sched-only-players"
                      className="w-1/2 text-xs font-semibold uppercase tracking-wide text-slate-400"
                    >
                      {t('schedOnlyPlayers')}
                    </label>
                    <Toggle
                      id="sched-only-players"
                      on={values.backup_only_with_players === true}
                      onClick={() => setValue('backup_only_with_players', !values.backup_only_with_players)}
                    />
                  </div>

                  <div className="flex items-center justify-between gap-3">
                    <label
                      htmlFor="sched-daily-backup"
                      className="w-1/2 text-xs font-semibold uppercase tracking-wide text-slate-400"
                    >
                      {t('schedDailyBackupTime')}
                    </label>
                    <input
                      id="sched-daily-backup"
                      type="text"
                      placeholder="04:00"
                      value={values.daily_backup_time ?? ''}
                      onChange={(e) => setValue('daily_backup_time', e.target.value)}
                      className={inputClass + ' w-1/2 font-mono'}
                    />
                  </div>

                  <SectionTitle>{t('schedWatchdogSection')}</SectionTitle>

                  <div className="flex items-center justify-between gap-3">
                    <label
                      htmlFor="sched-auto-restart"
                      className="w-1/2 text-xs font-semibold uppercase tracking-wide text-slate-400"
                    >
                      {t('schedAutoRestart')}
                    </label>
                    <Toggle
                      id="sched-auto-restart"
                      on={values.auto_restart_on_crash === true}
                      onClick={() => setValue('auto_restart_on_crash', !values.auto_restart_on_crash)}
                    />
                  </div>

                  <div className="flex items-center justify-between gap-3">
                    <label
                      htmlFor="sched-daily-restart"
                      className="w-1/2 text-xs font-semibold uppercase tracking-wide text-slate-400"
                    >
                      {t('schedDailyRestartTime')}
                    </label>
                    <input
                      id="sched-daily-restart"
                      type="text"
                      placeholder="05:00"
                      value={values.daily_restart_time ?? ''}
                      onChange={(e) => setValue('daily_restart_time', e.target.value)}
                      className={inputClass + ' w-1/2 font-mono'}
                    />
                  </div>
                </div>
              </SpotlightCard>
            </TiltCard>

            {result && (
              <div
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

            <div className="flex items-center gap-2 rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-3 py-2 text-xs font-semibold text-cyan-300">
              <CalendarClock className="h-4 w-4 shrink-0" />
              <span>{t('schedAppliesNow')}</span>
            </div>
          </div>

          <div className="flex justify-end gap-3 border-t border-white/10 pt-4">
            <button
              onClick={onClose}
              className="flex min-h-[44px] items-center rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-xs font-bold text-slate-300 transition-all duration-200 hover:border-white/25 hover:bg-white/15 hover:text-white active:scale-95 active:bg-white/25"
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
        </motion.div>
      </div>
    </AnimatePresence>
  );
}
