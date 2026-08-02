import React, { useState, useRef, useEffect } from 'react';
import { Send, Trash2 } from 'lucide-react';
import { TerminalMotionIcon } from './hover/AnimatedIcons';
import SpringChip from './hover/SpringChip';
import { useI18n } from '../i18n.jsx';

export default function TerminalConsole({ logs, onSendCommand, onClearLogs, isRunning }) {
  const [input, setInput] = useState('');
  const bodyRef = useRef(null);
  const { t } = useI18n();

  useEffect(() => {
    if (bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
    }
  }, [logs]);

  const handleSubmit = (e) => {
    e.preventDefault();
    const cmd = input.trim();
    if (!cmd) return;
    onSendCommand(cmd);
    setInput('');
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
    <section className="relative z-10 flex h-[540px] flex-col overflow-hidden rounded-2xl border border-white/10 bg-slate-950/80 backdrop-blur-xl shadow-2xl">
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
          className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-400 hover:border-emerald-500/50 hover:text-white transition-all"
        >
          <Trash2 className="h-3.5 w-3.5" />
          {t('clear')}
        </button>
      </div>

      {/* Terminal Output */}
      <div ref={bodyRef} className="flex-1 overflow-y-auto p-5 font-mono text-xs leading-relaxed space-y-1.5 bg-slate-950/55">
        {logs.length === 0 ? (
          <div className="text-slate-500 italic">{t('waitingLogs')}</div>
        ) : (
          logs.map((log, index) => (
            <div key={index} className={`break-all ${getLogClass(log.type)}`}>
              <span className="text-slate-600 mr-2">[{log.time}]</span>
              {log.text}
            </div>
          ))
        )}
      </div>

      {/* Input Form */}
      <form onSubmit={handleSubmit} className="flex items-center gap-3 border-t border-white/10 bg-black/60 px-4 py-3">
        <span className="font-mono font-bold text-emerald-400 text-lg">&gt;</span>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={isRunning ? t('placeholderRunning') : t('placeholderStopped')}
          className="flex-1 bg-transparent font-mono text-xs text-white outline-none placeholder:text-slate-500"
        />
        <button
          type="submit"
          className="flex items-center gap-1.5 rounded-lg bg-emerald-500 px-4 py-1.5 text-xs font-bold text-black hover:bg-emerald-400 transition-colors"
        >
          <Send className="h-3.5 w-3.5" />
          {t('send')}
        </button>
      </form>

      {/* Quick Command Chips */}
      <div className="flex gap-2 border-t border-white/10 bg-black/40 px-4 py-2">
        {['list', 'save query', 'say Servidor en mantenimiento.', 'time query day'].map((cmd) => (
          <SpringChip
            key={cmd}
            text={cmd}
            onClick={() => onSendCommand(cmd)}
          />
        ))}
      </div>
    </section>
  );
}
