import React, { useState } from 'react';
import ChipTabs from './hover/ChipTabs';
import PlayersSidebar from './PlayersSidebar';
import BackupsSidebar from './BackupsSidebar';
import { UsersMotionIcon, BackupMotionIcon } from './hover/AnimatedIcons';

export default function SidebarTabs({ players, backups, onRefreshBackups }) {
  const [activeTab, setActiveTab] = useState('players');

  const tabs = [
    {
      id: 'players',
      label: 'Jugadores',
      badge: players.length,
      icon: <UsersMotionIcon className="h-4 w-4 text-emerald-400" />
    },
    {
      id: 'backups',
      label: 'Backups',
      badge: backups.length,
      icon: <BackupMotionIcon className="h-4 w-4 text-cyan-400" />
    }
  ];

  return (
    <div className="flex flex-col gap-4">
      {/* Selector de Pestañas Animadas Hover.dev */}
      <ChipTabs tabs={tabs} selected={activeTab} setSelected={setActiveTab} />

      {/* Contenido de Pestaña */}
      <div className="transition-all duration-300">
        {activeTab === 'players' ? (
          <PlayersSidebar players={players} />
        ) : (
          <BackupsSidebar backups={backups} onRefresh={onRefreshBackups} />
        )}
      </div>
    </div>
  );
}
