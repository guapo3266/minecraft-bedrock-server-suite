import React from 'react';

/**
 * Fachada compatible de tarjeta: contenedor estable del sistema de vidrio.
 */
export default function TiltCard({ children, className = "" }) {
  // Se conserva la fachada para no reescribir formularios funcionales. El
  // diseño nuevo usa superficies estables, no inclinación ni translateZ.
  return <div className={`card-frame ${className}`}>{children}</div>;
}
