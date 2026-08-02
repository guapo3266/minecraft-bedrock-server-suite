import React from 'react';
import DecryptedText from './reactbits/DecryptedText';
import ShinyText from './reactbits/ShinyText';
import PingIndicator from './hover/PingIndicator';
import { ServerMotionIcon } from './hover/AnimatedIcons';
import { DownloadMotionIcon } from './hover/HardwareMotionIcons';
import { useI18n } from '../i18n.jsx';

export default function Navbar({ status, onOpenUpdate, latency = null }) {
  const { t, lang, setLang } = useI18n();
  const isOnline = status.running;
  const isBackup = status.backup_in_progress;

  let badgeStyle = "bg-rose-500/10 border-rose-500/40 text-rose-400";
  let dotStyle = "bg-rose-500 shadow-[0_0_10px_#f43f5e]";
  let statusText = t('offline');

  if (isBackup) {
    badgeStyle = "bg-amber-500/15 border-amber-500/50 text-amber-300 shadow-[0_0_15px_rgba(245,158,11,0.3)]";
    dotStyle = "bg-amber-400 shadow-[0_0_10px_#f59e0b]";
    statusText = t('backupInProgress');
  } else if (isOnline) {
    badgeStyle = "bg-emerald-500/15 border-emerald-500/50 text-emerald-300 shadow-[0_0_15px_rgba(16,185,129,0.3)]";
    dotStyle = "bg-emerald-400 shadow-[0_0_10px_#10b981]";
    statusText = t('online');
  }

  return (
    <header className="relative z-10 flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-white/10 bg-slate-900/65 px-4 py-4 backdrop-blur-xl shadow-2xl sm:px-6">
      <div className="flex items-center gap-4">
        <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500/20 to-cyan-500/20 border border-emerald-500/40 shadow-[0_0_20px_rgba(16,185,129,0.3)]">
          <ServerMotionIcon className="h-6 w-6 text-emerald-400" />
        </div>
        <div>
          <h1 className="text-2xl font-extrabold tracking-wider text-transparent bg-clip-text bg-gradient-to-r from-white via-emerald-200 to-cyan-300">
            <DecryptedText text="BEDROCK WRAPPER" />
          </h1>
          <p className="text-xs text-slate-400">Minecraft Dedicated Server Control Center</p>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-end gap-2 sm:gap-3">
        <button
          onClick={onOpenUpdate}
          className="flex items-center gap-2 rounded-xl border border-emerald-500/40 bg-emerald-500/10 px-3.5 py-2 text-xs font-bold text-emerald-300 hover:bg-emerald-500/20 transition-all shadow-lg"
        >
          <DownloadMotionIcon className="h-4 w-4 text-emerald-400" />
          <span>{t('updateBds')}</span>
        </button>

        {/* Selector de idioma ES/EN */}
        <div className="flex items-center rounded-xl border border-white/10 bg-black/40 p-0.5 font-mono text-xs font-bold">
          <button
            onClick={() => setLang('es')}
            className={`flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg px-2.5 py-1.5 transition-all ${lang === 'es' ? 'bg-emerald-500/30 text-emerald-300 border border-emerald-500/40' : 'text-slate-400 hover:text-white'}`}
          >
            ES
          </button>
          <button
            onClick={() => setLang('en')}
            className={`flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg px-2.5 py-1.5 transition-all ${lang === 'en' ? 'bg-emerald-500/30 text-emerald-300 border border-emerald-500/40' : 'text-slate-400 hover:text-white'}`}
          >
            EN
          </button>
        </div>

        <PingIndicator status={status} latency={latency} />

        <div className={`flex items-center gap-3 rounded-full border px-4 py-2 text-sm font-bold tracking-wider transition-all duration-300 ${badgeStyle}`}>
          <span className={`h-2.5 w-2.5 rounded-full animate-pulse ${dotStyle}`} />
          <ShinyText text={statusText} />
        </div>
      </div>
    </header>
  );
}
