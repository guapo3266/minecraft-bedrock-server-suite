import React from 'react';
import { motion } from 'framer-motion';

/**
 * SpringChip — Hover.dev Component (.jsx)
 * Botón chip interactivo con físicas de resorte en hover.
 */
export default function SpringChip({ text, onClick }) {
  return (
    <motion.button
      onClick={onClick}
      whileHover={{ scale: 1.08, y: -2 }}
      whileTap={{ scale: 0.95 }}
      transition={{ type: "spring", stiffness: 400, damping: 17 }}
      className="relative overflow-hidden rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 font-mono text-xs text-slate-300 backdrop-blur-md hover:border-emerald-500/50 hover:bg-emerald-500/10 hover:text-white shadow-lg"
    >
      {text}
    </motion.button>
  );
}
