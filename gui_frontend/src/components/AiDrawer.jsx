import React, { useState, useEffect, useCallback, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Sparkles, X } from 'lucide-react';
import AiSidebar from './AiSidebar';
import { useI18n } from '../i18n.jsx';

/**
 * AiDrawer — botón flotante + panel lateral deslizante para el Asistente IA.
 * El contenido (AiSidebar) se monta solo con el drawer abierto para no
 * duplicar el polling de /api/ai/status con el resto de la GUI.
 */
export default function AiDrawer({ onSendCommand, isRunning = false }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [lmOnline, setLmOnline] = useState(false);
  const panelRef = useRef(null);
  const triggerRef = useRef(null);

  const checkStatus = useCallback(async () => {
    try {
      const res = await fetch('/api/ai/status');
      if (res.ok) {
        const data = await res.json();
        setLmOnline(!!data.online);
      } else {
        setLmOnline(false);
      }
    } catch {
      setLmOnline(false);
    }
  }, []);

  useEffect(() => {
    checkStatus();
    const id = setInterval(checkStatus, 15000);
    return () => clearInterval(id);
  }, [checkStatus]);

  // Cerrar con Escape y bloquear el scroll del fondo mientras está abierto
  useEffect(() => {
    if (!open) return;
    const trigger = triggerRef.current;
    const onKey = (e) => {
      if (e.key === 'Escape') { e.stopPropagation(); setOpen(false); return; }
      if (e.key !== 'Tab' || !panelRef.current) return;
      const focusables = [...panelRef.current.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')]
        .filter(element => !element.disabled && element.getClientRects().length);
      if (!focusables.length) { e.preventDefault(); return; }
      const first = focusables[0], last = focusables.at(-1);
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    // Foco al campo de texto al abrir (apertura siempre iniciada por el usuario)
    const raf = requestAnimationFrame(() => {
      panelRef.current?.querySelector('textarea')?.focus();
    });
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = prev;
      cancelAnimationFrame(raf);
      trigger?.focus();
    };
  }, [open ]);

  return (
    <>
      {/* Botón flotante (oculto mientras el panel está abierto) */}
        <button
          ref={triggerRef}
          hidden={open}
          type="button"
          onClick={() => setOpen(true)}
          aria-label={t('aiOpen')}
          title={t('aiTitle')}
          className="ai-launcher button"
        >
          <Sparkles className="h-6 w-6" aria-hidden="true" />
          <span
            aria-hidden="true"
            title={lmOnline ? t('aiLmStudioOnline') : t('aiLmStudioOffline')}
            className={`absolute -right-0.5 -top-0.5 h-3.5 w-3.5 rounded-full ring-2 ring-slate-950 ${
              lmOnline ? 'bg-emerald-400' : 'bg-rose-500'
            }`}
          />
        </button>

      {/* Fondo: click para cerrar */}
      <AnimatePresence>
        {open && (
          <motion.div
            key="ai-backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={() => setOpen(false)}
            className="ai-backdrop"
            aria-hidden="true"
          />
        )}
      </AnimatePresence>

      {/* Panel lateral deslizante */}
      <AnimatePresence>
        {open && (
          <motion.aside
            key="ai-panel"
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-label={t('aiTitle')}
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ type: 'tween', duration: 0.28, ease: 'easeOut' }}
            className="ai-panel legacy-ui"
          >
            <div className="flex items-center justify-between border-b border-white/10 px-4 py-3">
              <span className="text-sm font-semibold text-slate-100">{t('aiTab')}</span>
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label={t('aiClose')}
                className="rounded-lg p-1.5 text-slate-400 transition hover:bg-white/5 hover:text-slate-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-300"
              >
                <X className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-4">
              <AiSidebar onSendCommand={onSendCommand} isRunning={isRunning} />
            </div>
          </motion.aside>
        )}
      </AnimatePresence>
    </>
  );
}
