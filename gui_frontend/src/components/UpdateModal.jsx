import React, { useState } from 'react';
import DecryptedText from './reactbits/DecryptedText';
import ShinyText from './reactbits/ShinyText';
import Magnet from './reactbits/Magnet';
import SpotlightCard from './reactbits/SpotlightCard';
import TiltCard from './hover/TiltCard';
import Modal from './Modal';
import { DownloadMotionIcon, ShieldMotionIcon } from './hover/HardwareMotionIcons';
import { X, CheckCircle, History, TriangleAlert } from 'lucide-react';
import { useI18n } from '../i18n.jsx';

export default function UpdateModal({ isOpen, onClose, updateInfo, onConfirmUpdate, onRollback, isUpdating }) {
  const { t } = useI18n();
  const [confirmRollback, setConfirmRollback] = useState(false);
  if (!isOpen) return null;
  const versionUnavailable = !updateInfo || updateInfo.has_update == null || updateInfo.unavailable;

  return (
    <div>
      <Modal onClose={onClose} label={t('updaterTitle')} className="max-w-lg border-emerald-500/40 overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-white/10 pb-4">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-500/20 border border-emerald-500/40">
                <DownloadMotionIcon className="h-5 w-5 text-emerald-400" />
              </div>
              <div>
                <h2 className="text-lg font-bold text-white">{t('updaterTitle')}</h2>
                <p className="text-xs text-slate-400">{t('updaterSubtitle')}</p>
              </div>
            </div>
            <button onClick={onClose} aria-label={t('close')} className="rounded-lg p-1 text-slate-400 hover:bg-white/10 hover:text-white">
              <X className="h-5 w-5" />
            </button>
          </div>

          {/* Body Content */}
          <div className="my-6 space-y-4">
            {versionUnavailable ? (
              <TiltCard>
                <SpotlightCard spotlightColor="rgba(245, 158, 11, 0.2)">
                  <div className="flex items-center gap-2 text-sm font-bold text-amber-400">
                    <ShieldMotionIcon className="h-4 w-4" />
                    <span>{t('versionUnavailable')}</span>
                  </div>
                  <p className="mt-2 text-xs text-slate-300">{t('versionUnavailableMsg')}</p>
                </SpotlightCard>
              </TiltCard>
            ) : updateInfo?.has_update ? (
              <TiltCard>
                <SpotlightCard spotlightColor="rgba(16, 185, 129, 0.2)">
                  <div className="flex items-center gap-2 text-sm font-bold text-emerald-400">
                    <CheckCircle className="h-4 w-4" />
                    <span>{t('newVersion')}</span>
                  </div>
                  <div className="mt-2 text-2xl font-extrabold text-white tracking-wider">
                    <DecryptedText text={`v${updateInfo.latest_version}`} />
                  </div>
                  <p className="mt-1 text-xs text-slate-300">
                    {t('currentVersion')} <span className="font-mono text-slate-400">{updateInfo.current_version}</span>
                  </p>
                </SpotlightCard>
              </TiltCard>
            ) : (
              <TiltCard>
                <SpotlightCard spotlightColor="rgba(6, 182, 212, 0.2)">
                  <div className="flex items-center gap-2 text-sm font-bold text-cyan-400">
                    <CheckCircle className="h-4 w-4" />
                    <span>{t('upToDate')}</span>
                  </div>
                  <div className="mt-2 text-xl font-extrabold text-white">
                    {t('activeVersion')} v{updateInfo?.current_version || '—'}
                  </div>
                </SpotlightCard>
              </TiltCard>
            )}

            <TiltCard>
              <SpotlightCard spotlightColor="rgba(245, 158, 11, 0.18)">
                <div className="space-y-2 text-xs text-slate-300">
                  <div className="flex items-center gap-2 font-bold text-amber-400">
                    <ShieldMotionIcon className="h-4 w-4 text-amber-400" />
                    <span>{t('protectionTitle')}</span>
                  </div>
                  <ul className="list-disc list-inside space-y-1 text-slate-400">
                    <li>{t('protection1')}</li>
                    <li>{t('protection2')}</li>
                  </ul>
                </div>
              </SpotlightCard>
            </TiltCard>

            {/* Versión anterior guardada: volver con un clic (swap simétrico) */}
            {updateInfo?.has_previous && (
              <TiltCard>
                <SpotlightCard spotlightColor="rgba(244, 63, 94, 0.15)">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2 text-sm font-bold text-rose-300">
                        <History className="h-4 w-4" />
                        <span>{t('rollbackTitle')}</span>
                      </div>
                      <p className="mt-1 text-xs text-slate-400">
                        {t('rollbackDesc')}{' '}
                        <span className="font-mono text-slate-300">
                          {updateInfo.previous_version ? `v${updateInfo.previous_version}` : t('rollbackUnknown')}
                        </span>
                      </p>
                    </div>
                    <button
                      onClick={() => setConfirmRollback(true)}
                      disabled={isUpdating}
                      className="flex min-h-[44px] shrink-0 items-center gap-2 rounded-xl border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-xs font-bold text-rose-300 transition hover:bg-rose-500/25 hover:border-rose-500/70 disabled:opacity-50"
                    >
                      <History className="h-4 w-4" />
                      <ShinyText text={t('rollbackNow')} />
                    </button>
                  </div>
                </SpotlightCard>
              </TiltCard>
            )}
          </div>

          {/* Footer Actions */}
          <div className="flex justify-end gap-3 border-t border-white/10 pt-4">
            <button
              onClick={onClose}
              className="flex min-h-[44px] items-center rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-xs font-bold text-slate-300 transition duration-200 hover:border-white/25 hover:bg-white/15 hover:text-white active:scale-95 active:bg-white/25"
            >
              {t('cancel')}
            </button>

            {updateInfo?.has_update && (
              <Magnet>
                <button
                  onClick={onConfirmUpdate}
                  disabled={isUpdating}
                  className="flex min-h-[44px] items-center gap-2 rounded-xl bg-gradient-to-r from-emerald-500 to-cyan-500 px-5 py-2 text-xs font-bold text-black shadow-[0_0_20px_rgba(16,185,129,0.4)] hover:brightness-110 disabled:opacity-50"
                >
                  <DownloadMotionIcon className="h-4 w-4 text-black" />
                  <ShinyText text={isUpdating ? t('updating') : t('updateNow')} />
                </button>
              </Magnet>
            )}
          </div>
      </Modal>

      {/* Confirmación de rollback: reemplaza el BDS actual (destructivo) */}
      {confirmRollback && (
        <Modal onClose={() => setConfirmRollback(false)} label={t('rollbackConfirmTitle')} className="max-w-sm border-rose-500/40">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-rose-500/20 border border-rose-500/50">
              <TriangleAlert className="h-5 w-5 text-rose-400" />
            </div>
            <div>
              <h3 className="text-base font-bold text-white">{t('rollbackConfirmTitle')}</h3>
              <p className="font-mono text-[11px] text-rose-300 truncate max-w-[240px]">
                {updateInfo?.previous_version ? `v${updateInfo.previous_version}` : t('rollbackUnknown')}
              </p>
            </div>
          </div>
          <p className="mt-4 text-xs text-slate-300 leading-relaxed">
            {t('rollbackConfirmMsg')}
          </p>
          <div className="mt-5 flex justify-end gap-3">
            <button
              onClick={() => setConfirmRollback(false)}
              className="flex min-h-[44px] items-center rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-xs font-bold text-slate-300 transition duration-200 hover:border-white/25 hover:bg-white/15 hover:text-white active:scale-95"
            >
              {t('cancel')}
            </button>
            <button
              onClick={() => {
                setConfirmRollback(false);
                onRollback();
              }}
              disabled={isUpdating}
              className="flex min-h-[44px] items-center gap-2 rounded-xl bg-gradient-to-r from-rose-500 to-orange-500 px-5 py-2 text-xs font-bold text-black shadow-[0_0_20px_rgba(244,63,94,0.4)] transition duration-200 hover:brightness-110 active:scale-95 disabled:opacity-50"
            >
              <History className="h-4 w-4" />
              {t('rollbackNow')}
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
