import React, { useState, useEffect } from 'react';
import SpotlightCard from './reactbits/SpotlightCard';
import TiltCard from './hover/TiltCard';
import CountUp from './reactbits/CountUp';
import Sparkline from './Sparkline';
import { CpuMotionIcon, RamMotionIcon, DownloadMotionIcon } from './hover/HardwareMotionIcons';
import { Package } from 'lucide-react';
import { useI18n } from '../i18n.jsx';

const RANGES = [1, 6, 24];

export default function HardwareMeter({ hardware, running, version }) {
  const ramMb = hardware?.ram_mb || 0;
  const cpuPct = hardware?.cpu_pct || 0;
  const totalRamGb = hardware?.total_ram_gb || 23.6;
  const availGb = hardware?.system_available_gb || 0;
  // RAM disponible de la maquina: en GB si >= 1, en MB si es menos
  const availLabel = availGb >= 1 ? `${availGb}\u00A0GB` : `${Math.round(availGb * 1024)}\u00A0MB`;
  // Disco: el volumen del servidor y los backups
  const diskFreeGb = hardware?.disk_free_gb ?? 0;
  const diskTotalGb = hardware?.disk_total_gb ?? 0;
  const diskUsedPct = hardware?.disk_used_pct ?? 0;
  const diskLow = diskFreeGb < 5; // menos de 5 GB libres: aviso
  const { t } = useI18n();

  // Historial persistente (SQLite): sparklines por tarjeta
  const [range, setRange] = useState(24);
  const [points, setPoints] = useState([]);
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await fetch(`/api/history/metrics?hours=${range}`);
        const data = await res.json();
        if (!cancelled && Array.isArray(data.points)) setPoints(data.points);
      } catch (e) {
        /* historial opcional: sin el, la GUI funciona igual */
      }
    };
    load();
    const timer = setInterval(load, 60000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [range]);

  const series = (key) => points.map((p) => p[key] ?? 0);

  // El estado "encendido" viene del backend (status.running): la RAM medida
  // ahora incluye siempre la propia GUI, asi que ramMb ya no puede ser 0.
  const isServerRunning = Boolean(running);

  return (
    <section className="relative z-10 grid grid-cols-1 gap-4 sm:grid-cols-2">
      {/* Cabecera de la sección: etiqueta + selector de rango del historial */}
      <div className="col-span-full flex items-center justify-between gap-2">
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
          {t('historyLabel')}
        </span>
        <div className="flex items-center gap-1">
          {RANGES.map((h) => (
            <button
              key={h}
              onClick={() => setRange(h)}
              className={`flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg border px-3 font-mono text-xs font-bold transition ${
                range === h
                  ? 'border-cyan-500/40 bg-cyan-500/20 text-cyan-300'
                  : 'border-white/10 bg-black/30 text-slate-400 hover:text-slate-200'
              }`}
            >
              {h}h
            </button>
          ))}
        </div>
      </div>
      {/* RAM Meter */}
      <TiltCard>
        <SpotlightCard spotlightColor="rgba(16, 185, 129, 0.2)">
          <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-slate-400">
            <div className="flex items-center gap-2">
              <RamMotionIcon className="h-4 w-4 text-emerald-400" />
              <span>{t('ram')}</span>
            </div>
            <span className="font-mono text-emerald-400 text-xs font-bold">
              {isServerRunning ? `${ramMb}\u00A0MB` : t('off')}
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
              className="h-full rounded-full bg-gradient-to-r from-emerald-500 via-cyan-400 to-emerald-300 transition-[width] duration-500 shadow-[0_0_10px_#10b981]"
              style={{ width: `${isServerRunning ? Math.max(Math.min((ramMb / (totalRamGb * 1024)) * 100, 100), 3) : 0}%` }}
            />
          </div>

          <div className="mt-2">
            <Sparkline values={series('ram_pct')} color="#10b981" id="ram" />
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
              className="h-full rounded-full bg-gradient-to-r from-cyan-500 via-blue-400 to-purple-400 transition-[width] duration-500 shadow-[0_0_10px_#06b6d4]"
              style={{ width: `${isServerRunning ? Math.max(Math.min(cpuPct, 100), 3) : 0}%` }}
            />
          </div>

          <div className="mt-2">
            <Sparkline values={series('cpu_pct')} color="#06b6d4" id="cpu" />
          </div>
        </SpotlightCard>
      </TiltCard>

      {/* Disk Meter */}
      <TiltCard>
        <SpotlightCard spotlightColor="rgba(245, 158, 11, 0.2)">
          <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-slate-400">
            <div className="flex items-center gap-2">
              <DownloadMotionIcon className="h-4 w-4 text-amber-400" />
              <span>{t('disk')}</span>
            </div>
            <span className={`font-mono text-xs font-bold ${diskLow ? 'text-rose-400' : 'text-amber-400'}`}>
              {diskLow ? t('diskLow') : `${diskFreeGb}\u00A0GB`}
            </span>
          </div>

          <div className="mt-2 flex items-baseline gap-2">
            <span className={`text-2xl font-extrabold ${diskLow ? 'text-rose-400' : 'text-white'}`}>
              <CountUp to={diskFreeGb} decimals={1} />
            </span>
            <span className="text-xs font-medium text-slate-400">{t('diskFreeOf', { total: diskTotalGb })}</span>
          </div>

          {/* Barra de Nivel Minimalista */}
          <div className="mt-2.5 h-2 w-full overflow-hidden rounded-full bg-slate-950 border border-white/10">
            <div
              className={`h-full rounded-full bg-gradient-to-r from-amber-500 via-orange-400 to-yellow-300 transition-[width] duration-500 shadow-[0_0_10px_#f59e0b] ${
                diskLow ? 'from-rose-500 via-rose-400 to-rose-300 shadow-[0_0_10px_#f43f5e]' : ''
              }`}
              style={{ width: `${Math.max(Math.min(diskUsedPct, 100), 3)}%` }}
            />
          </div>

          <div className="mt-2">
            <Sparkline values={series('disk_used_pct')} color="#f59e0b" id="disk" />
          </div>
        </SpotlightCard>
      </TiltCard>

      {/* Version de BDS: capturada al arrancar el servidor (None apagado) */}
      <TiltCard>
        <SpotlightCard spotlightColor="rgba(139, 92, 246, 0.2)">
          <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-slate-400">
            <div className="flex items-center gap-2">
              <Package className="h-4 w-4 text-purple-400" />
              <span>{t('bdsVersion')}</span>
            </div>
          </div>

          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-extrabold text-white" title={version || undefined}>
              {version || '—'}
            </span>
          </div>
          <div className="mt-2 text-xs font-semibold text-purple-400">
            {t('bdsVersionHint')}
          </div>
        </SpotlightCard>
      </TiltCard>
    </section>
  );
}
