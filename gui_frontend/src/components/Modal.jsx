import React, { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { motion } from 'framer-motion';

// Modal base compartido: semantica de dialogo (role/aria-modal), cierre con
// Escape, foco inicial en la tarjeta + restauracion al cerrar, trampa de Tab
// y overscroll contenida. Se renderiza via portal a body para que ningún
// stacking context ancestro (secciones z-10, transforms) lo tapen o desvien.
// La animacion replica el patron spring que ya usaban los modales originales.
export default function Modal({ onClose, label, children, className = '' }) {
  const cardRef = useRef(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const restoreFocusRef = useRef(null);

  useEffect(() => {
    restoreFocusRef.current = document.activeElement;
    if (cardRef.current) cardRef.current.focus();

    const onKey = (ev) => {
      if (ev.key === 'Escape') {
        onCloseRef.current();
        return;
      }
      if (ev.key !== 'Tab') return;
      const card = cardRef.current;
      if (!card) return;
      const focusables = card.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );
      if (focusables.length === 0) {
        ev.preventDefault();
        return;
      }
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (ev.shiftKey && document.activeElement === first) {
        ev.preventDefault();
        last.focus();
      } else if (!ev.shiftKey && document.activeElement === last) {
        ev.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      // Devolver el foco a quien abrio el modal (si sigue en el DOM)
      const el = restoreFocusRef.current;
      if (el && el.isConnected && typeof el.focus === 'function') el.focus();
    };
  }, []);

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={() => onCloseRef.current()}
        className="absolute inset-0 bg-black/75 backdrop-blur-md"
      />
      <motion.div
        ref={cardRef}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        tabIndex={-1}
        initial={{ scale: 0.8, opacity: 0, y: 20 }}
        animate={{ scale: 1, opacity: 1, y: 0 }}
        exit={{ scale: 0.8, opacity: 0, y: 20 }}
        transition={{ type: 'spring', stiffness: 300, damping: 20 }}
        className={`relative z-10 w-full rounded-2xl border border-white/10 bg-slate-950 p-6 shadow-2xl outline-none overscroll-contain ${className}`}
      >
        {children}
      </motion.div>
    </div>,
    document.body
  );
}
