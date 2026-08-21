import React, { useState } from 'react';
import { motion } from 'framer-motion';
import ClickSpark from '../reactbits/ClickSpark';
import { useI18n } from '../../i18n.jsx';

export default function ConfirmButton({
  children,
  onClick,
  variant = 'emerald', // emerald, rose, purple, amber, cyan
  disabled = false,
  cooldownMs = 1200,
  sparkColor,
  className = '',
  ...props
}) {
  const [isCoolingDown, setIsCoolingDown] = useState(false);
  const { t } = useI18n();

  const variantStyles = {
    emerald: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/50 hover:bg-emerald-500/30 shadow-[0_0_20px_rgba(16,185,129,0.25)]',
    // Variante solida para la accion primaria (Iniciar): destaca sobre las
    // ghost y usa texto negro (ShinyText blanco no daria contraste).
    emeraldSolid: 'bg-emerald-500 text-black border-emerald-400 hover:bg-emerald-400 shadow-[0_0_20px_rgba(16,185,129,0.35)]',
    rose: 'bg-rose-500/20 text-rose-300 border-rose-500/50 hover:bg-rose-500/30 shadow-[0_0_20px_rgba(244,63,94,0.25)]',
    purple: 'bg-purple-500/20 text-purple-300 border-purple-500/50 hover:bg-purple-500/30 shadow-[0_0_20px_rgba(168,85,247,0.25)]',
    amber: 'bg-amber-500/20 text-amber-300 border-amber-500/50 hover:bg-amber-500/30 shadow-[0_0_20px_rgba(245,158,11,0.25)]',
    cyan: 'bg-cyan-500/20 text-cyan-300 border-cyan-500/50 hover:bg-cyan-500/30 shadow-[0_0_20px_rgba(6,182,212,0.25)]'
  };

  const defaultSparkColors = {
    emerald: '#10b981',
    rose: '#f43f5e',
    purple: '#a855f7',
    amber: '#f59e0b',
    cyan: '#06b6d4'
  };

  const currentSparkColor = sparkColor || defaultSparkColors[variant] || '#10b981';

  const handleClick = async (e) => {
    if (disabled || isCoolingDown) return;

    setIsCoolingDown(true);

    try {
      if (onClick) await onClick(e);
    } finally {
      setTimeout(() => {
        setIsCoolingDown(false);
      }, cooldownMs);
    }
  };

  const isBtnDisabled = disabled || isCoolingDown;

  return (
    <ClickSpark sparkColor={currentSparkColor} disabled={isBtnDisabled} sparkCount={10}>
      <motion.button
        whileHover={isBtnDisabled ? {} : { scale: 1.03 }}
        whileTap={isBtnDisabled ? {} : { scale: 0.94 }}
        transition={{ type: 'spring', stiffness: 400, damping: 17 }}
        onClick={handleClick}
        disabled={isBtnDisabled}
        className={`relative flex items-center justify-center gap-2 rounded-xl border px-5 py-3 text-sm font-bold transition duration-200 ${
          isBtnDisabled
            ? 'opacity-60 cursor-not-allowed border-slate-700 bg-slate-900/50 text-slate-400'
            : variantStyles[variant] || variantStyles.emerald
        } ${className}`}
        {...props}
      >
        {isCoolingDown ? (
          <span className="flex items-center gap-2 text-slate-300 animate-pulse">
            <svg className="h-4 w-4 animate-spin text-current" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
              />
            </svg>
            <span>{t('sending')}</span>
          </span>
        ) : (
          children
        )}
      </motion.button>
    </ClickSpark>
  );
}
