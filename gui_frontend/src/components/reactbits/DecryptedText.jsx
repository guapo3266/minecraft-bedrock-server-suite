import React, { useState, useEffect } from 'react';

/**
 * DecryptedText — ReactBits Component (.jsx)
 * Efecto de desencriptado cyberpunk para textos y estados.
 */
export default function DecryptedText({ 
  text, 
  speed = 40, 
  maxIterations = 10, 
  sequential = true, 
  className = "",
  animateOnMount = true
}) {
  const [displayText, setDisplayText] = useState(text);
  const characters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@#$%&*';

  useEffect(() => {
    let currentIteration = 0;
    let interval = null;

    interval = setInterval(() => {
      setDisplayText(() => {
        return text
          .split('')
          .map((char, index) => {
            if (char === ' ') return ' ';
            if (sequential) {
              if (index < currentIteration / maxIterations * text.length) {
                return text[index];
              }
            } else {
              if (currentIteration >= maxIterations) {
                return text[index];
              }
            }
            return characters[Math.floor(Math.random() * characters.length)];
          })
          .join('');
      });

      currentIteration += 1;

      if (currentIteration > maxIterations * (sequential ? text.length / 2 : 1)) {
        clearInterval(interval);
        setDisplayText(text);
      }
    }, speed);

    return () => clearInterval(interval);
  }, [text, speed, maxIterations, sequential]);

  return <span className={className}>{displayText}</span>;
}
