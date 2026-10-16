import React, { useState, useEffect, lazy, Suspense } from 'react';
import ChipTabs from './hover/ChipTabs';
import PlayersSidebar from './PlayersSidebar';
import BackupsSidebar from './BackupsSidebar';
import { Boxes, Users as UsersMotionIcon, FolderArchive as BackupMotionIcon } from 'lucide-react';
import { useI18n } from '../i18n.jsx';

const AddonsSidebar = lazy(() => import('./AddonsSidebar'));

export default function SidebarTabs({
  players = [],
  playersData = null,
  backups = [],
  onRefreshBackups = () => {},
  onRefreshPlayers = () => {},
  isRunning = false,
  activeTab: controlledTab,
  showTabs = true
}) {
  const [localTab, setActiveTab] = useState('players');
  const activeTab = controlledTab ?? localTab;
  const [visited, setVisited] = useState(['players']);
  // Se monta Addons solo al visitarlo y no se pierde su filtro al navegar.
  const visibleTabs = visited.includes(activeTab) ? visited : [...visited, activeTab];
  useEffect(() => {
    if (['players', 'backups', 'addons'].includes(activeTab)) {
      setVisited(previous => previous.includes(activeTab) ? previous : [...previous, activeTab]);
    }
  }, [activeTab]);
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
    },
    {
      // Inventario de addons (solo lectura): el componente consulta
      // /api/addons por su cuenta y ofrece su propio boton de actualizacion.
      id: 'addons',
      label: t('addonsTab'),
      icon: <Boxes className="h-4 w-4 text-amber-400" />
    }
  ];

  return (
    <div className="management-view" hidden={!showTabs && activeTab === 'server'}>
      {/* Selector de Pestañas Animadas Hover.dev */}
      {showTabs && <ChipTabs tabs={tabs} selected={activeTab} setSelected={setActiveTab} />}

      {/* Contenido de Pestaña */}
      <div id="players-panel" role={showTabs ? undefined : 'tabpanel'} aria-labelledby={showTabs ? undefined : 'players-tab'} hidden={activeTab !== 'players'}>
        {visibleTabs.includes('players') && (
          <PlayersSidebar
            players={players}
            playersData={playersData}
            isRunning={isRunning}
            onRefreshPlayers={onRefreshPlayers}
          />
        )}
      </div>
      <div id="backups-panel" role={showTabs ? undefined : 'tabpanel'} aria-labelledby={showTabs ? undefined : 'backups-tab'} hidden={activeTab !== 'backups'}>
        {visibleTabs.includes('backups') && (
          <BackupsSidebar backups={backups} onRefresh={onRefreshBackups} isRunning={isRunning} />
        )}
      </div>
      <div id="addons-panel" role={showTabs ? undefined : 'tabpanel'} aria-labelledby={showTabs ? undefined : 'addons-tab'} hidden={activeTab !== 'addons'}>
        {visibleTabs.includes('addons') && <Suspense fallback={<div className="panel"><p role="status">{t('addonsLoading')}</p></div>}><AddonsSidebar /></Suspense>}
      </div>
    </div>
  );
}
