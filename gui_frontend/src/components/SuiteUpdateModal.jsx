import { useState } from 'react';
import { Download, X, TriangleAlert, Check } from 'lucide-react';
import Modal from './Modal';
import { useI18n } from '../i18n.jsx';
import { version } from '../../../version.json';
import { PHASE_KEYS } from '../suiteUpdateLogic';

export default function SuiteUpdateModal({ update, running, playerCount }) {
  const { t } = useI18n();
  const [confirming, setConfirming] = useState(false);
  const { info, checking, error, progress, inFlight } = update;
  const phase = progress?.phase || 'idle';
  return <Modal onClose={() => update.setOpen(false)} label={t('suiteUpdateTitle')} className="suite-update-dialog">
    <div className="dialog-heading">
      <div><span className="eyebrow">Minecraft Bedrock Server Suite</span><h2>{t('suiteUpdateTitle')}</h2></div>
      <button type="button" className="button icon-button" onClick={() => update.setOpen(false)} aria-label={t('close')}><X size={18} /></button>
    </div>
    <div className="suite-update-body">
    <p className="suite-update-subtitle">{t('suiteUpdateSeparate')}</p>
    <dl className="suite-version-list"><div><dt>{t('suiteCurrentVersion')}</dt><dd>{version}</dd></div>
      <div><dt>{t('suiteLatestVersion')}</dt><dd>{info?.latest_version || '—'}</dd></div></dl>
    {info?.state === 'no_release' && <p className="notice">{t('suiteNoRelease')}</p>}
    {info?.state === 'unavailable' && <p className="notice warning">{t('suiteCheckUnavailable')}</p>}
    {info?.state === 'available' && !info.has_update && <p className="notice"><Check size={16} />{t('suiteUpToDate')}</p>}
    {info?.has_update && <p className="notice"><Download size={16} />{t('suiteNewVersion', { version: info.latest_version })}</p>}
    {info?.install_block && <p className="notice warning">{t(info.install_block === 'git_checkout' ? 'suiteGitCheckout' : 'suiteLauncherRequired')}</p>}
    <p className="suite-update-preserve">{t('suitePreserve')}</p>
    {phase !== 'idle' && <div className={`notice ${['error', 'rollback_failed', 'restart_failed'].includes(phase) ? 'warning' : ''}`} role="status">
      <span>{t(PHASE_KEYS[phase] || 'suitePhaseReconnecting')}</span>
    </div>}
    {(error || progress?.detail) && <p className="suite-update-detail" role="alert">{error || progress.detail}</p>}
    {info?.release_url && <a className="text-link" href={info.release_url} target="_blank" rel="noopener noreferrer">{t('suiteReleaseNotes')}</a>}
    </div>
    <div className="dialog-actions">
      <button type="button" className="button" onClick={() => update.check(true)} disabled={checking || inFlight}>{checking ? t('loading') : t('suiteCheckNow')}</button>
      {info?.url && info.install_block && <a className="button" href={info.url}>{t('suiteDownloadZip')}</a>}
      {info?.has_update && <button type="button" className="button primary" disabled={inFlight || !!info.install_block || checking} onClick={() => setConfirming(true)}>{t('suiteInstall')}</button>}
    </div>
    {confirming && <Modal onClose={() => setConfirming(false)} label={t('suiteConfirmTitle')} className="suite-update-confirm">
      <div className="dialog-heading"><h2>{t('suiteConfirmTitle')}</h2><TriangleAlert size={24} /></div>
      <p>{running ? t('suiteConfirmRunning', { count: playerCount || 0 }) : t('suiteConfirmStopped')}</p>
      <p>{t('suitePreserve')}</p>
      <div className="dialog-actions">
        <button type="button" className="button" onClick={() => setConfirming(false)}>{t('cancel')}</button>
        <button type="button" className="button primary" onClick={() => { setConfirming(false); update.install(); }}>{t('suiteConfirmInstall')}</button>
      </div>
    </Modal>}
  </Modal>;
}
