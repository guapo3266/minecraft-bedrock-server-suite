import React, { useEffect, useState } from 'react';

/**
 * CountUp — ReactBits Component (.jsx)
 * Animación fluida de incremento numérico para contadores y métricas.
 */
export default function CountUp({ to, duration = 1, decimals = 0, className = "" }) {
  const [count, setCount] = useState(0);

  useEffect(() => {
    let startTimestamp = null;
    const startValue = count;
    const endValue = Number(to) || 0;

    const step = (timestamp) => {
      if (!startTimestamp) startTimestamp = timestamp;
      const progress = Math.min((timestamp - startTimestamp) / (duration * 1000), 1);
      const currentValue = startValue + (endValue - startValue) * progress;

      setCount(currentValue);

      if (progress < 1) {
        requestAnimationFrame(step);
      } else {
        setCount(endValue);
      }
    };

    requestAnimationFrame(step);
  }, [to, duration]);

  return <span className={className}>{count.toFixed(decimals)}</span>;
}
