import React from 'react';
import SpotlightCard from './reactbits/SpotlightCard';
import TiltCard from './hover/TiltCard';
import { ServerMotionIcon, UsersMotionIcon, BackupMotionIcon, TerminalMotionIcon } from './hover/AnimatedIcons';

export default function MetricsGrid({ status }) {
  const formatUptime = (seconds) => {
    if (!status.running || !seconds) return "00:00:00";
    const hrs = String(Math.floor(seconds / 3600)).padStart(2, '0');
    const mins = String(Math.floor((seconds % 3600) / 60)).padStart(2, '0');
    const secs = String(seconds % 60).padStart(2, '0');
    return `${hrs}:${mins}:${secs}`;
  };

  return (
    <section className="relative z-10 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
      {/* Card 1: Status */}
      <TiltCard>
        <SpotlightCard spotlightColor="rgba(16, 185, 129, 0.2)">
          <div className="flex items-center gap-2.5 text-xs font-semibold uppercase tracking-wider text-slate-400">
            <ServerMotionIcon className="h-4 w-4 text-emerald-400" />
            <h3>Estado del Servidor</h3>
          </div>
          <div className="mt-3 text-2xl font-extrabold text-white">
            {status.backup_in_progress ? "Backup en Vivo" : status.running ? "En Línea (BDS)" : "Detenido"}
          </div>
          <div className="mt-2 text-xs font-semibold text-emerald-400">
            Uptime: {formatUptime(status.uptime)}
          </div>
        </SpotlightCard>
      </TiltCard>

      {/* Card 2: Players */}
      <TiltCard>
        <SpotlightCard spotlightColor="rgba(6, 182, 212, 0.2)">
          <div className="flex items-center gap-2.5 text-xs font-semibold uppercase tracking-wider text-slate-400">
            <UsersMotionIcon className="h-4 w-4 text-cyan-400" />
            <h3>Jugadores Online</h3>
          </div>
          <div className="mt-3 text-2xl font-extrabold text-white">
            {status.player_count || 0} <span className="text-base font-normal text-slate-400">conectados</span>
          </div>
          <div className="mt-2 text-xs font-semibold text-cyan-400 truncate">
            {status.players && status.players.length > 0 ? status.players.join(', ') : 'Sin jugadores en línea'}
          </div>
        </SpotlightCard>
      </TiltCard>

      {/* Card 3: Backups */}
      <TiltCard>
        <SpotlightCard spotlightColor="rgba(245, 158, 11, 0.2)">
          <div className="flex items-center gap-2.5 text-xs font-semibold uppercase tracking-wider text-slate-400">
            <BackupMotionIcon className="h-4 w-4 text-amber-400" />
            <h3>Último Backup</h3>
          </div>
          <div className="mt-3 text-2xl font-extrabold text-white">
            {status.last_backup || "Ninguno"}
          </div>
          <div className="mt-2 text-xs font-semibold text-amber-400">
            {status.backup_in_progress ? "Guardando datos..." : "Modo en caliente activo"}
          </div>
        </SpotlightCard>
      </TiltCard>

      {/* Card 4: Version */}
      <TiltCard>
        <SpotlightCard spotlightColor="rgba(139, 92, 246, 0.2)">
          <div className="flex items-center gap-2.5 text-xs font-semibold uppercase tracking-wider text-slate-400">
            <TerminalMotionIcon className="h-4 w-4 text-purple-400" />
            <h3>Motor de Juego</h3>
          </div>
          <div className="mt-3 text-2xl font-extrabold text-white">Bedrock 1.21+</div>
          <div className="mt-2 text-xs font-semibold text-purple-400">Hot Backup Protocol</div>
        </SpotlightCard>
      </TiltCard>
    </section>
  );
}
