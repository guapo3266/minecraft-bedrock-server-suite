import React, { useState, useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import SpotlightCard from './reactbits/SpotlightCard';
import AnimatedList from './reactbits/AnimatedList';
import ConfirmButton from './hover/ConfirmButton';
import { FolderArchive, RefreshCw, XCircle, Download, Trash2, ShieldCheck } from 'lucide-react';
import { FilledCheckedIcon, TriangleAlertIcon, HistoryCircleIcon, DotsVerticalIcon } from './hover/AnimatedStatusIcons';
import { useI18n } from '../i18n.jsx';

export default function BackupsSidebar({ backups = [], onRefresh, isRunning = false }) {
  const { t } = useI18n();
  const successIconRef = useRef(null);
  const alertIconRef = useRef(null);
  const menuRef = useRef(null);
  const [restoreTarget, setRestoreTarget] = useState(null); // backup a restaurar (confirm)
  const [deleteTarget, setDeleteTarget] = useState(null); // backup a eliminar (confirm)
  const [alertOpen, setAlertOpen] = useState(false); // alerta "apaga el servidor"
  const [result, setResult] = useState(null); // { ok: bool, message: string } tras el intento
  const [verifyResult, setVerifyResult] = useState(null); // feedback transitorio de verificacion
  const [verifying, setVerifying] = useState(null); // filename en verificacion
  const verifyTimerRef = useRef(null);
  // Menu de acciones por backup: fixed (el scroll de AnimatedList recortaria
  // un dropdown absoluto). menuRect = posicion calculada del boton "mas".
  const [menuFor, setMenuFor] = useState(null);
  const [menuRect, setMenuRect] = useState(null);

  const closeMenu = () => {
    setMenuFor(null);
    setMenuRect(null);
  };

  const openMenu = (backup, e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const w = 176;
    const h = 184;
    setMenuRect({
      top: Math.min(rect.bottom + 4, window.innerHeight - h - 8),
      left: Math.max(8, Math.min(rect.right - w, window.innerWidth - w - 8))
    });
    setMenuFor(backup.filename);
  };

  // Cierra el menu con clic fuera (sin contar el boton que lo abre: evita la
  // carrera mousedown->click del toggle), Escape, scroll o resize
  useEffect(() => {
    if (!menuFor) return;
    const onDown = (ev) => {
      if (menuRef.current && menuRef.current.contains(ev.target)) return;
      if (ev.target && ev.target.closest && ev.target.closest('[data-menu-trigger]')) return;
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
  }, [menuFor]);

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
              <div key={b.filename} className="flex items-center gap-2 rounded-lg border border-transparent px-2 py-1.5 transition-colors hover:border-white/10 hover:bg-white/5">
                <div className="min-w-0 flex-1">
                  <p className="truncate font-bold text-white text-xs" title={b.filename}>
                    {b.filename}
                  </p>
                  <p className="truncate font-mono text-[10px] text-slate-400 whitespace-nowrap">
                    {b.date} · {b.size_mb} MB
                  </p>
                </div>
                <button
                  data-menu-trigger
                  onClick={(e) => (menuFor === b.filename ? closeMenu() : openMenu(b, e))}
                  title={t('actions')}
                  aria-label={t('actions')}
                  className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md border transition-all ${
                    menuFor === b.filename
                      ? 'border-amber-500/70 bg-amber-500/25 text-amber-300'
                      : 'border-white/10 bg-white/5 text-slate-400 hover:border-amber-500/50 hover:text-white'
                  }`}
                >
                  <DotsVerticalIcon size={16} className="text-current" />
                </button>
              </div>
            ))}
            showGradients
            enableArrowNavigation={false}
            displayScrollbar
          />
        )}
      </div>

      {/* Menu de acciones: PORTAL a document.body para que position:fixed sea
          relativo al viewport (un ancestro con transform lo desviaria). */}
      {createPortal(
        <AnimatePresence>
          {menuFor && menuRect && (
            <motion.div
              ref={menuRef}
              initial={{ opacity: 0, scale: 0.92, y: -4 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.92, y: -4 }}
              transition={{ type: 'spring', stiffness: 400, damping: 26 }}
              style={{ top: menuRect.top, left: menuRect.left }}
              className="fixed z-50 w-44 rounded-xl border border-white/10 bg-slate-950 p-1 shadow-2xl"
            >
            <a
              href={`/api/backups/${encodeURIComponent(menuFor)}/download`}
              onClick={closeMenu}
              className="flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs font-semibold text-cyan-300 transition-colors hover:bg-cyan-500/15"
            >
              <Download className="h-3.5 w-3.5" />
              {t('download')}
            </a>
            <button
              onClick={() => {
                const b = backups.find((x) => x.filename === menuFor);
                closeMenu();
                if (b) handleVerify(b);
              }}
              disabled={verifying === menuFor}
              className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs font-semibold text-sky-300 transition-colors hover:bg-sky-500/15 disabled:opacity-50"
            >
              {verifying === menuFor ? (
                <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />
              ) : (
                <ShieldCheck className="h-3.5 w-3.5" />
              )}
              {t('verify')}
            </button>
            <button
              onClick={() => {
                const b = backups.find((x) => x.filename === menuFor);
                closeMenu();
                if (b) handleRestoreClick(b);
              }}
              className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs font-semibold text-amber-300 transition-colors hover:bg-amber-500/15"
            >
              <HistoryCircleIcon size={15} className="text-amber-300" />
              {t('restore')}
            </button>
            <button
              onClick={() => {
                const b = backups.find((x) => x.filename === menuFor);
                closeMenu();
                if (b) handleDeleteClick(b);
              }}
              className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs font-semibold text-rose-300 transition-colors hover:bg-rose-500/15"
            >
              <Trash2 className="h-3.5 w-3.5" />
              {t('delete')}
            </button>
            </motion.div>
          )}
        </AnimatePresence>,
        document.body
      )}

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
