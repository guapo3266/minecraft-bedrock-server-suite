import React, { useState, useRef, useEffect, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Send, Trash2, Search, ArrowDown, Sun, Moon, CloudSun, Users, Save, Shield, Compass } from 'lucide-react';
import { TerminalMotionIcon, ServerMotionIcon, UsersMotionIcon } from './hover/AnimatedIcons';
import { CpuMotionIcon } from './hover/HardwareMotionIcons';
import { TriangleAlertIcon, DotsVerticalIcon } from './hover/AnimatedStatusIcons';
import ClickSpark from './reactbits/ClickSpark';
import ShinyText from './reactbits/ShinyText';
import { useI18n } from '../i18n.jsx';

const TYPE_FILTERS = [
  { id: 'all', match: () => true },
  { id: 'error', match: (l) => l.type === 'error' },
  { id: 'players', match: (l) => l.type === 'join' || l.type === 'leave' },
  { id: 'system', match: (l) => l.type === 'system' || l.type === 'backup' },
  { id: 'command', match: (l) => l.type === 'command' }
];

const QUICK_COMMANDS = [
  { id: 'day', command: 'time set day', labelKey: 'cmdDay', icon: Sun, color: 'text-amber-300', hover: 'hover:bg-amber-500/15' },
  { id: 'night', command: 'time set night', labelKey: 'cmdNight', icon: Moon, color: 'text-sky-300', hover: 'hover:bg-sky-500/15' },
  { id: 'clear', command: 'weather clear', labelKey: 'cmdWeatherClear', icon: CloudSun, color: 'text-cyan-300', hover: 'hover:bg-cyan-500/15' },
  { id: 'list', command: 'list', labelKey: 'cmdList', icon: Users, color: 'text-emerald-300', hover: 'hover:bg-emerald-500/15' },
  { id: 'backup', command: 'backup', labelKey: 'cmdBackup', icon: Save, color: 'text-amber-300', hover: 'hover:bg-amber-500/15' },
  { id: 'keepinv', command: 'gamerule keepinventory true', labelKey: 'cmdKeepInventory', icon: Shield, color: 'text-purple-300', hover: 'hover:bg-purple-500/15' },
  { id: 'coords', command: 'gamerule showcoordinates true', labelKey: 'cmdShowCoords', icon: Compass, color: 'text-emerald-300', hover: 'hover:bg-emerald-500/15' }
];

// Estado de "radio button": solo el filtro activo lleva color; los demas se
// apagan (gris). Excepcion: con "Todos" activo, todos lucen su color (estado
// natural). Los inactivos mantienen hover sutil para no parecer bloqueados.
const FILTER_BUTTON_STYLES = {
  all: {
    icon: ServerMotionIcon,
    spark: '#06b6d4',
    variant: 'bg-cyan-500/20 text-cyan-300 border-cyan-500/50 hover:bg-cyan-500/30 shadow-[0_0_20px_rgba(6,182,212,0.25)]'
  },
  error: {
    icon: TriangleAlertIcon,
    spark: '#f43f5e',
    variant: 'bg-rose-500/20 text-rose-300 border-rose-500/50 hover:bg-rose-500/30 shadow-[0_0_20px_rgba(244,63,94,0.25)]'
  },
  players: {
    icon: UsersMotionIcon,
    spark: '#10b981',
    variant: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/50 hover:bg-emerald-500/30 shadow-[0_0_20px_rgba(16,185,129,0.25)]'
  },
  system: {
    icon: CpuMotionIcon,
    spark: '#f59e0b',
    variant: 'bg-amber-500/20 text-amber-300 border-amber-500/50 hover:bg-amber-500/30 shadow-[0_0_20px_rgba(245,158,11,0.25)]'
  },
  command: {
    icon: TerminalMotionIcon,
    spark: '#a855f7',
    variant: 'bg-purple-500/20 text-purple-300 border-purple-500/50 hover:bg-purple-500/30 shadow-[0_0_20px_rgba(168,85,247,0.25)]'
  }
};

