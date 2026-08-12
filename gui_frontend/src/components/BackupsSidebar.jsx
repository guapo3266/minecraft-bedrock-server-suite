import React, { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import SpotlightCard from './reactbits/SpotlightCard';
import AnimatedList from './reactbits/AnimatedList';
import ConfirmButton from './hover/ConfirmButton';
import { FolderArchive, RefreshCw, XCircle, Download, Trash2, ShieldCheck } from 'lucide-react';
import { FilledCheckedIcon, TriangleAlertIcon, HistoryCircleIcon } from './hover/AnimatedStatusIcons';
import { useI18n } from '../i18n.jsx';

export default function BackupsSidebar({ backups = [], onRefresh, isRunning = false }) {
  const { t } = useI18n();
  const successIconRef = useRef(null);
  const alertIconRef = useRef(null);
  const [restoreTarget, setRestoreTarget] = useState(null); // backup a restaurar (confirm)
  const [deleteTarget, setDeleteTarget] = useState(null); // backup a eliminar (confirm)
  const [alertOpen, setAlertOpen] = useState(false); // alerta "apaga el servidor"
  const [result, setResult] = useState(null); // { ok: bool, message: string } tras el intento
  const [verifyResult, setVerifyResult] = useState(null); // feedback transitorio de verificacion
  const [verifying, setVerifying] = useState(null); // filename en verificacion
  const verifyTimerRef = useRef(null);

  // Reproduce la animacion del check al confirmarse una restauracion exitosa
  useEffect(() => {
    if (result?.ok && successIconRef.current) {
      successIconRef.current.startAnimation();
    }
  }, [result]);

  // Igual para el feedback de verificacion de integridad
  useEffect(() => {
    if (verifyResult?.ok && successIconRef.current) {
      successIconRef.current.startAnimation();
    }
  }, [verifyResult]);

  // Pequena atencion al abrir la alerta de servidor encendido
  useEffect(() => {
    if (alertOpen && alertIconRef.current) {
      alertIconRef.current.startAnimation();
    }
  }, [alertOpen]);

  const handleRestoreClick = (backup) => {
    if (isRunning) {
      setAlertOpen(true);
      return;
    }
    setResult(null);
    setRestoreTarget(backup);
  };

  const handleConfirmRestore = async () => {
    const backup = restoreTarget;
    if (!backup) return;
    try {
      const res = await fetch('/api/restore', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: backup.filename })
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        setResult({ ok: true, message: t('restoreSuccess') });
        onRefresh();
      } else {
        const detail = data.detail || res.statusText;
        setResult({ ok: false, message: detail });
      }
    } catch (e) {
      setResult({ ok: false, message: String(e) });
    }
  };

  const handleDeleteClick = (backup) => {
    setResult(null);
    setDeleteTarget(backup);
  };

  const handleConfirmDelete = async () => {
    const backup = deleteTarget;
    if (!backup) return;
    try {
      const res = await fetch(`/api/backups/${encodeURIComponent(backup.filename)}/delete`, {
        method: 'POST'
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        setResult({ ok: true, message: t('deleteSuccess') });
        onRefresh();
      } else {
        const detail = data.detail || res.statusText;
        setResult({ ok: false, message: detail });
      }
    } catch (e) {
      setResult({ ok: false, message: String(e) });
    }
  };

  const handleVerify = async (backup) => {
    setVerifying(backup.filename);
    setVerifyResult(null);
    try {
      const res = await fetch(`/api/backups/${encodeURIComponent(backup.filename)}/verify`, { method: 'POST' });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.status === 'ok') {
        setVerifyResult({ ok: true, message: t('verifyOk') });
      } else {
        const detail = data.detail || data.entry || res.statusText;
        setVerifyResult({ ok: false, message: t('verifyCorrupt', { entry: detail }) });
      }
    } catch (e) {
      setVerifyResult({ ok: false, message: t('verifyError', { err: String(e) }) });
    } finally {
      setVerifying(null);
      if (verifyTimerRef.current) clearTimeout(verifyTimerRef.current);
      verifyTimerRef.current = setTimeout(() => setVerifyResult(null), 8000);
    }
  };

  return (
    <SpotlightCard spotlightColor="rgba(245, 158, 11, 0.15)">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
          <FolderArchive className="h-4 w-4 text-amber-400" />
          <h3>{t('backupsTitle')}</h3>
        </div>
        <button
          onClick={onRefresh}
          className="rounded-md border border-white/10 bg-white/5 p-1.5 text-xs text-slate-400 hover:border-amber-500/50 hover:text-white transition-all"
        >
          <RefreshCw className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="mt-4">
        {backups.length === 0 ? (
          <p className="text-xs italic text-slate-400 text-center py-4">{t('noBackups')}</p>
        ) : (
          <AnimatedList
            items={backups.map((b) => (
              <div key={b.filename} className="flex items-center justify-between gap-2">
                <div className="truncate mr-1">
                  <p className="font-bold text-white truncate">{b.filename}</p>
                  <p className="text-[11px] text-slate-400">{b.date}</p>
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                  <span className="rounded bg-amber-500/20 px-2 py-0.5 font-mono text-[11px] font-semibold text-amber-300">
                    {b.size_mb} MB
                  </span>
                  <a
                    href={`/api/backups/${encodeURIComponent(b.filename)}/download`}
                    title={t('download')}
                    aria-label={t('download')}
                    className="flex h-7 w-7 items-center justify-center rounded-md border border-cyan-500/40 bg-cyan-500/10 text-cyan-300 hover:bg-cyan-500/25 hover:border-cyan-500/70 transition-all"
                  >
                    <Download className="h-3.5 w-3.5" />
                  </a>
                  <motion.button
                    whileHover={{ scale: 1.1 }}
                    whileTap={{ scale: 0.9 }}
                    transition={{ type: 'spring', stiffness: 400, damping: 17 }}
                    onClick={() => handleVerify(b)}
                    disabled={verifying === b.filename}
                    title={t('verify')}
                    aria-label={t('verify')}
                    className="flex h-7 w-7 items-center justify-center rounded-md border border-sky-500/40 bg-sky-500/10 text-sky-300 hover:bg-sky-500/25 hover:border-sky-500/70 transition-all disabled:opacity-50"
                  >
                    {verifying === b.filename ? (
                      <span className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
                    ) : (
                      <ShieldCheck className="h-3.5 w-3.5" />
                    )}
                  </motion.button>
                  <motion.button
                    whileHover={{ scale: 1.1 }}
                    whileTap={{ scale: 0.9 }}
                    transition={{ type: 'spring', stiffness: 400, damping: 17 }}
                    onClick={() => handleDeleteClick(b)}
                    title={t('delete')}
                    aria-label={t('delete')}
                    className="flex h-7 w-7 items-center justify-center rounded-md border border-rose-500/40 bg-rose-500/10 text-rose-300 hover:bg-rose-500/25 hover:border-rose-500/70"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </motion.button>
                  <motion.button
                    whileHover={{ scale: 1.1 }}
                    whileTap={{ scale: 0.9 }}
                    transition={{ type: 'spring', stiffness: 400, damping: 17 }}
                    onClick={() => handleRestoreClick(b)}
                    title={t('restore')}
                    aria-label={t('restore')}
                    className="flex h-7 w-7 items-center justify-center rounded-md border border-amber-500/40 bg-amber-500/10 text-amber-300 hover:bg-amber-500/25 hover:border-amber-500/70"
                  >
                    <HistoryCircleIcon size={15} className="text-amber-300" />
                  </motion.button>
                </div>
              </div>
            ))}
            showGradients
            enableArrowNavigation={false}
            displayScrollbar
          />
        )}
      </div>

      {/* Feedback transitorio de verificacion (mismo patron que PlayersSidebar) */}
      {verifyResult && (
        <div
          className={`mt-3 flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-semibold ${
            verifyResult.ok
              ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
              : 'border-rose-500/40 bg-rose-500/10 text-rose-300'
          }`}
        >
          {verifyResult.ok ? (
            <FilledCheckedIcon ref={successIconRef} size={18} color="#6ee7b7" />
          ) : (
            <XCircle className="h-4 w-4 shrink-0" />
          )}
          <span className="break-all">{verifyResult.message}</span>
        </div>
      )}

      {/* Alerta: el servidor está encendido */}
      <AnimatePresence>
        {alertOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setAlertOpen(false)}
              className="absolute inset-0 bg-black/75 backdrop-blur-md"
            />
            <motion.div
              initial={{ scale: 0.8, opacity: 0, y: 20 }}
              animate={{ scale: 1, opacity: 1, y: 0 }}
              exit={{ scale: 0.8, opacity: 0, y: 20 }}
              transition={{ type: 'spring', stiffness: 300, damping: 20 }}
              className="relative z-10 w-full max-w-sm rounded-2xl border border-rose-500/40 bg-slate-950 p-6 shadow-2xl"
            >
              <div className="flex items-center gap-3">
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-rose-500/20 border border-rose-500/50">
                  <TriangleAlertIcon ref={alertIconRef} size={28} color="#fb7185" />
                </div>
                <div>
                  <h3 className="text-base font-bold text-white">{t('restoreServerOn')}</h3>
                  <p className="text-xs text-slate-400">{t('restoreServerOnMsg')}</p>
                </div>
              </div>
              <div className="mt-5 flex justify-end">
                <ConfirmButton variant="rose" onClick={() => setAlertOpen(false)} className="px-4 py-2">
                  {t('cancel')}
                </ConfirmButton>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* Confirmación de eliminación */}
      <AnimatePresence>
        {deleteTarget && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setDeleteTarget(null)}
              className="absolute inset-0 bg-black/75 backdrop-blur-md"
            />
            <motion.div
              initial={{ scale: 0.8, opacity: 0, y: 20 }}
              animate={{ scale: 1, opacity: 1, y: 0 }}
              exit={{ scale: 0.8, opacity: 0, y: 20 }}
              transition={{ type: 'spring', stiffness: 300, damping: 20 }}
              className="relative z-10 w-full max-w-sm rounded-2xl border border-rose-500/40 bg-slate-950 p-6 shadow-2xl"
            >
              <div className="flex items-center gap-3">
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-rose-500/20 border border-rose-500/50">
                  <Trash2 className="h-5 w-5 text-rose-400" />
                </div>
                <div>
                  <h3 className="text-base font-bold text-white">{t('deleteConfirm')}</h3>
                  <p className="font-mono text-[11px] text-rose-300 truncate max-w-[240px]">{deleteTarget.filename}</p>
                </div>
              </div>
              <p className="mt-4 text-xs text-slate-300 leading-relaxed">
                {t('deleteWarning')}
              </p>
              <p className="mt-2 text-[11px] text-slate-400">
                {deleteTarget.date} · {deleteTarget.size_mb} MB
              </p>

              {result && (
                <div
                  className={`mt-4 flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-semibold ${
                    result.ok
                      ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
                      : 'border-rose-500/40 bg-rose-500/10 text-rose-300'
                  }`}
                >
                  {result.ok ? <FilledCheckedIcon ref={successIconRef} size={18} color="#6ee7b7" /> : <XCircle className="h-4 w-4 shrink-0" />}
                  <span className="break-all">{result.message}</span>
                </div>
              )}

              <div className="mt-5 flex justify-end gap-3">
                <ConfirmButton variant="amber" onClick={() => setDeleteTarget(null)} className="px-4 py-2">
                  {t('cancel')}
                </ConfirmButton>
                <ConfirmButton variant="rose" onClick={handleConfirmDelete} className="px-4 py-2">
                  <Trash2 className="h-4 w-4" />
                  <span>{t('delete')}</span>
                </ConfirmButton>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* Confirmación de restauración */}
      <AnimatePresence>
        {restoreTarget && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setRestoreTarget(null)}
              className="absolute inset-0 bg-black/75 backdrop-blur-md"
            />
            <motion.div
              initial={{ scale: 0.8, opacity: 0, y: 20 }}
              animate={{ scale: 1, opacity: 1, y: 0 }}
              exit={{ scale: 0.8, opacity: 0, y: 20 }}
              transition={{ type: 'spring', stiffness: 300, damping: 20 }}
              className="relative z-10 w-full max-w-sm rounded-2xl border border-amber-500/40 bg-slate-950 p-6 shadow-2xl"
            >
              <div className="flex items-center gap-3">
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-amber-500/20 border border-amber-500/50">
                  <HistoryCircleIcon size={26} color="#fbbf24" />
                </div>
                <div>
                  <h3 className="text-base font-bold text-white">{t('restoreConfirm')}</h3>
                  <p className="font-mono text-[11px] text-amber-300 truncate max-w-[240px]">{restoreTarget.filename}</p>
                </div>
              </div>
              <p className="mt-4 text-xs text-slate-300 leading-relaxed">
                {t('restoreWarning')}
              </p>
              <p className="mt-2 text-[11px] text-slate-400">
                {restoreTarget.date} · {restoreTarget.size_mb} MB
              </p>

              {result && (
                <div
                  className={`mt-4 flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-semibold ${
                    result.ok
                      ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
                      : 'border-rose-500/40 bg-rose-500/10 text-rose-300'
                  }`}
                >
                  {result.ok ? <FilledCheckedIcon ref={successIconRef} size={18} color="#6ee7b7" /> : <XCircle className="h-4 w-4 shrink-0" />}
                  <span className="break-all">{result.message}</span>
                </div>
              )}

              <div className="mt-5 flex justify-end gap-3">
                <ConfirmButton variant="amber" onClick={() => setRestoreTarget(null)} className="px-4 py-2">
                  {t('cancel')}
                </ConfirmButton>
                <ConfirmButton variant="rose" onClick={handleConfirmRestore} className="px-4 py-2">
                  <HistoryCircleIcon size={16} />
                  <span>{t('restore')}</span>
                </ConfirmButton>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </SpotlightCard>
  );
}
