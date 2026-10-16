import React from 'react';

/**
 * Fachada compatible: texto legible con color heredado, sin barrido metálico.
 */
export default function ShinyText({ text, disabled: _disabled, speed: _speed, className = "" }) {
  // El texto siempre hereda el color semántico y mantiene su opacidad.
  return <span className={className}>{text}</span>;
}
