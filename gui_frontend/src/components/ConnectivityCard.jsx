import React, { useState } from 'react';
import SpotlightCard from './reactbits/SpotlightCard';
import { Globe, Copy, Check, RefreshCw } from 'lucide-react';
import { WifiIcon, WifiOffIcon } from './hover/AnimatedStatusIcons';
import { useI18n } from '../i18n.jsx';

function CopyButton({ value, label, copiedLabel }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (e) {
      // clipboard no disponible: sin accion
    }
  };
  return (
    <button
      onClick={copy}
      title={label}
      className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-xs font-bold text-slate-300 hover:bg-white/10 hover:text-white transition"
    >
      {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
      {copied ? copiedLabel : label}
    </button>
  );
}

export default function ConnectivityCard({ connectivity, running, onRefresh }) {
  const { t } = useI18n();
  const lan = connectivity?.lan_ip;
  const pub = connectivity?.public_ip;
  const port = connectivity?.port || '19132';
  const lanAddr = lan ? `${lan}:${port}` : '';
  const pubAddr = pub ? `${pub}:${port}` : '';

  return (
    <SpotlightCard spotlightColor="rgba(16, 185, 129, 0.15)">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
          {running ? (
            <WifiIcon size={18} color="#34d399" className="text-emerald-400" />
          ) : (
            <WifiOffIcon size={18} color="#94a3b8" className="text-slate-400" />
          )}
          <h3>{t('inviteTitle')}</h3>
        </div>
        {running ? (
          <span className="flex items-center gap-2 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-3 py-1 text-xs font-bold text-emerald-300">
            <span className="h-2 w-2 rounded-full animate-pulse bg-emerald-400" />
            {t('inviteListening', { port })}
          </span>
        ) : (
          <span className="rounded-full border border-white/10 bg-black/40 px-3 py-1 text-xs font-bold text-slate-400">
            {t('inviteStopped')}
          </span>
        )}
      </div>

      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="rounded-xl border border-white/10 bg-slate-950/60 p-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-semibold text-slate-400">{t('inviteLan')}</span>
            {lanAddr && <CopyButton value={lanAddr} label={t('copy')} copiedLabel={t('copied')} />}
          </div>
          <p className="mt-1 font-mono text-lg font-bold text-emerald-300">{lanAddr || '—'}</p>
        </div>
        <div className="rounded-xl border border-white/10 bg-slate-950/60 p-3">
          <div className="flex items-center justify-between gap-2">
            <span className="flex items-center gap-1.5 text-xs font-semibold text-slate-400">
              <Globe className="h-3.5 w-3.5 text-cyan-400" />
              {t('inviteInternet')}
            </span>
            <div className="flex items-center gap-1.5">
              {pubAddr && <CopyButton value={pubAddr} label={t('copy')} copiedLabel={t('copied')} />}
              <button
                onClick={onRefresh}
                title={t('refresh')}
                aria-label={t('refresh')}
                className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-xs font-bold text-slate-300 hover:bg-white/10 hover:text-white transition"
              >
                <RefreshCw className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
          <p className="mt-1 font-mono text-lg font-bold text-cyan-300">{pubAddr || t('ipPublicUnavailable')}</p>
        </div>
      </div>

      <p className="mt-3 text-xs leading-relaxed text-slate-400">
        {t('inviteOutside', { port })}
      </p>
    </SpotlightCard>
  );
}
