import React from 'react';

// Sparkline SVG pura (sin dependencias): polyline + area con gradiente.
// viewBox 100x100 con preserveAspectRatio="none": se estira al contenedor.
export default function Sparkline({ values = [], color = '#10b981', height = 36, id }) {
  if (values.length < 2) {
    return (
      <div
        style={{ height }}
        className="w-full rounded-md border border-dashed border-white/10"
        title={id}
      />
    );
  }
  const max = Math.max(...values);
  const min = Math.min(...values);
  const range = max - min || 1;
  const pts = values.map((v, i) => {
    const x = (i / (values.length - 1)) * 100;
    const y = 100 - ((v - min) / range) * 100;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });
  const gradientId = `spark-${id}`;
  return (
    <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="block w-full" style={{ height }}>
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.35" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={`0,100 ${pts.join(' ')} 100,100`} fill={`url(#${gradientId})`} />
      <polyline
        points={pts.join(' ')}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        vectorEffect="non-scaling-stroke"
        strokeLinejoin="round"
      />
    </svg>
  );
}
