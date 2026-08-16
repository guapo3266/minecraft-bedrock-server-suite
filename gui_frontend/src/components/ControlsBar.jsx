import React, { useState } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import ConfirmButton from './hover/ConfirmButton';
import ShinyText from './reactbits/ShinyText';
import { Play, Square, RotateCw, Save, X, TriangleAlert } from 'lucide-react';
import { useI18n } from '../i18n.jsx';

export default function ControlsBar({ status, onAction }) {
  const { t } = useI18n();
  const isRunning = status.running;
  const [confirmAction, setConfirmAction] = useState(null);

  const confirmProps = confirmAction === 'stop'
    ? { title: t('confirmStopTitle'), msg: t('confirmStopMsg'), variant: 'rose' }
    : confirmAction === 'restart'
      ? { title: t('confirmRestartTitle'), msg: t('confirmRestartMsg'), variant: 'purple' }
      : null;

  const runConfirmed = () => {
    if (confirmAction) onAction(confirmAction);
    setConfirmAction(null);
  };

  return (
    <section className="relative z-10 grid grid-cols-2 gap-3 sm:gap-4 lg:flex">
      {/* Start Button — accion primaria: solida, sin ShinyText (texto negro) */}
      <ConfirmButton
        onClick={() => onAction('start')}
        disabled={isRunning}
        variant="emeraldSolid"
        className="w-full py-3.5 text-sm"
      >
        <Play className="h-5 w-5 text-black fill-black" />
        {t('start')}
      </ConfirmButton>

      {/* Stop Button */}
      <ConfirmButton
        onClick={() => setConfirmAction('stop')}
        disabled={!isRunning}
        variant="rose"
        className="w-full py-3.5 text-sm"
      >
        <Square className="h-5 w-5 text-rose-400 fill-rose-400" />
        <ShinyText text={t('stop')} />
      </ConfirmButton>

      {/* Restart Button */}
      <ConfirmButton
        onClick={() => setConfirmAction('restart')}
        disabled={!isRunning}
        variant="purple"
        className="w-full py-3.5 text-sm"
      >
        <RotateCw className="h-5 w-5 text-purple-400" />
        <ShinyText text={t('restart')} />
      </ConfirmButton>

      {/* Backup Button */}
      <ConfirmButton
        onClick={() => onAction('backup')}
        variant="amber"
        className="w-full py-3.5 text-sm"
        disabled={status?.backup_in_progress}
      >
        <Save className="h-5 w-5 text-amber-400" />
        <ShinyText text={t('backup')} />
      </ConfirmButton>

      {/* Modal de confirmación para acciones destructivas (stop/restart).
          Se renderiza con portal a document.body: dentro de la section
          (stacking context z-10) quedaría tapado por las secciones siguientes. */}
      {createPortal(
        <AnimatePresence>
          {confirmProps && (
            <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setConfirmAction(null)}
              className="absolute inset-0 bg-black/75 backdrop-blur-md"
            />
            <motion.div
              initial={{ scale: 0.8, opacity: 0, y: 20 }}
              animate={{ scale: 1, opacity: 1, y: 0 }}
              exit={{ scale: 0.8, opacity: 0, y: 20 }}
              transition={{ type: 'spring', stiffness: 300, damping: 20 }}
              className="relative z-10 w-full max-w-sm rounded-2xl border border-white/10 bg-slate-950 p-6 shadow-2xl"
            >
              <div className="flex items-center justify-between border-b border-white/10 pb-4">
                <div className="flex items-center gap-3">
                  <div className={`flex h-10 w-10 items-center justify-center rounded-xl border ${
                    confirmProps.variant === 'rose'
                      ? 'bg-rose-500/20 border-rose-500/40'
                      : 'bg-purple-500/20 border-purple-500/40'
                  }`}>
                    <TriangleAlert className={`h-5 w-5 ${confirmProps.variant === 'rose' ? 'text-rose-400' : 'text-purple-400'}`} />
                  </div>
                  <h2 className="text-base font-bold text-white">{confirmProps.title}</h2>
                </div>
                <button onClick={() => setConfirmAction(null)} className="rounded-lg p-1 text-slate-400 hover:bg-white/10 hover:text-white">
                  <X className="h-5 w-5" />
                </button>
              </div>

              <p className="my-6 text-sm text-slate-300">{confirmProps.msg}</p>

              <div className="flex justify-end gap-3 border-t border-white/10 pt-4">
                <button
                  onClick={() => setConfirmAction(null)}
                  className="flex min-h-[44px] items-center rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-xs font-bold text-slate-300 transition-all duration-200 hover:border-white/25 hover:bg-white/15 hover:text-white active:scale-95"
                >
                  {t('cancel')}
                </button>
                <button
                  onClick={runConfirmed}
                  className={`flex min-h-[44px] items-center rounded-xl px-5 py-2 text-xs font-bold text-black transition-all duration-200 hover:brightness-110 active:scale-95 ${
                    confirmProps.variant === 'rose'
                      ? 'bg-gradient-to-r from-rose-500 to-orange-500 shadow-[0_0_20px_rgba(244,63,94,0.4)]'
                      : 'bg-gradient-to-r from-purple-500 to-indigo-500 shadow-[0_0_20px_rgba(168,85,247,0.4)]'
                  }`}
                >
                  {t('confirm')}
                </button>
              </div>
            </motion.div>
          </div>
        )}
        </AnimatePresence>,
        document.body
      )}
    </section>
  );
}
