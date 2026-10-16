import React from 'react';

/**
 * Fachada de tarjeta compartida: conserva los consumidores existentes,
 * ahora con el material neutral de Nokia WiFi Manager, sin halos de neón.
 */
export default function SpotlightCard({ 
  children, 
  className = "", 
  spotlightColor: _spotlightColor
}) {
  return (
    <div className={`panel legacy-ui ${className}`}>{children}</div>
  );
}
