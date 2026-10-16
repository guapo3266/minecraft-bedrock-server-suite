import React from 'react';

/**
 * Fachada compatible: valor formateado sin interpolación decorativa.
 */
export default function CountUp({ to, duration: _duration, decimals = 0, className = "" }) {
  // Lectura inmediata, como en el origen: no simular valores intermedios al
  // llegar una muestra nueva ni arrancar frames decorativos por cada métrica.
  return <span className={className}>{(Number(to) || 0).toFixed(decimals)}</span>;
}
