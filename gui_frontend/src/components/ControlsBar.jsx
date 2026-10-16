import React, { useState } from 'react';
import { AnimatePresence } from 'framer-motion';
import ConfirmButton from './hover/ConfirmButton';
import ShinyText from './reactbits/ShinyText';
import Modal from './Modal';
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
    <section className="controls-panel panel legacy-ui" aria-label={t('serverControls')}>
      <div className="controls-context">
        <h1>{t('serverTab')}</h1>
        <p>{isRunning ? t('connectedPlayers', { count: status.player_count ?? 0 }) : t('startServerHint')}</p>
      </div>
      <div className="controls-actions">
      {/* Solo Iniciar tiene tratamiento primario, y solo si está disponible. */}
      <ConfirmButton
        onClick={() => onAction('start')}
        disabled={isRunning}
        variant="emeraldSolid"
        className={`control-start ${isRunning ? '' : 'strong-primary'}`}
      >
        <Play className="h-4 w-4 fill-current" />
        {t('start')}
      </ConfirmButton>

      {/* Stop Button */}
      <ConfirmButton
        onClick={() => setConfirmAction('stop')}
        disabled={!isRunning}
        variant="rose"
        className="control-danger"
      >
        <Square className="h-4 w-4 fill-current" />
        <ShinyText text={t('stop')} />
      </ConfirmButton>

      {/* Restart Button */}
      <ConfirmButton
        onClick={() => setConfirmAction('restart')}
        disabled={!isRunning}
        variant="purple"
        className="control-secondary"
      >
        <RotateCw className="h-4 w-4" />
        <ShinyText text={t('restart')} />
      </ConfirmButton>

      {/* Backup Button */}
      <ConfirmButton
        onClick={() => onAction('backup')}
        variant="amber"
        className="control-secondary"
        disabled={status?.backup_in_progress}
      >
        <Save className="h-4 w-4" />
        <ShinyText text={t('backup')} />
      </ConfirmButton>
      </div>

      {/* Modal de confirmación para acciones destructivas (stop/restart).
          El Modal base vive en portal a body: dentro de la section
          (stacking context z-10) quedaría tapado por las secciones siguientes. */}
      <AnimatePresence>
        {confirmProps && (
          <Modal onClose={() => setConfirmAction(null)} label={confirmProps.title} className="max-w-sm">
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
              <button onClick={() => setConfirmAction(null)} aria-label={t('close')} className="rounded-lg p-1 text-slate-400 hover:bg-white/10 hover:text-white">
                <X className="h-5 w-5" />
              </button>
            </div>

            <p className="my-6 text-sm text-slate-300">{confirmProps.msg}</p>

            <div className="flex justify-end gap-3 border-t border-white/10 pt-4">
              <button
                onClick={() => setConfirmAction(null)}
                className="flex min-h-[44px] items-center rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-xs font-bold text-slate-300 transition duration-200 hover:border-white/25 hover:bg-white/15 hover:text-white active:scale-95"
              >
                {t('cancel')}
              </button>
              <button
                onClick={runConfirmed}
                className={`flex min-h-[44px] items-center rounded-xl px-5 py-2 text-xs font-bold text-black transition duration-200 hover:brightness-110 active:scale-95 ${
                  confirmProps.variant === 'rose'
                    ? 'bg-gradient-to-r from-rose-500 to-orange-500 shadow-[0_0_20px_rgba(244,63,94,0.4)]'
                    : 'bg-gradient-to-r from-purple-500 to-indigo-500 shadow-[0_0_20px_rgba(168,85,247,0.4)]'
                }`}
              >
                {t('confirm')}
              </button>
            </div>
          </Modal>
        )}
      </AnimatePresence>
    </section>
  );
}
