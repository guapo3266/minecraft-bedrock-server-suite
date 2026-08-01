import React, { useEffect, useRef } from 'react';

/**
 * Particles — ReactBits Component (.jsx)
 * Red de partículas Canvas interactivas en segundo plano.
 */
export default function Particles({
  particleCount = 50,
  particleColors = ['#10b981', '#06b6d4'],
  className = ""
}) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    let animationFrameId;
    let particles = [];
    const mouse = { x: null, y: null, radius: 120 };

    const handleResize = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    };

    const handleMouseMove = (e) => {
      mouse.x = e.clientX;
      mouse.y = e.clientY;
    };

    handleResize();

    for (let i = 0; i < particleCount; i++) {
      particles.push({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        vx: (Math.random() - 0.5) * 0.6,
        vy: (Math.random() - 0.5) * 0.6,
        size: Math.random() * 2 + 1,
        color: particleColors[i % particleColors.length]
      });
    }

    const render = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      for (let i = 0; i < particles.length; i++) {
        let p = particles[i];
        p.x += p.vx;
        p.y += p.vy;

        if (p.x < 0 || p.x > canvas.width) p.vx *= -1;
        if (p.y < 0 || p.y > canvas.height) p.vy *= -1;

        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
        ctx.fillStyle = p.color;
        ctx.fill();

        for (let j = i + 1; j < particles.length; j++) {
          let p2 = particles[j];
          let dx = p.x - p2.x;
          let dy = p.y - p2.y;
          let dist = Math.sqrt(dx * dx + dy * dy);

          if (dist < 110) {
            ctx.beginPath();
            ctx.moveTo(p.x, p.y);
            ctx.lineTo(p2.x, p2.y);
            ctx.strokeStyle = `rgba(16, 185, 129, ${1 - dist / 110 * 0.8})`;
            ctx.lineWidth = 0.5;
            ctx.stroke();
          }
        }

        if (mouse.x !== null) {
          let mdx = p.x - mouse.x;
          let mdy = p.y - mouse.y;
          let mdist = Math.sqrt(mdx * mdx + mdy * mdy);
          if (mdist < mouse.radius) {
            let force = (mouse.radius - mdist) / mouse.radius;
            p.x += (mdx / mdist) * force * 3;
            p.y += (mdy / mdist) * force * 3;
          }
        }
      }

      animationFrameId = requestAnimationFrame(render);
    };

    render();

    window.addEventListener('resize', handleResize);
    window.addEventListener('mousemove', handleMouseMove);

    return () => {
      cancelAnimationFrame(animationFrameId);
      window.removeEventListener('resize', handleResize);
      window.removeEventListener('mousemove', handleMouseMove);
    };
  }, [particleCount]);

  return <canvas ref={canvasRef} className={`fixed inset-0 pointer-events-none z-0 ${className}`} />;
}
