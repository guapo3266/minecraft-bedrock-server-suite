import { forwardRef, useImperativeHandle, useCallback } from 'react';
import { motion, useAnimate } from 'framer-motion';

/**
 * AnimatedStatusIcons — ItsHover.com (adaptado a framer-motion)
 * Iconos animados con API imperativa (startAnimation/stopAnimation).
 */

export const FilledCheckedIcon = forwardRef(function FilledCheckedIcon(
  { size = 24, className = '', color = 'currentColor', strokeWidth = '1' },
  ref
) {
  const [scope, animate] = useAnimate();

  const start = useCallback(async () => {
    await animate(
      'svg',
      { scale: 1.1 },
      { duration: 0.1, ease: 'easeInOut' }
    );
    animate(
      '.filled-circle',
      { scale: 1.15, opacity: 0.8 },
      { duration: 0.15, ease: 'easeOut' }
    );
    await animate(
      '.check-icon',
      { pathLength: 0 },
      { duration: 0.1, ease: 'easeInOut' }
    );
    animate(
      '.filled-circle',
      { scale: 1, opacity: 1 },
      { duration: 0.3, ease: 'easeInOut' }
    );
    await animate(
      '.check-icon',
      { pathLength: 1 },
      { duration: 0.4, ease: 'easeInOut' }
    );
    await animate(
      'svg',
      { scale: 1 },
      { duration: 0.2, ease: 'easeInOut' }
    );
  }, [animate]);

  const stop = useCallback(() => {
    animate(
      'svg, .filled-circle, .check-icon',
      { scale: 1, opacity: 1, pathLength: 1 },
      { duration: 0.2, ease: 'easeInOut' }
    );
  }, [animate]);

  useImperativeHandle(ref, () => ({
    startAnimation: start,
    stopAnimation: stop
  }));

  return (
    <motion.div ref={scope} onHoverStart={start} onHoverEnd={stop}>
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="currentColor"
        stroke={color || 'currentColor'}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
        className={className}
      >
        <path stroke="none" d="M0 0h24v24H0z" fill="none" />
        <motion.path
          d="M17 3.34a10 10 0 1 1 -14.995 8.984l-.005 -.324l.005 -.324a10 10 0 0 1 14.995 -8.336z"
          className={`filled-circle ${className}`}
          style={{ transformOrigin: 'center' }}
        />
        <motion.path
          d="M15.707 9.293a1 1 0 0 0 -1.32 -.083l-.094 .083l-3.293 3.292l-1.293 -1.292l-.094 -.083a1 1 0 0 0 -1.403 1.403l.083 .094l2 2l.094 .083a1 1 0 0 0 1.226 0l.094 -.083l4 -4l.083 -.094a1 1 0 0 0 -.083 -1.32z"
          className="check-icon text-background"
          fill="currentColor"
        />
      </svg>
    </motion.div>
  );
});
FilledCheckedIcon.displayName = 'FilledCheckedIcon';

export const TriangleAlertIcon = forwardRef(function TriangleAlertIcon(
  { size = 24, color = 'currentColor', strokeWidth = 2, className = '' },
  ref
) {
  const [scope, animate] = useAnimate();

  const start = useCallback(async () => {
    await animate(
      '.triangle',
      { y: [0, -1.5, 0] },
      { duration: 0.25, ease: 'easeOut' }
    );

    animate(
      '.exclamation-line',
      { scaleY: [1, 1.35, 1] },
      { duration: 0.3, ease: 'easeOut' }
    );

    animate(
      '.exclamation-dot',
      { scale: [1, 1.4, 1], opacity: [1, 0.6, 1] },
      { duration: 0.25, delay: 0.05, ease: 'easeOut' }
    );
  }, [animate]);

  const stop = useCallback(() => {
    animate('.triangle', { y: 0 }, { duration: 0.2, ease: 'easeOut' });
    animate(
      '.exclamation-line',
      { scaleY: 1 },
      { duration: 0.2, ease: 'easeOut' }
    );
    animate(
      '.exclamation-dot',
      { scale: 1, opacity: 1 },
      { duration: 0.2, ease: 'easeOut' }
    );
  }, [animate]);

  useImperativeHandle(ref, () => ({
    startAnimation: start,
    stopAnimation: stop
  }));

  return (
    <motion.svg
      ref={scope}
      onHoverStart={start}
      onHoverEnd={stop}
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke={color}
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`cursor-pointer ${className}`}
    >
      <motion.path
        className="triangle"
        d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"
      />

      <g>
        <motion.path
          className="exclamation-line"
          d="M12 9v4"
          style={{ transformOrigin: '12px 11px' }}
        />
        <motion.path
          className="exclamation-dot"
          d="M12 17h.01"
          style={{ transformOrigin: '12px 17px' }}
        />
      </g>
    </motion.svg>
  );
});
TriangleAlertIcon.displayName = 'TriangleAlertIcon';

