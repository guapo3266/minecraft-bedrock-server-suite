import React, { useState, useEffect, useRef } from 'react';
import { AnimatePresence } from 'framer-motion';
import SpotlightCard from './reactbits/SpotlightCard';
import AnimatedList from './reactbits/AnimatedList';
import ConfirmButton from './hover/ConfirmButton';
import Modal from './Modal';
import { Gamepad2, UserX, Ban, UserCog, ListPlus, ListX, TriangleAlert, XCircle } from 'lucide-react';
import { FilledCheckedIcon } from './hover/AnimatedStatusIcons';
import { useI18n } from '../i18n.jsx';

const ONLINE_ACTIONS = [
  { id: 'kick', command: 'kick', icon: UserX, color: 'rose', titleKey: 'kick' }
];

const actionStyles = {
  rose: 'border-rose-500/40 bg-rose-500/10 text-rose-300 hover:bg-rose-500/25 hover:border-rose-500/70',
  cyan: 'border-cyan-500/40 bg-cyan-500/10 text-cyan-300 hover:bg-cyan-500/25 hover:border-cyan-500/70',
  amber: 'border-amber-500/40 bg-amber-500/10 text-amber-300 hover:bg-amber-500/25 hover:border-amber-500/70'
};

const permBadge = {
  operator: 'border-cyan-500/40 bg-cyan-500/10 text-cyan-300',
  member: 'border-slate-500/40 bg-slate-500/10 text-slate-300',
  visitor: 'border-slate-500/40 bg-slate-500/10 text-slate-300',
  default: 'border-slate-500/40 bg-slate-500/10 text-slate-400'
};

