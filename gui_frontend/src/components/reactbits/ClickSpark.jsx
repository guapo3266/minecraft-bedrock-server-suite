import React, { useState, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

export default function ClickSpark({
  children,
  sparkColor = '#10b981',
  sparkSize = 16,
  sparkCount = 10,
  duration = 0.5,
  className = '',
  onClick,
  disabled = false,
  ...props
}) {
  const [sparks, setSparks] = useState([]);
  const containerRef = useRef(null);

  const handleClick = (e) => {
    if (disabled) return;

    if (containerRef.current) {
      const rect = containerRef.current.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;

      const now = Date.now();
      const newSparks = Array.from({ length: sparkCount }).map((_, i) => ({
        id: `${now}-${i}`,
        x,
        y,
        angle: (i * 360) / sparkCount,
        distance: sparkSize + Math.random() * 10,
      }));

      setSparks(newSparks);
    }

    if (onClick) onClick(e);
  };

  return (
    <div
      ref={containerRef}
      onClick={handleClick}
      className={`relative inline-block w-full ${className}`}
      {...props}
    >
      {children}
      <svg
        className="pointer-events-none absolute inset-0 z-50 h-full w-full overflow-visible"
        style={{ pointerEvents: 'none' }}
      >
        <AnimatePresence>
          {sparks.map((spark) => {
            const rad = (spark.angle * Math.PI) / 180;
            const targetX = spark.x + Math.cos(rad) * (spark.distance + 12);
            const targetY = spark.y + Math.sin(rad) * (spark.distance + 12);

            return (
              <motion.line
                key={spark.id}
                initial={{
                  x1: spark.x,
                  y1: spark.y,
                  x2: spark.x,
                  y2: spark.y,
                  opacity: 1,
                  strokeWidth: 3.5,
                }}
                animate={{
                  x1: spark.x + Math.cos(rad) * 6,
                  y1: spark.y + Math.sin(rad) * 6,
                  x2: targetX,
                  y2: targetY,
                  opacity: 0,
                  strokeWidth: 1,
                }}
                exit={{ opacity: 0 }}
                transition={{ duration: duration, ease: 'easeOut' }}
                stroke={sparkColor}
                strokeLinecap="round"
                style={{
                  filter: `drop-shadow(0 0 8px ${sparkColor})`,
                }}
              />
            );
          })}
        </AnimatePresence>
      </svg>
    </div>
  );
}
