import React, { useState, useEffect } from 'react';
import CountUp from './reactbits/CountUp';
import Sparkline from './Sparkline';
import { Package, Cpu as CpuMotionIcon, MemoryStick as RamMotionIcon, HardDrive as DownloadMotionIcon } from 'lucide-react';
import { useI18n } from '../i18n.jsx';

const RANGES = [1, 6, 24];

function MetricRow({ icon: Icon, label, value, detail, color, history, progress, id, warning = false }) {
  return <div className={`metric-row ${warning ? 'metric-warning' : ''}`} style={{ '--metric-color': color }}>
    <div className="metric-readout">
      <div className="metric-title"><span className="metric-name"><Icon size={15} aria-hidden="true" />{label}</span>
        <strong className="metric-value">{value}</strong></div>
      <p className="metric-detail">{detail}</p>
      <div className="metric-track" aria-hidden="true"><div className="metric-fill" style={{ width: `${progress}%` }} /></div>
    </div>
    <div className="metric-history" aria-hidden="true"><Sparkline values={history} color={color} height={28} id={id} /></div>
  </div>;
}

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
      } catch {
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
    <section className="panel hardware-panel legacy-ui" aria-label={t('resourcesLabel')}>
      <div className="hardware-heading">
        <h2>{t('resourcesLabel')}</h2>
        <div className="history-ranges" role="group" aria-label={t('historyLabel')}>
          {RANGES.map((h) => (
            <button
              key={h}
              onClick={() => setRange(h)}
              aria-pressed={range === h}
              className={`button range-button ${range === h ? 'selected' : ''}`}
            >
              {h}h
            </button>
          ))}
        </div>
      </div>
      <MetricRow icon={RamMotionIcon} label={t('ram')} id="ram" color="var(--green)"
        value={isServerRunning ? <><CountUp to={ramMb} decimals={1} />{'\u00a0'}MB</> : t('off')}
        detail={t('ramAvailable', { available: availLabel })} history={series('ram_pct')}
        progress={isServerRunning ? Math.max(Math.min((ramMb / (totalRamGb * 1024)) * 100, 100), 3) : 0} />
      <MetricRow icon={CpuMotionIcon} label={t('cpu')} id="cpu" color="var(--acc)"
        value={<><CountUp to={isServerRunning ? cpuPct : 0} decimals={1} />%</>}
        detail={t('cpuUsage')} history={series('cpu_pct')}
        progress={isServerRunning ? Math.max(Math.min(cpuPct, 100), 3) : 0} />
      <MetricRow icon={DownloadMotionIcon} label={t('disk')} id="disk" color={diskLow ? 'var(--red)' : 'var(--amber)'} warning={diskLow}
        value={<CountUp to={diskFreeGb} decimals={1} />}
        detail={<>{t('diskFreeOf', { total: diskTotalGb })}{diskLow && <> · {t('diskLow')}</>}</>}
        history={series('disk_used_pct')} progress={Math.max(Math.min(diskUsedPct, 100), 3)} />
      <div className="metric-version">
        <div className="metric-title"><span className="metric-name"><Package size={15} aria-hidden="true" />{t('bdsVersion')}</span>
          <strong title={version || undefined}>{version || '—'}</strong></div>
        <p className="metric-detail">{t('bdsVersionHint')}</p>
      </div>
    </section>
  );
}
