import React from 'react';
import SpotlightCard from './reactbits/SpotlightCard';
import AnimatedList from './reactbits/AnimatedList';
import { Gamepad2 } from 'lucide-react';
import { useI18n } from '../i18n.jsx';

export default function PlayersSidebar({ players = [] }) {
  const { t } = useI18n();
  return (
    <SpotlightCard spotlightColor="rgba(6, 182, 212, 0.15)">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
        <Gamepad2 className="h-4 w-4 text-cyan-400" />
        <h3>{t('playersOnline')}</h3>
      </div>

      <div className="mt-4">
        {players.length === 0 ? (
          <p className="text-xs italic text-slate-400 text-center py-4">{t('noPlayers')}</p>
        ) : (
          <AnimatedList
            items={players.map((player) => (
              <div key={player} className="flex items-center gap-3 text-xs text-white">
                <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-emerald-500 font-extrabold text-black">
                  {player.charAt(0).toUpperCase()}
                </div>
                <span className="font-semibold truncate">{player}</span>
              </div>
            ))}
            showGradients
            enableArrowNavigation={false}
            displayScrollbar
          />
        )}
      </div>
    </SpotlightCard>
  );
}
