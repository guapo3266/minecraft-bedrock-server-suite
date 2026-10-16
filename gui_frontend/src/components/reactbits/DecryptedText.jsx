import React from 'react';

/**
 * Fachada compatible: texto inmediato, sin alterar temporalmente su contenido.
 */
export default function DecryptedText({ 
  text, 
  speed: _speed,
  maxIterations: _maxIterations,
  sequential: _sequential,
  className = ""
}) {
  return <span className={className}>{text}</span>;
}
