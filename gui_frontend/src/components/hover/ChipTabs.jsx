import React from 'react';
import { motion } from 'framer-motion';

export default function ChipTabs({ tabs, selected, setSelected }) {
  return (
    <div className="flex items-center gap-1.5 rounded-xl border border-white/10 bg-slate-950/60 p-1.5 backdrop-blur-md">
      {tabs.map((tab) => {
        const isSelected = selected === tab.id;
        return (
          <button
            key={tab.id}
            onClick={() => setSelected(tab.id)}
            className={`relative flex items-center gap-2 rounded-lg px-4 py-2 text-xs font-bold transition-colors duration-200 ${
              isSelected ? 'text-white' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            {isSelected && (
              <motion.span
                layoutId="active-tab-chip"
                transition={{ type: 'spring', stiffness: 400, damping: 30 }}
                className="absolute inset-0 z-0 rounded-lg bg-gradient-to-r from-emerald-500/30 to-cyan-500/30 border border-emerald-500/50 shadow-[0_0_15px_rgba(16,185,129,0.3)]"
              />
            )}
            <span className="relative z-10 flex items-center gap-2">
              {tab.icon}
              <span>{tab.label}</span>
              {tab.badge !== undefined && (
                <span className={`ml-1 rounded-full px-2 py-0.5 text-[10px] font-extrabold ${
                  isSelected ? 'bg-emerald-400/20 text-emerald-300 border border-emerald-400/40' : 'bg-white/10 text-slate-400'
                }`}>
                  {tab.badge}
                </span>
              )}
            </span>
          </button>
        );
      })}
    </div>
  );
}
