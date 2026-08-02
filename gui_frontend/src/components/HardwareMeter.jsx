import React from 'react';
import SpotlightCard from './reactbits/SpotlightCard';
import TiltCard from './hover/TiltCard';
import CountUp from './reactbits/CountUp';
import { CpuMotionIcon, RamMotionIcon } from './hover/HardwareMotionIcons';
import { useI18n } from '../i18n.jsx';

export default function HardwareMeter({ hardware, running }) {
  const ramMb = hardware?.ram_mb || 0;
  const cpuPct = hardware?.cpu_pct || 0;
  const totalRamGb = hardware?.total_ram_gb || 23.6;
  const availGb = hardware?.system_available_gb || 0;
  // RAM disponible de la maquina: en GB si >= 1, en MB si es menos
  const availLabel = availGb >= 1 ? `${availGb} GB` : `${Math.round(availGb * 1024)} MB`;
  const { t } = useI18n();

  // El estado "encendido" viene del backend (status.running): la RAM medida
  // ahora incluye siempre la propia GUI, asi que ramMb ya no puede ser 0.
  const isServerRunning = Boolean(running);

  return (
    <section className="relative z-10 grid grid-cols-1 gap-4 sm:grid-cols-2">
      {/* RAM Meter */}
      <TiltCard>
        <SpotlightCard spotlightColor="rgba(16, 185, 129, 0.2)">
          <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-slate-400">
            <div className="flex items-center gap-2">
              <RamMotionIcon className="h-4 w-4 text-emerald-400" />
              <span>{t('ram')}</span>
            </div>
            <span className="font-mono text-emerald-400 text-xs font-bold">
              {isServerRunning ? `${ramMb} MB` : t('off')}
            </span>
          </div>

          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-extrabold text-white">
              <CountUp to={isServerRunning ? ramMb : 0} decimals={isServerRunning ? 1 : 0} />
            </span>
            <span className="text-xs font-medium text-slate-400">{t('ramOf', { available: availLabel })}</span>
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
              <span>{t('cpu')}</span>
            </div>
            <span className="font-mono text-cyan-400 text-xs font-bold">
              {isServerRunning ? `${cpuPct}%` : '0%'}
            </span>
          </div>

          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-extrabold text-white">
              <CountUp to={isServerRunning ? cpuPct : 0} decimals={1} />
            </span>
            <span className="text-xs font-medium text-slate-400">{t('cpuUsage')}</span>
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
