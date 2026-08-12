import React, { useState, useEffect, useRef } from 'react';
import SpotlightCard from './reactbits/SpotlightCard';
import AnimatedList from './reactbits/AnimatedList';
import { Gamepad2, UserX, Ban, UserCog, XCircle } from 'lucide-react';
import { FilledCheckedIcon } from './hover/AnimatedStatusIcons';
import { useI18n } from '../i18n.jsx';

const PLAYER_ACTIONS = [
  { id: 'kick', command: 'kick', icon: UserX, color: 'rose', titleKey: 'kick' },
  { id: 'ban', command: 'ban', icon: Ban, color: 'rose', titleKey: 'ban' },
  { id: 'op', command: 'op', icon: UserCog, color: 'cyan', titleKey: 'makeOperator' }
];

const actionStyles = {
  rose: 'border-rose-500/40 bg-rose-500/10 text-rose-300 hover:bg-rose-500/25 hover:border-rose-500/70',
  cyan: 'border-cyan-500/40 bg-cyan-500/10 text-cyan-300 hover:bg-cyan-500/25 hover:border-cyan-500/70'
};

export default function PlayersSidebar({ players = [], isRunning = false }) {
  const { t } = useI18n();
  const [result, setResult] = useState(null);
  const [busyKey, setBusyKey] = useState(null); // `${actionId}:${player}` en curso
  const successIconRef = useRef(null);
  const timerRef = useRef(null);

  useEffect(() => {
    if (result?.ok && successIconRef.current) {
      successIconRef.current.startAnimation();
    }
    if (result) {
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setResult(null), 6000);
    }
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [result]);

  const runAction = async (player, action) => {
    const key = `${action.id}:${player}`;
    setBusyKey(key);
    setResult(null);
    try {
      const res = await fetch('/api/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: `${action.command} "${player}"` })
      });
      const data = await res.json().catch(() => ({}));
      if (data.status === 'offline') {
        setResult({ ok: false, message: t('serverOff') });
      } else {
        setResult({ ok: true, message: t('playerActionSent', { action: action.command, player }) });
      }
    } catch (e) {
      setResult({ ok: false, message: t('playerActionFailed', { err: String(e) }) });
    } finally {
      setBusyKey(null);
    }
  };

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
                <span className="font-semibold truncate flex-1">{player}</span>
                {isRunning && (
                  <div className="flex shrink-0 items-center gap-1">
                    {PLAYER_ACTIONS.map((action) => {
                      const ActionIcon = action.icon;
                      const busy = busyKey === `${action.id}:${player}`;
                      return (
                        <button
                          key={action.id}
                          onClick={() => runAction(player, action)}
                          disabled={busy}
                          title={t(action.titleKey)}
                          aria-label={t(action.titleKey)}
                          className={`flex h-6 w-6 items-center justify-center rounded-md border transition-all disabled:opacity-50 ${actionStyles[action.color]}`}
                        >
                          {busy ? (
                            <span className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
                          ) : (
                            <ActionIcon className="h-3.5 w-3.5" />
                          )}
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            ))}
            showGradients
            enableArrowNavigation={false}
            displayScrollbar
          />
        )}
      </div>

      {result && (
        <div
          className={`mt-3 flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-semibold ${
            result.ok
              ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
              : 'border-rose-500/40 bg-rose-500/10 text-rose-300'
          }`}
        >
          {result.ok ? <FilledCheckedIcon ref={successIconRef} size={18} color="#6ee7b7" /> : <XCircle className="h-4 w-4 shrink-0" />}
          <span className="break-all">{result.message}</span>
        </div>
      )}
    </SpotlightCard>
  );
}
