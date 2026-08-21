import React, { useState } from 'react';
import ChipTabs from './hover/ChipTabs';
import PlayersSidebar from './PlayersSidebar';
import BackupsSidebar from './BackupsSidebar';
import { UsersMotionIcon, BackupMotionIcon } from './hover/AnimatedIcons';
import { useI18n } from '../i18n.jsx';

export default function SidebarTabs({ players, playersData, backups, onRefreshBackups, onRefreshPlayers, isRunning = false }) {
  const [activeTab, setActiveTab] = useState('players');
  const { t } = useI18n();

  const tabs = [
    {
      id: 'players',
      label: t('playersTab'),
      badge: players.length,
      icon: <UsersMotionIcon className="h-4 w-4 text-emerald-400" />
    },
    {
      id: 'backups',
      label: t('backupsTab'),
      badge: backups.length,
      icon: <BackupMotionIcon className="h-4 w-4 text-cyan-400" />
    }
  ];

  return (
    <div className="flex flex-col gap-4">
      {/* Selector de Pestañas Animadas Hover.dev */}
      <ChipTabs tabs={tabs} selected={activeTab} setSelected={setActiveTab} />

      {/* Contenido de Pestaña */}
      <div className="transition duration-300">
        {activeTab === 'players' ? (
          <PlayersSidebar
            players={players}
            playersData={playersData}
            isRunning={isRunning}
            onRefreshPlayers={onRefreshPlayers}
          />
        ) : (
          <BackupsSidebar backups={backups} onRefresh={onRefreshBackups} isRunning={isRunning} />
        )}
      </div>
    </div>
  );
}
