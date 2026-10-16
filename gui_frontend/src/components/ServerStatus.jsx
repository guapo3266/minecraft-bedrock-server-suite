import { useI18n } from '../i18n.jsx';

function formatUptime(totalSeconds) {
  if (!totalSeconds || totalSeconds < 0) return '00:00';
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  if (h > 0) return `${h}h ${String(m).padStart(2, '0')}m ${String(s).padStart(2, '0')}s`;
  return `${String(m).padStart(2, '0')}m ${String(s).padStart(2, '0')}s`;
}

// Sin un estado reciente recibido por WS, no presentar el último dato como
// estado en vivo. Desconectar la GUI NO equivale a detener el proceso BDS.
export default function ServerStatus({ status, connectionState = 'connecting', latency = null }) {
  const { t } = useI18n();
  const connected = connectionState === 'connected';
  const state = connected ? (status.backup_in_progress ? 'backup' : status.running ? 'online' : 'offline') : 'reconnecting';
  const key = connected ? (state === 'backup' ? 'serverStatusBackup' : state === 'online' ? 'serverStatusOnline' : 'serverStatusOffline')
    : connectionState === 'connecting' ? 'guiConnecting' : 'guiReconnecting';
  return <div className={`status-badge ${state}`} data-connection={connectionState} title={connected ? undefined : t('guiConnectionUnknown')}>
    <span className="status-dot" aria-hidden="true" />
    <span className="status-label" role="status">{t(key)}</span>
    {connected && status.running && status.uptime > 0 && <span className="server-uptime">{formatUptime(status.uptime)}</span>}
    {connected && status.running && latency !== null && <span className="server-latency" title={t('latency', { ms: latency })}>{latency} ms</span>}
  </div>;
}
