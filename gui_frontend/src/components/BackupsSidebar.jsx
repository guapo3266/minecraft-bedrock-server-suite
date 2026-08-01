import React from 'react';
import SpotlightCard from './reactbits/SpotlightCard';
import { FolderArchive, RefreshCw } from 'lucide-react';

export default function BackupsSidebar({ backups = [], onRefresh }) {
  return (
    <SpotlightCard spotlightColor="rgba(245, 158, 11, 0.15)">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
          <FolderArchive className="h-4 w-4 text-amber-400" />
          <h3>Historial de Backups</h3>
        </div>
        <button
          onClick={onRefresh}
          className="rounded-md border border-white/10 bg-white/5 p-1.5 text-xs text-slate-400 hover:border-amber-500/50 hover:text-white transition-all"
        >
          <RefreshCw className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="mt-4 max-h-[220px] overflow-y-auto space-y-2">
        {backups.length === 0 ? (
          <p className="text-xs italic text-slate-500 text-center py-4">No se encontraron respaldos ZIP</p>
        ) : (
          backups.map((b) => (
            <div
              key={b.filename}
              className="flex items-center justify-between rounded-lg border border-white/10 bg-white/5 p-2.5 text-xs"
            >
              <div className="truncate mr-2">
                <p className="font-bold text-white truncate">{b.filename}</p>
                <p className="text-[11px] text-slate-400">{b.date}</p>
              </div>
              <span className="shrink-0 rounded bg-amber-500/20 px-2 py-0.5 font-mono text-[11px] font-semibold text-amber-300">
                {b.size_mb} MB
              </span>
            </div>
          ))
        )}
      </div>
    </SpotlightCard>
  );
}
