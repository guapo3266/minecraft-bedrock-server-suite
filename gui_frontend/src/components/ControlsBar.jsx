import React from 'react';
import ConfirmButton from './hover/ConfirmButton';
import ShinyText from './reactbits/ShinyText';
import { Play, Square, RotateCw, Save } from 'lucide-react';
import { useI18n } from '../i18n.jsx';

export default function ControlsBar({ status, onAction }) {
  const { t } = useI18n();
  const isRunning = status.running;

  return (
    <section className="relative z-10 flex flex-wrap gap-4">
      {/* Start Button */}
      <div className="flex-1 min-w-[200px]">
        <ConfirmButton
          onClick={() => onAction('start')}
          disabled={isRunning}
          variant="emerald"
          className="w-full py-4 text-base"
        >
          <Play className="h-5 w-5 text-emerald-400 fill-emerald-400" />
          <ShinyText text={t('start')} />
        </ConfirmButton>
      </div>

      {/* Stop Button */}
      <div className="flex-1 min-w-[200px]">
        <ConfirmButton
          onClick={() => onAction('stop')}
          disabled={!isRunning}
          variant="rose"
          className="w-full py-4 text-base"
        >
          <Square className="h-5 w-5 text-rose-400 fill-rose-400" />
          <ShinyText text={t('stop')} />
        </ConfirmButton>
      </div>

      {/* Restart Button */}
      <div className="flex-1 min-w-[200px]">
        <ConfirmButton
          onClick={() => onAction('restart')}
          disabled={!isRunning}
          variant="purple"
          className="w-full py-4 text-base"
        >
          <RotateCw className="h-5 w-5 text-purple-400" />
          <ShinyText text={t('restart')} />
        </ConfirmButton>
      </div>

      {/* Backup Button */}
      <div className="flex-1 min-w-[200px]">
        <ConfirmButton
          onClick={() => onAction('backup')}
          variant="amber"
          className="w-full py-4 text-base"
        >
          <Save className="h-5 w-5 text-amber-400" />
          <ShinyText text={t('backup')} />
        </ConfirmButton>
      </div>
    </section>
  );
}
