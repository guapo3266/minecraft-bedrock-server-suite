import React from 'react';
import { motion } from 'framer-motion';

/**
 * HardwareMotionIcons — ItsHover.com Motion Icon Suite
 */

export function CpuMotionIcon({ className = "h-5 w-5 text-emerald-400" }) {
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
      whileHover={{ scale: 1.15, rotate: 90 }}
      transition={{ type: "spring", stiffness: 300, damping: 15 }}
    >
      <rect width="12" height="12" x="6" y="6" rx="2" />
      <motion.path
        d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"
        animate={{ opacity: [0.4, 1, 0.4] }}
        transition={{ repeat: Infinity, duration: 1.2 }}
      />
    </motion.svg>
  );
}

export function RamMotionIcon({ className = "h-5 w-5 text-cyan-400" }) {
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
      whileHover={{ scale: 1.15, y: -2 }}
    >
      <path d="M6 19v-3M10 19v-3M14 19v-3M18 19v-3" />
      <rect width="20" height="9" x="2" y="7" rx="2" />
      <motion.line
        x1="6"
        x2="6.01"
        y1="11"
        y2="11"
        animate={{ opacity: [0.2, 1, 0.2] }}
        transition={{ repeat: Infinity, duration: 0.8 }}
      />
      <motion.line
        x1="10"
        x2="10.01"
        y1="11"
        y2="11"
        animate={{ opacity: [1, 0.2, 1] }}
        transition={{ repeat: Infinity, duration: 0.8 }}
      />
    </motion.svg>
  );
}

export function DownloadMotionIcon({ className = "h-5 w-5 text-emerald-400" }) {
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
      whileHover={{ y: 3 }}
      transition={{ type: "spring", stiffness: 400, damping: 10 }}
    >
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <motion.polyline
        points="7 10 12 15 17 10"
        animate={{ y: [0, 3, 0] }}
        transition={{ repeat: Infinity, duration: 1.5 }}
      />
      <line x1="12" x2="12" y1="3" y2="15" />
    </motion.svg>
  );
}

export function ShieldMotionIcon({ className = "h-5 w-5 text-purple-400" }) {
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
      whileHover={{ scale: 1.1, rotate: [0, -10, 10, 0] }}
    >
      <path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z" />
      <motion.path
        d="m9 12 2 2 4-4"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 1 }}
      />
    </motion.svg>
  );
}
