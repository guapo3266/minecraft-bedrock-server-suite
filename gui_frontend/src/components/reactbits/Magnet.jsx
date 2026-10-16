import React from 'react';

/**
 * Fachada compatible: contenedor de acciones sin movimiento magnético.
 */
export default function Magnet({ children, disabled: _disabled = false, className = "" }) {
  return <div className={`inline-block ${className}`}>{children}</div>;
}
