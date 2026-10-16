import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import SpotlightCard from './reactbits/SpotlightCard';
import {
  Sparkles,
  Send,
  Play,
  X,
  Copy,
  Check,
  AlertTriangle,
  RefreshCw,
  Clock,
  Terminal
} from 'lucide-react';
import { useI18n } from '../i18n.jsx';

export default function AiSidebar({ onSendCommand, isRunning = false }) {
  const { t } = useI18n();

  const [prompt, setPrompt] = useState('');
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);
  const [lmStatus, setLmStatus] = useState({ online: false, model: null, checked: false });
  const [currentProposal, setCurrentProposal] = useState(null);
  const [proposalsHistory, setProposalsHistory] = useState([]);
  const [copied, setCopied] = useState(false);
  const [executedFeedback, setExecutedFeedback] = useState(false);

  const inputRef = useRef(null);

  // Comprobar estado de LM Studio periódicamente (cada 10s o manual)
  const checkStatus = async () => {
    try {
      const res = await fetch('/api/ai/status');
      if (res.ok) {
        const data = await res.json();
        setLmStatus({ online: !!data.online, model: data.model || null, checked: true });
      } else {
        setLmStatus({ online: false, model: null, checked: true });
      }
    } catch {
      setLmStatus({ online: false, model: null, checked: true });
    }
  };

  useEffect(() => {
    checkStatus();
    const interval = setInterval(checkStatus, 10000);
    return () => clearInterval(interval);
  }, []);

  // Enviar prompt al backend para consulta a FunctionGemma
  const handlePropose = async (textToPropose) => {
    const text = (textToPropose !== undefined ? textToPropose : prompt).trim();
    if (!text || loading) return;

    setLoading(true);
    setErrorMsg(null);
    setExecutedFeedback(false);

    try {
      const res = await fetch('/api/ai/propose', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: text })
      });

      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        const proposalItem = {
          id: Date.now(),
          prompt: text,
          proposed_command: data.proposed_command,
          explanation: data.explanation,
          function: data.function,
          args: data.args,
          warning: data.warning,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        };
        setCurrentProposal(proposalItem);
        setProposalsHistory((prev) => [proposalItem, ...prev.slice(0, 9)]);
        setPrompt('');
      } else {
        setErrorMsg(data.message || data.detail || t('aiProposeError'));
      }
    } catch (err) {
      setErrorMsg(t('aiNetworkError', { err: err.message }));
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handlePropose();
    }
  };

  const handleExecute = (cmd) => {
    if (!cmd || !onSendCommand) return;
    onSendCommand(cmd);
    setExecutedFeedback(true);
    setTimeout(() => setExecutedFeedback(false), 3000);
  };

  const handleCopy = (text) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDiscard = () => {
    setCurrentProposal(null);
    setErrorMsg(null);
  };

  // Sugerencias rápidas: label Y texto insertado salen del diccionario i18n
  // (antes el label se traducía pero el prompt iba fijo en español, con lo que
  // en EN se veía "Set day" → "haz de día").
  const suggestions = [
    { label: t('sugDay'), text: t('sugDayPrompt') },
    { label: t('sugWeatherClear'), text: t('sugWeatherClearPrompt') },
    { label: t('sugDiamonds'), text: t('sugDiamondsPrompt') },
    { label: t('sugNightVision'), text: t('sugNightVisionPrompt') },
    { label: t('sugCreative'), text: t('sugCreativePrompt') }
  ];

  return (
    <div className="space-y-4">
      <SpotlightCard className="p-4 border border-white/10 bg-slate-900/80 rounded-xl shadow-lg backdrop-blur-md">
        {/* Cabecera & Estado de LM Studio */}
        <div className="flex items-center justify-between gap-2 border-b border-white/10 pb-3">
          <div className="flex items-center gap-2">
            <div className="p-2 rounded-lg bg-purple-500/20 text-purple-400 border border-purple-500/30">
              <Sparkles className="h-4 w-4 animate-pulse" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-slate-100">{t('aiTitle')}</h3>
              <p className="text-[11px] text-slate-400">{t('aiSubtitle')}</p>
            </div>
          </div>

          <button
            onClick={checkStatus}
            title={t('aiRefreshStatus')}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-white/5 transition"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </div>

        {/* Indicador de conexión con LM Studio */}
        <div className="mt-3 flex items-center justify-between text-xs px-2.5 py-1.5 rounded-lg bg-black/40 border border-white/5">
          <div className="flex items-center gap-2">
            <span
              className={`h-2 w-2 rounded-full ${
                lmStatus.online ? 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]' : 'bg-rose-500'
              }`}
            />
            <span className={lmStatus.online ? 'text-emerald-300 font-medium' : 'text-rose-300'}>
              {lmStatus.online ? t('aiLmStudioOnline') : t('aiLmStudioOffline')}
            </span>
          </div>
          {lmStatus.model && (
            <span className="text-[10px] text-slate-400 max-w-[130px] truncate" title={lmStatus.model}>
              {lmStatus.model}
            </span>
          )}
        </div>

        {!lmStatus.online && lmStatus.checked && (
          <p className="mt-2 text-[11px] text-amber-300/90 bg-amber-500/10 border border-amber-500/20 p-2 rounded-lg leading-relaxed">
            {t('aiOfflineHelp')}
          </p>
        )}

        {/* Sugerencias Rápidas */}
        <div className="mt-4">
          <span className="text-[11px] font-medium text-slate-400 mb-1.5 block">
            {t('aiQuickSuggestions')}
          </span>
          <div className="flex flex-wrap gap-1.5">
            {suggestions.map((sug, idx) => (
              <button
                key={idx}
                onClick={() => {
                  setPrompt(sug.text);
                  handlePropose(sug.text);
                }}
                disabled={loading}
                className="text-[11px] px-2.5 py-1 rounded-full bg-slate-800/80 hover:bg-purple-600/30 text-slate-300 hover:text-purple-200 border border-white/10 hover:border-purple-500/40 transition disabled:opacity-50"
              >
                {sug.label}
              </button>
            ))}
          </div>
        </div>

        {/* Formulario de Entrada */}
        <div className="mt-4 space-y-2">
          <div className="relative">
            <textarea
              ref={inputRef}
              rows={2}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={t('aiPlaceholder')}
              disabled={loading}
              className="w-full text-xs bg-black/50 border border-white/10 rounded-lg p-2.5 pr-10 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-purple-500/60 focus:ring-1 focus:ring-purple-500/30 resize-none transition"
            />
            <button
              onClick={() => handlePropose()}
              disabled={!prompt.trim() || loading}
              className="absolute right-2.5 bottom-3.5 p-1.5 rounded-md bg-purple-600 hover:bg-purple-500 disabled:bg-slate-800 text-white disabled:text-slate-500 transition shadow-md"
              title={t('aiSend')}
            >
              {loading ? (
                <RefreshCw className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Send className="h-3.5 w-3.5" />
              )}
            </button>
          </div>

          {errorMsg && (
            <div className="text-xs text-rose-300 bg-rose-500/15 border border-rose-500/30 p-2.5 rounded-lg flex items-start gap-2">
              <AlertTriangle className="h-4 w-4 shrink-0 text-rose-400 mt-0.5" />
              <div className="flex-1 text-[11px]">{errorMsg}</div>
              <button onClick={() => setErrorMsg(null)} className="text-rose-400 hover:text-rose-200">
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
        </div>

        {/* Tarjeta de Comando Propuesto para Aprobación Humana */}
        <AnimatePresence>
          {currentProposal && (
            <motion.div
              initial={{ opacity: 0, y: 10, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -10, scale: 0.98 }}
              className="mt-4 p-3 rounded-xl bg-slate-950/90 border border-purple-500/40 shadow-xl space-y-3"
            >
              <div className="flex items-center justify-between text-xs">
                <span className="font-semibold text-purple-300 flex items-center gap-1.5">
                  <Terminal className="h-3.5 w-3.5 text-purple-400" />
                  {t('aiProposedAction')}
                </span>
                <span className="text-[10px] text-slate-400 font-mono">
                  {currentProposal.function}
                </span>
              </div>

              {/* Explicación de la acción */}
              <p className="text-xs text-slate-300 leading-snug">
                {currentProposal.explanation}
              </p>

              {/* Comando propuesto con botón de copiar */}
              <div className="relative group">
                <div className="font-mono text-xs text-emerald-400 bg-black/80 p-2.5 rounded-lg border border-emerald-500/30 select-all break-all shadow-inner">
                  {currentProposal.proposed_command}
                </div>
                <button
                  onClick={() => handleCopy(currentProposal.proposed_command)}
                  title={t('aiCopyCommand')}
                  className="absolute right-2 top-2 p-1 rounded bg-slate-800/80 hover:bg-slate-700 text-slate-400 hover:text-slate-200 border border-white/5 opacity-0 group-hover:opacity-100 transition"
                >
                  {copied ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
                </button>
              </div>

              {/* Advertencia (si existe) */}
              {currentProposal.warning && (
                <div className="flex items-start gap-2 p-2 rounded-lg bg-amber-500/15 border border-amber-500/30 text-amber-200 text-[11px] leading-snug">
                  <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-400 mt-0.5" />
                  <span>{currentProposal.warning}</span>
                </div>
              )}

              {/* Feedback de ejecución */}
              {executedFeedback && (
                <div className="flex items-center gap-1.5 text-xs text-emerald-300 bg-emerald-500/15 border border-emerald-500/30 px-2.5 py-1.5 rounded-lg">
                  <Check className="h-3.5 w-3.5 text-emerald-400" />
                  <span>{t('aiExecuted')}</span>
                </div>
              )}

              {!isRunning && (
                <p className="text-[11px] text-rose-300/90 bg-rose-500/10 border border-rose-500/20 p-2 rounded-lg">
                  {t('aiServerOffline')}
                </p>
              )}

              {/* Botonera de Acción: Ejecutar o Descartar */}
              <div className="flex items-center gap-2 pt-1">
                <button
                  onClick={() => handleExecute(currentProposal.proposed_command)}
                  disabled={!isRunning}
                  className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-800 disabled:opacity-50 text-white font-medium text-xs shadow-md transition"
                >
                  <Play className="h-3.5 w-3.5 fill-current" />
                  {t('aiExecute')}
                </button>

                <button
                  onClick={handleDiscard}
                  className="px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs border border-white/10 transition"
                >
                  {t('aiDiscard')}
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Historial de Propuestas Recientes */}
        {proposalsHistory.length > 0 && (
          <div className="mt-5 border-t border-white/10 pt-3">
            <span className="text-[11px] font-semibold text-slate-400 flex items-center gap-1.5 mb-2">
              <Clock className="h-3 w-3" />
              {t('aiRecentHistory')}
            </span>

            <div className="space-y-2 max-h-48 overflow-y-auto pr-1">
              {proposalsHistory.map((item) => (
                <div
                  key={item.id}
                  className="p-2 rounded-lg bg-slate-950/60 border border-white/5 hover:border-purple-500/30 transition text-xs space-y-1"
                >
                  <div className="flex items-center justify-between text-[10px] text-slate-400">
                    <span className="truncate max-w-[170px] italic">"{item.prompt}"</span>
                    <span>{item.timestamp}</span>
                  </div>
                  <div className="flex items-center justify-between gap-2">
                    <code className="text-[11px] text-emerald-400 font-mono truncate">
                      {item.proposed_command}
                    </code>
                    <div className="flex items-center gap-1 shrink-0">
                      <button
                        onClick={() => handleCopy(item.proposed_command)}
                        title={t('aiCopy')}
                        className="p-1 rounded text-slate-400 hover:text-slate-200 hover:bg-white/5"
                      >
                        <Copy className="h-3 w-3" />
                      </button>
                      <button
                        onClick={() => handleExecute(item.proposed_command)}
                        disabled={!isRunning}
                        title={t('aiRun')}
                        className="p-1 rounded text-emerald-400 hover:text-emerald-300 hover:bg-emerald-500/10 disabled:opacity-40"
                      >
                        <Play className="h-3 w-3 fill-current" />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </SpotlightCard>
    </div>
  );
}
