import React, { useEffect, useRef } from 'react';

/**
 * Silk — ReactBits Component (.jsx)
 * Fondo orgánico Duo-Tone con exactamente 1 color principal (Esmeralda #10b981)
 * y 1 color secundario (Cyan #06b6d4) sobre fondo oscuro slate.
 */
export default function Silk({
  primaryColor = '#10b981',
  secondaryColor = '#06b6d4',
  className = ''
}) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    let animationId;
    let step = 0;

    const handleResize = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    };

    handleResize();
    window.addEventListener('resize', handleResize);

    const render = () => {
      step += 0.004;
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      // Dibujar 2 capas de ondas orgánicas fluidas Duo-Tone
      const drawWave = (color, offset, amplitude, frequency) => {
        ctx.beginPath();
        ctx.fillStyle = color;

        ctx.moveTo(0, canvas.height);
        for (let x = 0; x <= canvas.width; x += 15) {
          const y =
            Math.sin(x * frequency + step + offset) * amplitude +
            canvas.height * 0.45 +
            Math.cos(x * 0.002 + step) * 40;
          ctx.lineTo(x, y);
        }
        ctx.lineTo(canvas.width, canvas.height);
        ctx.closePath();
        ctx.fill();
      };

      // Gradient 1: Color Principal (Esmeralda)
      const grad1 = ctx.createLinearGradient(0, 0, canvas.width, canvas.height);
      grad1.addColorStop(0, 'rgba(16, 185, 129, 0.12)');
      grad1.addColorStop(1, 'rgba(16, 185, 129, 0.02)');
      drawWave(grad1, 0, 50, 0.003);

      // Gradient 2: Color Secundario (Cyan)
      const grad2 = ctx.createLinearGradient(canvas.width, 0, 0, canvas.height);
      grad2.addColorStop(0, 'rgba(6, 182, 212, 0.14)');
      grad2.addColorStop(1, 'rgba(6, 182, 212, 0.02)');
      drawWave(grad2, Math.PI, 65, 0.002);

      animationId = requestAnimationFrame(render);
    };

    render();

    return () => {
      cancelAnimationFrame(animationId);
      window.removeEventListener('resize', handleResize);
    };
  }, [primaryColor, secondaryColor]);

  return (
    <div className={`pointer-events-none fixed inset-0 z-0 bg-[#070a12] ${className}`}>
      <canvas ref={canvasRef} className="h-full w-full opacity-90" />
    </div>
  );
}