export const HistoryCircleIcon = forwardRef(function HistoryCircleIcon(
  { size = 24, color = 'currentColor', strokeWidth = 2, className = '' },
  ref
) {
  const [scope, animate] = useAnimate();

  const start = useCallback(async () => {
    // rebobina el circulo ligeramente
    animate(
      '.history-circle',
      { rotate: -45, pathLength: [1, 0.75] },
      { duration: 0.35, ease: 'easeOut' }
    );

    // la manecilla retrocede
    animate(
      '.clock-hand',
      { rotate: -30 },
      { duration: 0.25, ease: 'easeOut' }
    );
  }, [animate]);

  const stop = useCallback(async () => {
    animate(
      '.history-circle, .clock-hand',
      { rotate: 0, pathLength: 1 },
      { duration: 0.25, ease: 'easeInOut' }
    );
  }, [animate]);

  useImperativeHandle(ref, () => ({
    startAnimation: start,
    stopAnimation: stop
  }));

  return (
    <motion.svg
      ref={scope}
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke={color}
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`cursor-pointer ${className}`}
      onHoverStart={start}
      onHoverEnd={stop}
    >
      <path stroke="none" d="M0 0h24v24H0z" fill="none" />

      {/* manecilla del reloj */}
      <motion.path
        d="M12 8l0 4l2 2"
        className="clock-hand"
        style={{ transformOrigin: '50% 50%' }}
      />

      {/* circulo de historial */}
      <motion.path
        d="M3.05 11a9 9 0 1 1 .5 4m-.5 5v-5h5"
        className="history-circle"
        style={{ transformOrigin: '50% 50%' }}
      />
    </motion.svg>
  );
});
HistoryCircleIcon.displayName = 'HistoryCircleIcon';

export const DotsVerticalIcon = forwardRef(function DotsVerticalIcon(
  { size = 24, color = 'currentColor', className = '' },
  ref
) {
  const [scope, animate] = useAnimate();

  const start = useCallback(async () => {
    animate(
      '.dot-top',
      { y: [-1.5, 0], scale: [1, 1.35, 1] },
      { duration: 0.3, ease: 'easeOut' }
    );
    animate(
      '.dot-middle',
      { scale: [1, 1.5, 1] },
      { duration: 0.3, ease: 'easeOut' }
    );
    animate(
      '.dot-bottom',
      { y: [1.5, 0], scale: [1, 1.35, 1] },
      { duration: 0.3, ease: 'easeOut' }
    );
  }, [animate]);

  const stop = useCallback(() => {
    animate(
      '.dot-top, .dot-middle, .dot-bottom',
      { y: 0, scale: 1 },
      { duration: 0.2, ease: 'easeInOut' }
    );
  }, [animate]);

  useImperativeHandle(ref, () => ({
    startAnimation: start,
    stopAnimation: stop
  }));

  return (
    <motion.svg
      ref={scope}
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill={color || 'currentColor'}
      className={`cursor-pointer ${className}`}
      onHoverStart={start}
      onHoverEnd={stop}
    >
      <motion.circle
        className="dot-top"
        cx="12"
        cy="5"
        r="1.6"
        style={{ transformOrigin: '12px 5px' }}
      />
      <motion.circle
        className="dot-middle"
        cx="12"
        cy="12"
        r="1.6"
        style={{ transformOrigin: '12px 12px' }}
      />
      <motion.circle
        className="dot-bottom"
        cx="12"
        cy="19"
        r="1.6"
        style={{ transformOrigin: '12px 19px' }}
      />
    </motion.svg>
  );
});
DotsVerticalIcon.displayName = 'DotsVerticalIcon';
