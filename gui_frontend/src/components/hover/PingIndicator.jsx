import React from 'react';
import { motion } from 'framer-motion';
import { useI18n } from '../../i18n.jsx';

/**
 * PingIndicator — ItsHover / Hover.dev Component (.jsx)
 * Indicador de latencia y estado en tiempo real con pulsaciones concéntricas.
 */
export default function PingIndicator({ status, latency = null }) {
  const { t } = useI18n();
  const isOnline = status.running;
  const isBackup = status.backup_in_progress;

  let color = "bg-rose-500";
  let ringColor = "border-rose-500/50";
  let text = t('disconnected');

  if (isBackup) {
    color = "bg-amber-400";
    ringColor = "border-amber-400/50";
    text = t('hotBackup');
  } else if (isOnline) {
    color = "bg-emerald-400";
    ringColor = "border-emerald-400/50";
    text = latency != null ? t('latency', { ms: Math.max(latency, 0) }) : t('online');
  }

  return (
    <div className="flex items-center gap-2.5 rounded-full border border-white/10 bg-black/40 px-3 py-1 font-mono text-[11px] font-bold text-slate-300 backdrop-blur-md">
      <div className="relative flex h-2.5 w-2.5 items-center justify-center">
        <motion.span
          animate={{ scale: [1, 2.2, 1], opacity: [0.8, 0, 0.8] }}
          transition={{ repeat: Infinity, duration: 2, ease: "easeInOut" }}
          className={`absolute h-full w-full rounded-full border ${ringColor}`}
        />
        <span className={`h-2 w-2 rounded-full ${color}`} />
      </div>
      <span>{text}</span>
    </div>
  );
}
