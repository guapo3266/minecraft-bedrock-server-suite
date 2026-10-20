import React from 'react';
import { motion } from 'framer-motion';

/**
 * AnimatedIcons — ItsHover.com Component Library (.jsx)
 * Íconos motion-first con animaciones micro-interactivas.
 */

export function ServerMotionIcon({ className = "h-5 w-5 text-emerald-400" }) {
  return (
    <motion.svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      whileHover={{ scale: 1.15, rotate: [0, -5, 5, 0] }}
      transition={{ duration: 0.3 }}
    >
      <rect width="20" height="8" x="2" y="2" rx="2" ry="2" />
      <rect width="20" height="8" x="2" y="14" rx="2" ry="2" />
      <line x1="6" x2="6.01" y1="6" y2="6" />
      <line x1="6" x2="6.01" y1="18" y2="18" />
      <motion.line
        x1="10"
        x2="14"
        y1="6"
        y2="6"
        animate={{ opacity: [0.3, 1, 0.3] }}
        transition={{ repeat: Infinity, duration: 1.5 }}
      />
    </motion.svg>
  );
}

export function UsersMotionIcon({ className = "h-5 w-5 text-cyan-400" }) {
  return (
    <motion.svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      whileHover="hover"
    >
      <motion.path
        d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"
        variants={{ hover: { y: -2, transition: { duration: 0.2 } } }}
      />
      <motion.circle
        cx="9"
        cy="7"
        r="4"
        variants={{ hover: { scale: 1.1, y: -3, transition: { duration: 0.2 } } }}
      />
      <motion.path
        d="M22 21v-2a4 4 0 0 0-3-3.87"
        variants={{ hover: { x: 2, transition: { duration: 0.2 } } }}
      />
      <motion.path
        d="M16 3.13a4 4 0 0 1 0 7.75"
        variants={{ hover: { scale: 1.1, transition: { duration: 0.2 } } }}
      />
    </motion.svg>
  );
}

export function BackupMotionIcon({ className = "h-5 w-5 text-amber-400" }) {
  return (
    <motion.svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      whileHover={{ scale: 1.15 }}
    >
      <line x1="22" x2="2" y1="12" y2="12" />
      <path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />
      <motion.line
        x1="6"
        x2="6.01"
        y1="16"
        y2="16"
        animate={{ opacity: [0.2, 1, 0.2] }}
        transition={{ repeat: Infinity, duration: 1 }}
      />
      <motion.line
        x1="10"
        x2="10.01"
        y1="16"
        y2="16"
        animate={{ opacity: [1, 0.2, 1] }}
        transition={{ repeat: Infinity, duration: 1 }}
      />
    </motion.svg>
  );
}

export function TerminalMotionIcon({ className = "h-5 w-5 text-emerald-400" }) {
  return (
    <motion.svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      whileHover={{ scale: 1.1 }}
    >
      <polyline points="4 17 10 11 4 5" />
      <motion.line
        x1="12"
        x2="20"
        y1="19"
        y2="19"
        animate={{ opacity: [0, 1, 0] }}
        transition={{ repeat: Infinity, duration: 0.8 }}
      />
    </motion.svg>
  );
}
