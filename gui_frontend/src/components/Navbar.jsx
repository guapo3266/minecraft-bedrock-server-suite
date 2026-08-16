import React, { useState, useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import DecryptedText from './reactbits/DecryptedText';
import ShinyText from './reactbits/ShinyText';
import PingIndicator from './hover/PingIndicator';
import { ServerMotionIcon } from './hover/AnimatedIcons';
import { DownloadMotionIcon } from './hover/HardwareMotionIcons';
import { Settings, CalendarClock } from 'lucide-react';
import { DotsVerticalIcon } from './hover/AnimatedStatusIcons';
import { useI18n } from '../i18n.jsx';

function formatUptime(totalSeconds) {
  if (!totalSeconds || totalSeconds < 0) return '00:00';
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  if (h > 0) {
    return `${h}h ${String(m).padStart(2, '0')}m ${String(s).padStart(2, '0')}s`;
  }
  return `${String(m).padStart(2, '0')}m ${String(s).padStart(2, '0')}s`;
}

// Acciones secundarias del header, agrupadas en un solo menu para no
// competir por atencion con el badge de estado (color = solo estado).
export default function Navbar({ status, onOpenUpdate, onOpenProps, onOpenSchedule, latency = null }) {
  const { t, lang, setLang } = useI18n();
  const isOnline = status.running;
  const isBackup = status.backup_in_progress;
  const menuRef = useRef(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [menuRect, setMenuRect] = useState(null);

  const closeMenu = () => {
    setMenuOpen(false);
    setMenuRect(null);
  };

  const toggleMenu = (e) => {
    if (menuOpen) {
      closeMenu();
      return;
    }
    const rect = e.currentTarget.getBoundingClientRect();
    const w = 240;
    const h = 172;
    setMenuRect({
      top: Math.min(rect.bottom + 4, window.innerHeight - h - 8),
      left: Math.max(8, Math.min(rect.right - w, window.innerWidth - w - 8))
    });
    setMenuOpen(true);
  };

  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (ev) => {
      if (menuRef.current && menuRef.current.contains(ev.target)) return;
      if (ev.target && ev.target.closest && ev.target.closest('[data-nav-menu-trigger]')) return;
      closeMenu();
    };
    const onKey = (ev) => {
      if (ev.key === 'Escape') closeMenu();
    };
    document.addEventListener('mousedown', onDown);
    window.addEventListener('keydown', onKey);
    window.addEventListener('scroll', closeMenu, true);
    window.addEventListener('resize', closeMenu);
    return () => {
      document.removeEventListener('mousedown', onDown);
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('scroll', closeMenu, true);
      window.removeEventListener('resize', closeMenu);
    };
  }, [menuOpen]);

  const menuActions = [
    { id: 'props', label: t('settings'), icon: <Settings className="h-4 w-4 text-cyan-400" />, onClick: onOpenProps },
    { id: 'schedule', label: t('schedMenu'), icon: <CalendarClock className="h-4 w-4 text-purple-400" />, onClick: onOpenSchedule },
    { id: 'update', label: t('updateBds'), icon: <DownloadMotionIcon className="h-4 w-4 text-emerald-400" />, onClick: onOpenUpdate }
  ];

  const runMenuAction = (action) => {
    closeMenu();
    action.onClick();
  };

  let badgeStyle = "bg-rose-500/10 border-rose-500/40 text-rose-400";
  let dotStyle = "bg-rose-500 shadow-[0_0_10px_#f43f5e]";
  let statusText = t('offline');

  if (isBackup) {
    badgeStyle = "bg-amber-500/15 border-amber-500/50 text-amber-300 shadow-[0_0_15px_rgba(245,158,11,0.3)]";
    dotStyle = "bg-amber-400 shadow-[0_0_10px_#f59e0b]";
    statusText = t('backupInProgress');
  } else if (isOnline) {
    badgeStyle = "bg-emerald-500/15 border-emerald-500/50 text-emerald-300 shadow-[0_0_15px_rgba(16,185,129,0.3)]";
    dotStyle = "bg-emerald-400 shadow-[0_0_10px_#10b981]";
    statusText = t('online');
  }

  return (
    <header className="relative z-10 flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-white/10 bg-slate-900/65 px-4 py-4 backdrop-blur-xl shadow-2xl sm:px-6">
      <div className="flex items-center gap-4">
        <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500/20 to-cyan-500/20 border border-emerald-500/40 shadow-[0_0_20px_rgba(16,185,129,0.3)]">
          <ServerMotionIcon className="h-6 w-6 text-emerald-400" />
        </div>
        <div>
          <h1 className="text-2xl font-extrabold tracking-wider text-transparent bg-clip-text bg-gradient-to-r from-white via-emerald-200 to-cyan-300">
            <DecryptedText text="BEDROCK WRAPPER" />
          </h1>
          <p className="text-xs text-slate-400">{t('subtitle')}</p>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-end gap-2 sm:gap-3">
        {/* Menú de acciones secundarias (Configuración / Programación / Actualización) */}
        <button
          onClick={toggleMenu}
          data-nav-menu-trigger="true"
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          title={t('moreActions')}
          className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-slate-300 hover:bg-white/15 hover:text-white transition-all"
        >
          <DotsVerticalIcon size={18} />
        </button>

        {/* Selector de idioma ES/EN */}
        <div className="flex items-center rounded-xl border border-white/10 bg-black/40 p-0.5 font-mono text-xs font-bold">
          <button
            onClick={() => setLang('es')}
            className={`flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg px-2.5 py-1.5 transition-all ${lang === 'es' ? 'bg-emerald-500/30 text-emerald-300 border border-emerald-500/40' : 'text-slate-400 hover:text-white'}`}
          >
            ES
          </button>
          <button
            onClick={() => setLang('en')}
            className={`flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg px-2.5 py-1.5 transition-all ${lang === 'en' ? 'bg-emerald-500/30 text-emerald-300 border border-emerald-500/40' : 'text-slate-400 hover:text-white'}`}
          >
            EN
          </button>
        </div>

        {/* Latencia en vivo solo con el servidor corriendo: apagado, el badge
            de estado basta (antes se veian juntos DISCONNECTED + OFFLINE) */}
        {isOnline && <PingIndicator status={status} latency={latency} />}

        <div className={`flex items-center gap-2.5 rounded-full border px-4 py-2 text-sm font-bold tracking-wider transition-all duration-300 ${badgeStyle}`}>
          <span className={`h-2.5 w-2.5 rounded-full animate-pulse ${dotStyle}`} />
          <ShinyText text={statusText} />
          {isOnline && typeof status.uptime === 'number' && status.uptime > 0 && (
            <span className="font-mono text-xs font-medium text-emerald-300/80 border-l border-emerald-500/30 pl-2.5">
              {formatUptime(status.uptime)}
            </span>
          )}
        </div>
      </div>

      {/* Desplegable de acciones secundarias (portal: mismo patron que el menu
          de comandos rapidos y el de backups, fuera del stacking del header) */}
      {createPortal(
        <AnimatePresence>
          {menuOpen && menuRect && (
            <motion.div
              ref={menuRef}
              initial={{ opacity: 0, scale: 0.95, y: -4 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: -4 }}
              transition={{ duration: 0.12 }}
              style={{
                position: 'fixed',
                top: menuRect.top,
                left: menuRect.left,
                zIndex: 60
              }}
              className="w-60 rounded-2xl border border-white/15 bg-slate-900/95 p-1.5 shadow-2xl backdrop-blur-xl space-y-0.5"
            >
              <div className="px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-400 border-b border-white/10 mb-1">
                {t('moreActions')}
              </div>
              {menuActions.map((action) => (
                <button
                  key={action.id}
                  onClick={() => runMenuAction(action)}
                  className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-xs font-semibold text-slate-200 transition-colors hover:bg-white/10"
                >
                  {action.icon}
                  <span>{action.label}</span>
                </button>
              ))}
            </motion.div>
          )}
        </AnimatePresence>,
        document.body
      )}
    </header>
  );
}