// Filtro apagado: gris neutro, con hover sutil (parece clicable, no deshabilitado)
const FILTER_OFF_STYLE = 'border-slate-700 bg-slate-900/50 text-slate-400 hover:bg-slate-800/70 hover:text-slate-200';

const HISTORY_MAX = 50;

// Prefijo crudo de log de BDS ("[2026-08-16 02:43:56:435 INFO]"): la hora ya
// se muestra en log.time, asi que se elimina al render para no duplicar
// timestamps por linea. Solo limpia la presentacion: el filtro de busqueda
// y el backend siguen trabajando sobre el texto original.
const RAW_LOG_PREFIX_RE = /^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}:\d{3} (?:INFO|WARN|WARNING|ERROR|DEBUG|TRACE)\]\s?/;

function cleanLogText(text) {
  return (text || '').replace(RAW_LOG_PREFIX_RE, '');
}

export default function TerminalConsole({ logs, onSendCommand, onClearLogs, isRunning }) {
  const [input, setInput] = useState('');
  const [filter, setFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState('all');
  const [autoScroll, setAutoScroll] = useState(true);
  const [history, setHistory] = useState([]);
  const [historyIdx, setHistoryIdx] = useState(-1);
  const [menuOpen, setMenuOpen] = useState(false);
  const [menuRect, setMenuRect] = useState(null);
  const bodyRef = useRef(null);
  const inputRef = useRef(null);
  const menuRef = useRef(null);
  const { t } = useI18n();

  const closeQuickMenu = () => {
    setMenuOpen(false);
    setMenuRect(null);
  };

  const toggleQuickMenu = (e) => {
    if (menuOpen) {
      closeQuickMenu();
      return;
    }
    const rect = e.currentTarget.getBoundingClientRect();
    const w = 240;
    const h = 270;
    // Abrir hacia arriba si no hay espacio hacia abajo
    const fitsBelow = rect.bottom + h + 8 <= window.innerHeight;
    const top = fitsBelow ? rect.bottom + 4 : Math.max(8, rect.top - h - 4);
    const left = Math.max(8, Math.min(rect.right - w, window.innerWidth - w - 8));
    setMenuRect({ top, left });
    setMenuOpen(true);
  };

  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (ev) => {
      if (menuRef.current && menuRef.current.contains(ev.target)) return;
      if (ev.target && ev.target.closest && ev.target.closest('[data-quick-menu-trigger]')) return;
      closeQuickMenu();
    };
    const onKey = (ev) => {
      if (ev.key === 'Escape') closeQuickMenu();
    };
    document.addEventListener('mousedown', onDown);
    window.addEventListener('keydown', onKey);
    window.addEventListener('scroll', closeQuickMenu, true);
    window.addEventListener('resize', closeQuickMenu);
    return () => {
      document.removeEventListener('mousedown', onDown);
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('scroll', closeQuickMenu, true);
      window.removeEventListener('resize', closeQuickMenu);
    };
  }, [menuOpen]);

  const handleRunQuick = (cmd) => {
    closeQuickMenu();
    onSendCommand(cmd);
  };

  const filteredLogs = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const active = TYPE_FILTERS.find((f) => f.id === typeFilter) || TYPE_FILTERS[0];
    return logs.filter((l) => {
      if (!active.match(l)) return false;
      if (q && !(l.text || '').toLowerCase().includes(q)) return false;
      return true;
    });
  }, [logs, filter, typeFilter]);

  useEffect(() => {
    const el = bodyRef.current;
    if (el && autoScroll) {
      el.scrollTop = el.scrollHeight;
    }
  }, [logs, filteredLogs, autoScroll]);

  const handleScroll = () => {
    const el = bodyRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
    setAutoScroll(atBottom);
  };

  const jumpToLatest = () => {
    setAutoScroll(true);
    const el = bodyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    const cmd = input.trim();
    if (!cmd) return;
    onSendCommand(cmd);
    setHistory((prev) => [...prev.filter((c) => c !== cmd), cmd].slice(-HISTORY_MAX));
    setHistoryIdx(-1);
    setInput('');
  };

  const handleKeyDown = (e) => {
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (history.length === 0) return;
      const idx = historyIdx < 0 ? history.length - 1 : Math.max(0, historyIdx - 1);
      setHistoryIdx(idx);
      setInput(history[idx]);
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (historyIdx < 0) return;
      const idx = historyIdx + 1;
      if (idx >= history.length) {
        setHistoryIdx(-1);
        setInput('');
      } else {
        setHistoryIdx(idx);
        setInput(history[idx]);
      }
    }
  };

  const getLogClass = (type) => {
    switch (type) {
      case 'join': return 'text-emerald-400 font-semibold';
      case 'leave': return 'text-rose-400';
      case 'backup': return 'text-amber-400 font-semibold';
      case 'system': return 'text-cyan-400 font-semibold';
      case 'command': return 'text-purple-400 font-semibold';
      case 'error': return 'text-red-400 bg-red-950/40 px-2 py-0.5 rounded';
      default: return 'text-slate-300';
    }
  };

  return (
    <section className="relative z-10 flex h-[420px] flex-col overflow-hidden rounded-2xl border border-white/10 backdrop-blur-xl shadow-2xl lg:h-[clamp(480px,68vh,780px)]">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-white/10 bg-black/40 px-5 py-3">
        <div className="flex items-center gap-2">
          <div className="flex gap-1.5">
            <span className="h-3 w-3 rounded-full bg-red-500/80" />
            <span className="h-3 w-3 rounded-full bg-yellow-500/80" />
            <span className="h-3 w-3 rounded-full bg-green-500/80" />
          </div>
          <span className="ml-3 font-mono text-xs tracking-wider text-slate-400 flex items-center gap-2">
            <TerminalMotionIcon className="h-4 w-4 text-emerald-400" />
            {t('terminalTitle')}
          </span>
        </div>

        <button
          onClick={onClearLogs}
          className="flex min-h-[44px] items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-400 hover:border-emerald-500/50 hover:text-white transition"
        >
          <Trash2 className="h-3.5 w-3.5" />
          {t('clear')}
        </button>
      </div>

      {/* Barra de búsqueda y filtros por tipo */}
      <div className="flex flex-wrap items-center gap-2 border-b border-white/10 bg-black/30 px-4 py-2">
        <div className="flex min-h-[34px] flex-1 items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-2.5">
          <Search className="h-3.5 w-3.5 shrink-0 text-slate-400" />
          <input
            type="text"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder={t('searchPlaceholder')}
            className="flex-1 bg-transparent py-1.5 font-mono text-xs text-white outline-none placeholder:text-slate-400"
          />
        </div>
        <div className="flex items-center gap-1.5">
          {TYPE_FILTERS.map((f) => {
            const style = FILTER_BUTTON_STYLES[f.id] || FILTER_BUTTON_STYLES.all;
            const Icon = style.icon;
            const active = typeFilter === f.id;
            const allActive = typeFilter === 'all';
            return (
              <div key={f.id} className="shrink-0">
                <ClickSpark sparkColor={style.spark} sparkCount={10} onClick={() => setTypeFilter(f.id)}>
                  <motion.button
                    type="button"
                    whileHover={{ scale: 1.03 }}
                    whileTap={{ scale: 0.94 }}
                    transition={{ type: 'spring', stiffness: 400, damping: 17 }}
                    className={`flex items-center gap-1.5 rounded-xl border px-3 py-1.5 text-xs font-bold transition duration-200 ${
                      active
                        ? `${style.variant} ring-1 ring-inset ring-white/40 brightness-125`
                        : allActive
                          ? style.variant
                          : FILTER_OFF_STYLE
                    }`}
                  >
                    <Icon className="h-4 w-4" />
                    <ShinyText text={t(`filter${f.id.charAt(0).toUpperCase()}${f.id.slice(1)}`)} />
                  </motion.button>
                </ClickSpark>
              </div>
            );
          })}
        </div>
      </div>

      {/* Terminal Output */}
      <div
        ref={bodyRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto p-5 font-mono text-xs leading-relaxed space-y-1.5 bg-slate-950/50"
        role="log"
        aria-live="polite"
      >
        {logs.length === 0 ? (
          <div className="text-slate-400 italic">{t('waitingLogs')}</div>
        ) : filteredLogs.length === 0 ? (
          <div className="text-slate-400 italic">{t('searchNoMatch')}</div>
        ) : (
          filteredLogs.map((log) =>
            log.type === 'session_start' ? (
              <div key={log.id} role="separator" aria-label={t('prevSession')} className="my-2 flex items-center gap-3 select-none">
                <span className="h-px flex-1 bg-white/10" />
                <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400">{t('prevSession')}</span>
                <span className="h-px flex-1 bg-white/10" />
              </div>
            ) : (
              <div key={log.id} className={`break-all ${getLogClass(log.type)}`}>
                <span className="text-slate-400 mr-2">[{log.time}]</span>
                {cleanLogText(log.text)}
              </div>
            )
          )
        )}
      </div>

      {/* Botón "ir al final" cuando el autoscroll está pausado */}
      {!autoScroll && (
        <button
          onClick={jumpToLatest}
          className="absolute bottom-24 right-4 z-20 flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/15 px-3 py-1.5 text-xs font-bold text-emerald-300 shadow-lg backdrop-blur-xl hover:bg-emerald-500/25 transition"
        >
          <ArrowDown className="h-3.5 w-3.5" />
          {t('jumpToLatest')}
        </button>
      )}

      {/* Input Form con botón 3-puntos de comandos rápidos */}
      <form onSubmit={handleSubmit} className="flex items-center gap-2.5 border-t border-white/10 bg-black/60 px-4 py-3">
        <span className="font-mono font-bold text-emerald-400 text-lg">&gt;</span>
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={isRunning ? t('placeholderRunning') : t('placeholderStopped')}
          className="flex-1 bg-transparent py-2 font-mono text-xs text-white outline-none placeholder:text-slate-400"
        />
        <button
          type="button"
          onClick={toggleQuickMenu}
          data-quick-menu-trigger="true"
          aria-label={t('quickCommands')}
          title={t('quickCommands')}
          className="flex min-h-[40px] min-w-[40px] items-center justify-center rounded-xl border border-white/10 bg-white/5 text-slate-400 hover:bg-white/10 hover:text-white transition active:scale-95 shadow-sm"
        >
          <DotsVerticalIcon size={18} />
        </button>
        <button
          type="submit"
          className="flex min-h-[40px] items-center gap-1.5 rounded-xl bg-emerald-500 px-4 py-2 text-xs font-bold text-black hover:bg-emerald-400 transition-colors shadow-lg active:scale-95"
        >
          <Send className="h-3.5 w-3.5" />
          {t('send')}
        </button>
      </form>

      {/* Menú flotante de Comandos Rápidos (estilo 3-puntos con portal) */}
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
              className="w-64 rounded-2xl border border-white/15 bg-slate-900/95 p-1.5 shadow-2xl backdrop-blur-xl space-y-0.5"
            >
              <div className="px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-400 border-b border-white/10 mb-1">
                {t('quickCommands')}
              </div>
              {QUICK_COMMANDS.map((qc) => {
                const Icon = qc.icon;
                return (
                  <button
                    key={qc.id}
                    onClick={() => handleRunQuick(qc.command)}
                    className={`flex w-full items-center justify-between gap-2.5 rounded-xl px-3 py-2 text-xs font-semibold ${qc.color} transition-colors ${qc.hover}`}
                  >
                    <div className="flex items-center gap-2.5">
                      <Icon className="h-4 w-4 shrink-0" />
                      <span>{t(qc.labelKey)}</span>
                    </div>
                    <span className="font-mono text-[10px] text-slate-400">/{qc.command.split(' ')[0]}</span>
                  </button>
                );
              })}
            </motion.div>
          )}
        </AnimatePresence>,
        document.body
      )}
    </section>
  );
}
