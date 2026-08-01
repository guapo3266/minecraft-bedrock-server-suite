import React from 'react';
import DecryptedText from './reactbits/DecryptedText';
import ShinyText from './reactbits/ShinyText';
import PingIndicator from './hover/PingIndicator';
import { ServerMotionIcon } from './hover/AnimatedIcons';
import { DownloadMotionIcon } from './hover/HardwareMotionIcons';

export default function Navbar({ status, onOpenUpdate, latency = null }) {
  const isOnline = status.running;
  const isBackup = status.backup_in_progress;

  let badgeStyle = "bg-rose-500/10 border-rose-500/40 text-rose-400";
  let dotStyle = "bg-rose-500 shadow-[0_0_10px_#f43f5e]";
  let statusText = "OFFLINE";

  if (isBackup) {
    badgeStyle = "bg-amber-500/15 border-amber-500/50 text-amber-300 shadow-[0_0_15px_rgba(245,158,11,0.3)]";
    dotStyle = "bg-amber-400 shadow-[0_0_10px_#f59e0b]";
    statusText = "BACKUP EN PROCESO";
  } else if (isOnline) {
    badgeStyle = "bg-emerald-500/15 border-emerald-500/50 text-emerald-300 shadow-[0_0_15px_rgba(16,185,129,0.3)]";
    dotStyle = "bg-emerald-400 shadow-[0_0_10px_#10b981]";
    statusText = "ONLINE";
  }

  return (
    <header className="relative z-10 flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-white/10 bg-slate-900/65 px-6 py-4 backdrop-blur-xl shadow-2xl">
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

      <div className="flex items-center gap-3">
        <button
          onClick={onOpenUpdate}
          className="flex items-center gap-2 rounded-xl border border-emerald-500/40 bg-emerald-500/10 px-3.5 py-2 text-xs font-bold text-emerald-300 hover:bg-emerald-500/20 transition-all shadow-lg"
        >
          <DownloadMotionIcon className="h-4 w-4 text-emerald-400" />
          <span>Actualización BDS</span>
        </button>

        <PingIndicator status={status} latency={latency} />

        <div className={`flex items-center gap-3 rounded-full border px-4 py-2 text-sm font-bold tracking-wider transition-all duration-300 ${badgeStyle}`}>
          <span className={`h-2.5 w-2.5 rounded-full animate-pulse ${dotStyle}`} />
          <ShinyText text={statusText} />
        </div>
      </div>
    </header>
  );
}