export default function PlayersSidebar({ players = [], playersData = null, isRunning = false, onRefreshPlayers = () => {} }) {
  const { t } = useI18n();
  const [result, setResult] = useState(null);
  const [busyKey, setBusyKey] = useState(null); // `${actionId}:${player}` en curso
  const [banTarget, setBanTarget] = useState(null); // jugador a banear (confirm)
  const [sessionTotals, setSessionTotals] = useState({}); // name -> segundos jugados (7d)
  const successIconRef = useRef(null);
  const timerRef = useRef(null);

  // Tiempo de juego de los ultimos 7 dias (historial SQLite; refresca con la
  // vista de jugadores, que ya se recarga tras cada accion)
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch('/api/history/sessions?days=7');
        const data = await res.json();
        if (!cancelled) {
          const map = {};
          (data.totals || []).forEach((x) => { map[x.player] = x.total_sec; });
          setSessionTotals(map);
        }
      } catch (e) {
        /* historial opcional */
      }
    })();
    return () => { cancelled = true; };
  }, [playersData]);

  const formatPlaytime = (sec) => {
    if (!sec || sec < 60) return null;
    if (sec < 3600) return `${Math.round(sec / 60)}m`;
    return `${(sec / 3600).toFixed(sec < 36000 ? 1 : 0)}h`;
  };

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

  const sendCommand = async (command) => {
    const res = await fetch('/api/command', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command })
    });
    return res.json().catch(() => ({}));
  };

  // BDS aplica op/deop/allowlist escribiendo sus archivos al procesar el
  // comando (asincrono al stdin): doble refresco para capturar el resultado.
  const refreshSoon = () => {
    onRefreshPlayers();
    setTimeout(onRefreshPlayers, 1500);
  };

  const runAction = async (player, action) => {
    const key = `${action.id}:${player}`;
    setBusyKey(key);
    setResult(null);
    try {
      const data = await sendCommand(`${action.command} "${player}"`);
      if (data.status === 'offline') {
        setResult({ ok: false, message: t('serverOff') });
      } else if (data.status === 'error') {
        // El backend no pudo escribir al stdin del wrapper: reportarlo como
        // fallo (antes se mostraba "enviado" con check de exito).
        setResult({ ok: false, message: t('playerActionFailed', { err: data.message || 'stdin' }) });
      } else {
        setResult({ ok: true, message: t('playerActionSent', { action: action.command, player }) });
        refreshSoon();
      }
    } catch (e) {
      setResult({ ok: false, message: t('playerActionFailed', { err: String(e) }) });
    } finally {
      setBusyKey(null);
    }
  };

  // "Ban" en BDS = fuera de la allowlist + kick (con allow-list=true no puede volver)
  const runBan = async (player) => {
    const key = `ban:${player}`;
    setBusyKey(key);
    setResult(null);
    try {
      const data = await sendCommand(`allowlist remove "${player}"`);
      if (data.status === 'offline') {
        setResult({ ok: false, message: t('serverOff') });
        return;
      }
      if (data.status === 'error') {
        setResult({ ok: false, message: t('playerActionFailed', { err: data.message || 'stdin' }) });
        return;
      }
      const kickData = await sendCommand(`kick "${player}"`);
      if (kickData.status === 'error') {
        setResult({ ok: false, message: t('playerActionFailed', { err: kickData.message || 'stdin' }) });
        return;
      }
      setResult({ ok: true, message: t('playerBanned', { player }) });
      refreshSoon();
    } catch (e) {
      setResult({ ok: false, message: t('playerActionFailed', { err: String(e) }) });
    } finally {
      setBusyKey(null);
    }
  };

  const iconButton = (player, action, extraClass = '') => {
    const ActionIcon = action.icon;
    const busy = busyKey === `${action.id}:${player}`;
    return (
      <button
        key={action.id + extraClass}
        onClick={() => runAction(player, action)}
        disabled={busy}
        title={t(action.titleKey)}
        aria-label={t(action.titleKey)}
        className={`flex h-6 w-6 items-center justify-center rounded-md border transition disabled:opacity-50 ${actionStyles[action.color]} ${extraClass}`}
      >
        {busy ? (
          <span className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
        ) : (
          <ActionIcon className="h-3.5 w-3.5" />
        )}
      </button>
    );
  };

  const known = playersData?.known || [];
  const allowListOff = playersData && playersData.allow_list_enabled === false;

  return (
    <div className="flex flex-col gap-4">
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
                      {ONLINE_ACTIONS.map((action) => iconButton(player, action))}
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
      </SpotlightCard>

      <SpotlightCard spotlightColor="rgba(16, 185, 129, 0.12)">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
          <UserCog className="h-4 w-4 text-emerald-400" />
          <h3>{t('playersKnown')}</h3>
        </div>

        {allowListOff && (
          <div className="mt-3 flex items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs font-semibold text-amber-300">
            <TriangleAlert className="h-4 w-4 shrink-0" />
            <span>{t('playersAllowListOff')}</span>
          </div>
        )}

        <div className="mt-3">
          {known.length === 0 ? (
            <p className="text-xs italic text-slate-400 text-center py-4">{t('playersNoKnown')}</p>
          ) : (
            <AnimatedList
              items={known.map((p) => {
                const isOp = p.permission === 'operator';
                const banBusy = busyKey === `ban:${p.name}`;
                return (
                  <div key={p.name} className="flex flex-col gap-1 text-xs text-white">
                    <div className="flex items-center gap-2">
                      <div
                        className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md font-extrabold text-black ${
                          p.online ? 'bg-emerald-500' : 'bg-slate-600'
                        }`}
                      >
                        {p.name.charAt(0).toUpperCase()}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          <span className="font-semibold truncate">{p.name}</span>
                          {p.online && (
                            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400 shadow-[0_0_6px_#10b981]" />
                          )}
                        </div>
                        {p.last_seen && (
                          <p className="text-[11px] text-slate-400 truncate">
                            {t('playersLastSeen')}: {p.last_seen}
                            {formatPlaytime(sessionTotals[p.name]) && (
                              <> &bull; {t('histPlayed')}: {formatPlaytime(sessionTotals[p.name])}</>
                            )}
                          </p>
                        )}
                      </div>
                      <span
                        className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${permBadge[p.permission] || permBadge.default}`}
                      >
                        {p.permission}
                      </span>
                    </div>
                    {isRunning && (
                      <div className="flex items-center justify-end gap-1 pb-1">
                        {p.online && iconButton(p.name, ONLINE_ACTIONS[0])}
                        {iconButton(
                          p.name,
                          isOp
                            ? { id: 'deop', command: 'deop', icon: UserCog, color: 'amber', titleKey: 'playersDeop' }
                            : { id: 'op', command: 'op', icon: UserCog, color: 'cyan', titleKey: 'makeOperator' }
                        )}
                        {iconButton(
                          p.name,
                          p.allowlisted
                            ? { id: 'al-remove', command: 'allowlist remove', icon: ListX, color: 'amber', titleKey: 'playersAllowRemove' }
                            : { id: 'al-add', command: 'allowlist add', icon: ListPlus, color: 'cyan', titleKey: 'playersAllowAdd' }
                        )}
                        <button
                          onClick={() => setBanTarget(p.name)}
                          disabled={banBusy || banTarget !== null}
                          title={t('ban')}
                          aria-label={t('ban')}
                          className={`flex h-6 w-6 items-center justify-center rounded-md border transition disabled:opacity-50 ${actionStyles.rose}`}
                        >
                          {banBusy ? (
                            <span className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
                          ) : (
                            <Ban className="h-3.5 w-3.5" />
                          )}
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
              showGradients
              enableArrowNavigation={false}
              displayScrollbar
            />
          )}
        </div>
      </SpotlightCard>

      {result && (
        <div
          aria-live="polite"
          className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-semibold ${
            result.ok
              ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
              : 'border-rose-500/40 bg-rose-500/10 text-rose-300'
          }`}
        >
          {result.ok ? <FilledCheckedIcon ref={successIconRef} size={18} color="#6ee7b7" /> : <XCircle className="h-4 w-4 shrink-0" />}
          <span className="break-all">{result.message}</span>
        </div>
      )}

      {/* Confirmación de ban: allowlist remove + kick (destructivo) */}
      <AnimatePresence>
        {banTarget && (
          <Modal onClose={() => setBanTarget(null)} label={t('banConfirmTitle', { player: banTarget })} className="max-w-sm border-rose-500/40">
            <div className="flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-rose-500/20 border border-rose-500/50">
                <Ban className="h-5 w-5 text-rose-400" />
              </div>
              <div>
                <h3 className="text-base font-bold text-white">{t('banConfirmTitle', { player: banTarget })}</h3>
                <p className="font-mono text-[11px] text-rose-300 truncate max-w-[240px]">{banTarget}</p>
              </div>
            </div>
            <p className="mt-4 text-xs text-slate-300 leading-relaxed">
              {t('banConfirmMsg')}
            </p>
            <div className="mt-5 flex justify-end gap-3">
              <ConfirmButton variant="amber" onClick={() => setBanTarget(null)} className="px-4 py-2">
                {t('cancel')}
              </ConfirmButton>
              <ConfirmButton
                variant="rose"
                onClick={() => {
                  const target = banTarget;
                  setBanTarget(null);
                  runBan(target);
                }}
                className="px-4 py-2"
              >
                <Ban className="h-4 w-4" />
                <span>{t('ban')}</span>
              </ConfirmButton>
            </div>
          </Modal>
        )}
      </AnimatePresence>
    </div>
  );
}
