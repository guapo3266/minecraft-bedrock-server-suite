import React from 'react';
import SpotlightCard from './reactbits/SpotlightCard';
import TiltCard from './hover/TiltCard';
import CountUp from './reactbits/CountUp';
import { CpuMotionIcon, RamMotionIcon } from './hover/HardwareMotionIcons';

export default function HardwareMeter({ hardware }) {
  const ramMb = hardware?.ram_mb || 0;
  const cpuPct = hardware?.cpu_pct || 0;
  const totalRamGb = hardware?.total_ram_gb || 23.6;

  const isServerRunning = ramMb > 0;

  return (
    <section className="relative z-10 grid grid-cols-1 gap-4 sm:grid-cols-2">
      {/* RAM Meter */}
      <TiltCard>
        <SpotlightCard spotlightColor="rgba(16, 185, 129, 0.2)">
          <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-slate-400">
            <div className="flex items-center gap-2">
              <RamMotionIcon className="h-4 w-4 text-emerald-400" />
              <span>Memoria RAM</span>
            </div>
            <span className="font-mono text-emerald-400 text-xs font-bold">
              {isServerRunning ? `${ramMb} MB` : 'Apagado'}
            </span>
          </div>

          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-extrabold text-white">
              <CountUp to={isServerRunning ? ramMb : 0} decimals={isServerRunning ? 1 : 0} />
            </span>
            <span className="text-xs font-medium text-slate-400">MB / {totalRamGb} GB</span>
          </div>

          {/* Barra de Nivel Minimalista */}
          <div className="mt-2.5 h-2 w-full overflow-hidden rounded-full bg-slate-950 border border-white/10">
            <div
              className="h-full rounded-full bg-gradient-to-r from-emerald-500 via-cyan-400 to-emerald-300 transition-all duration-500 shadow-[0_0_10px_#10b981]"
              style={{ width: `${isServerRunning ? Math.max(Math.min((ramMb / (totalRamGb * 1024)) * 100, 100), 3) : 0}%` }}
            />
          </div>
        </SpotlightCard>
      </TiltCard>

      {/* CPU Meter */}
      <TiltCard>
        <SpotlightCard spotlightColor="rgba(6, 182, 212, 0.2)">
          <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-slate-400">
            <div className="flex items-center gap-2">
              <CpuMotionIcon className="h-4 w-4 text-cyan-400" />
              <span>Procesador CPU</span>
            </div>
            <span className="font-mono text-cyan-400 text-xs font-bold">
              {isServerRunning ? `${cpuPct}%` : '0%'}
            </span>
          </div>

          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-extrabold text-white">
              <CountUp to={isServerRunning ? cpuPct : 0} decimals={1} />
            </span>
            <span className="text-xs font-medium text-slate-400">% de uso BDS</span>
          </div>

          {/* Barra de Nivel Minimalista */}
          <div className="mt-2.5 h-2 w-full overflow-hidden rounded-full bg-slate-950 border border-white/10">
            <div
              className="h-full rounded-full bg-gradient-to-r from-cyan-500 via-blue-400 to-purple-400 transition-all duration-500 shadow-[0_0_10px_#06b6d4]"
              style={{ width: `${isServerRunning ? Math.max(Math.min(cpuPct, 100), 3) : 0}%` }}
            />
          </div>
        </SpotlightCard>
      </TiltCard>
    </section>
  );
}
