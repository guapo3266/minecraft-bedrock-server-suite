import React from 'react';

/**
 * ShinyText — ReactBits Component (.jsx)
 * Texto con efecto metálico reluciente animado.
 */
export default function ShinyText({ text, disabled = false, speed = 3, className = "" }) {
  if (disabled) return <span className={className}>{text}</span>;

  return (
    <span
      className={`shiny-text ${className}`}
      style={{ animationDuration: `${speed}s` }}
    >
      {text}
    </span>
  );
}
