/**
 * reactbits.js — Motor de Componentes y Micro-animaciones ReactBits en Vanilla JS
 * ==============================================================================
 * Implementa:
 *   1. ParticlesBackground: Red de partículas interactivas en HTML5 Canvas
 *   2. SpotlightCard: Seguimiento radial del puntero en tarjetas
 *   3. DecryptedText: Efecto de desencriptado/matriz de texto
 *   4. MagneticButton: Atracción elástica de botones al cursor
 */

// ═══════════════════════════════════════════════════════════════
// 1. PARTICLES BACKGROUND (Lienzo interactivo de nodos)
// ═══════════════════════════════════════════════════════════════
class ParticlesBackground {
  constructor(canvasId) {
    this.canvas = document.getElementById(canvasId);
    if (!this.canvas) return;
    this.ctx = this.canvas.getContext('2d');
    this.particles = [];
    this.numParticles = 45;
    this.mouse = { x: null, y: null, radius: 120 };

    this.init();
    this.animate();

    window.addEventListener('resize', () => this.resize());
    window.addEventListener('mousemove', (e) => {
      this.mouse.x = e.x;
      this.mouse.y = e.y;
    });
  }

  init() {
    this.resize();
    this.particles = [];
    for (let i = 0; i < this.numParticles; i++) {
      this.particles.push({
        x: Math.random() * this.canvas.width,
        y: Math.random() * this.canvas.height,
        vx: (Math.random() - 0.5) * 0.6,
        vy: (Math.random() - 0.5) * 0.6,
        size: Math.random() * 2 + 1,
        color: i % 2 === 0 ? '#10b981' : '#06b6d4'
      });
    }
  }

  resize() {
    this.canvas.width = window.innerWidth;
    this.canvas.height = window.innerHeight;
  }

  animate() {
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

    for (let i = 0; i < this.particles.length; i++) {
      let p = this.particles[i];

      p.x += p.vx;
      p.y += p.vy;

      if (p.x < 0 || p.x > this.canvas.width) p.vx *= -1;
      if (p.y < 0 || p.y > this.canvas.height) p.vy *= -1;

      // Dibujar punto
      this.ctx.beginPath();
      this.ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
      this.ctx.fillStyle = p.color;
      this.ctx.fill();

      // Conectar líneas entre partículas cercanas
      for (let j = i + 1; j < this.particles.length; j++) {
        let p2 = this.particles[j];
        let dx = p.x - p2.x;
        let dy = p.y - p2.y;
        let dist = Math.sqrt(dx * dx + dy * dy);

        if (dist < 110) {
          this.ctx.beginPath();
          this.ctx.moveTo(p.x, p.y);
          this.ctx.lineTo(p2.x, p2.y);
          this.ctx.strokeStyle = `rgba(16, 185, 129, ${1 - dist / 110 * 0.8})`;
          this.ctx.lineWidth = 0.5;
          this.ctx.stroke();
        }
      }

      // Reacción física con el cursor
      if (this.mouse.x !== null) {
        let mdx = p.x - this.mouse.x;
        let mdy = p.y - this.mouse.y;
        let mdist = Math.sqrt(mdx * mdx + mdy * mdy);
        if (mdist < this.mouse.radius) {
          let force = (this.mouse.radius - mdist) / this.mouse.radius;
          p.x += (mdx / mdist) * force * 3;
          p.y += (mdy / mdist) * force * 3;
        }
      }
    }

    requestAnimationFrame(() => this.animate());
  }
}


// ═══════════════════════════════════════════════════════════════
// 2. SPOTLIGHT CARD (Efecto de luz radial con puntero)
// ═══════════════════════════════════════════════════════════════
class SpotlightEffect {
  static init() {
    const cards = document.querySelectorAll('.spotlight-card');
    cards.forEach(card => {
      card.addEventListener('mousemove', (e) => {
        const rect = card.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        card.style.setProperty('--mouse-x', `${x}px`);
        card.style.setProperty('--mouse-y', `${y}px`);
      });
    });
  }
}


// ═══════════════════════════════════════════════════════════════
// 3. DECRYPTED TEXT (Efecto de desencriptado de caracteres)
// ═══════════════════════════════════════════════════════════════
class DecryptedText {
  static animate(element, targetText, duration = 800) {
    if (!element) return;
    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@#$%&*';
    const originalText = targetText || element.getAttribute('data-text') || element.textContent;
    let start = null;

    function step(timestamp) {
      if (!start) start = timestamp;
      let progress = timestamp - start;
      let factor = Math.min(progress / duration, 1);

      let revealedChars = Math.floor(factor * originalText.length);
      let result = '';

      for (let i = 0; i < originalText.length; i++) {
        if (i < revealedChars || originalText[i] === ' ') {
          result += originalText[i];
        } else {
          result += chars[Math.floor(Math.random() * chars.length)];
        }
      }

      element.textContent = result;

      if (factor < 1) {
        requestAnimationFrame(step);
      } else {
        element.textContent = originalText;
      }
    }

    requestAnimationFrame(step);
  }
}


// ═══════════════════════════════════════════════════════════════
// 4. MAGNETIC BUTTONS (Atracción elástica)
// ═══════════════════════════════════════════════════════════════
class MagneticButton {
  static init() {
    const buttons = document.querySelectorAll('.magnetic-btn');
    buttons.forEach(btn => {
      btn.addEventListener('mousemove', (e) => {
        const rect = btn.getBoundingClientRect();
        const x = e.clientX - rect.left - rect.width / 2;
        const y = e.clientY - rect.top - rect.height / 2;
        btn.style.transform = `translate(${x * 0.25}px, ${y * 0.25}px)`;
      });

      btn.addEventListener('mouseleave', () => {
        btn.style.transform = 'translate(0px, 0px)';
      });
    });
  }
}

// Inicialización global al cargar DOM
document.addEventListener('DOMContentLoaded', () => {
  new ParticlesBackground('particles-canvas');
  SpotlightEffect.init();
  MagneticButton.init();

  // Ejecutar desencriptado inicial en título
  const titleEl = document.getElementById('brand-title');
  if (titleEl) {
    DecryptedText.animate(titleEl, 'BEDROCK WRAPPER');
  }
});
