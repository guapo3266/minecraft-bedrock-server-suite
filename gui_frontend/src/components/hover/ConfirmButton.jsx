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
    emerald: 'primary',
    // El nombre histórico se conserva; ahora la acción primaria usa el borde
    // y texto de acento, con el mismo material neutral que la referencia.
    emeraldSolid: 'primary',
    rose: 'danger',
    purple: '',
    amber: '',
    cyan: 'primary'
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
        whileTap={isBtnDisabled ? {} : { y: 1 }}
        transition={{ type: 'spring', stiffness: 400, damping: 17 }}
        onClick={handleClick}
        disabled={isBtnDisabled}
        className={`button ${variantStyles[variant] ?? variantStyles.emerald} ${className}`}
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
