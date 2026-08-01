import React from 'react';

/**
 * Aurora — ReactBits Organic Background Component
 * Fondo ambiental orgánico de auroras fluidas en movimiento constante.
 */
export default function Aurora({
  colorStops = ['#059669', '#0891b2', '#7c3aed'],
  className = ''
}) {
  return (
    <div className={`pointer-events-none fixed inset-0 z-0 overflow-hidden bg-[#070a12] ${className}`}>
      {/* Esferas de luz ambiental Aurora */}
      <div
        className="absolute -top-20 -left-20 h-[700px] w-[700px] rounded-full blur-[120px] opacity-60 animate-pulse"
        style={{
          background: `radial-gradient(circle, ${colorStops[0]} 0%, transparent 65%)`,
          animationDuration: '6s'
        }}
      />
      <div
        className="absolute top-1/4 -right-20 h-[800px] w-[800px] rounded-full blur-[140px] opacity-50 animate-pulse"
        style={{
          background: `radial-gradient(circle, ${colorStops[1]} 0%, transparent 65%)`,
          animationDuration: '9s',
          animationDelay: '1.5s'
        }}
      />
      <div
        className="absolute -bottom-20 left-1/3 h-[750px] w-[750px] rounded-full blur-[130px] opacity-55 animate-pulse"
        style={{
          background: `radial-gradient(circle, ${colorStops[2]} 0%, transparent 65%)`,
          animationDuration: '8s',
          animationDelay: '3s'
        }}
      />
    </div>
  );
}
