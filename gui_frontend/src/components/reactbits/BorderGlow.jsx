import React from 'react';

/**
 * BorderGlow — ReactBits Component (.jsx)
 * Borde reluciente animado para tarjetas de alto impacto.
 */
export default function BorderGlow({ children, className = "", glowColor = "from-emerald-500 via-cyan-500 to-purple-500" }) {
  return (
    <div className={`relative p-[1px] overflow-hidden rounded-2xl ${className}`}>
      <div className={`absolute -inset-[100%] animate-[spin_4s_linear_infinite] bg-[conic-gradient(from_90deg_at_50%_50%,#10b981_0%,#06b6d4_50%,#8b5cf6_100%)] opacity-70 blur-sm`} />
      <div className="relative rounded-[15px] bg-slate-950 h-full w-full">
        {children}
      </div>
    </div>
  );
}
