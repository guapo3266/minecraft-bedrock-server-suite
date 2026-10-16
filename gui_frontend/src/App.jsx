import React, { useState, useEffect, useRef, useCallback } from 'react';
import { MotionConfig } from 'framer-motion';
import { X, Check, TriangleAlert } from 'lucide-react';
import GlassStage from './components/GlassStage';
import Appearance from './components/Appearance';
import Dock from './components/Dock';
import { SECTIONS } from './navigation';
import { useAppearance } from './hooks/useAppearance';
import Navbar from './components/Navbar';
import HardwareMeter from './components/HardwareMeter';
import ConnectivityCard from './components/ConnectivityCard';
import ControlsBar from './components/ControlsBar';
import TerminalConsole from './components/TerminalConsole';
import SidebarTabs from './components/SidebarTabs';
import { lazy, Suspense } from 'react';
import UpdateModal from './components/UpdateModal';
import PropsModal from './components/PropsModal';
import ScheduleModal from './components/ScheduleModal';
import SetupWizard from './components/SetupWizard';
import AboutModal from './components/AboutModal';
import { useI18n } from './i18n.jsx';

const AiDrawer = lazy(() => import('./components/AiDrawer'));

export default function App() {
  const { t, lang } = useI18n();
  const [appearanceOpen, setAppearanceOpen] = useState(false);
  const [glassStatus, setGlassStatus] = useState('loading');
  const [activeView, setActiveView] = useState('server');
  const [consoleExpanded, setConsoleExpanded] = useState(false);
  const [aboutOpen, setAboutOpen] = useState(false);
  const [toast, setToast] = useState(null);
  const headerRef = useRef(null), dockRef = useRef(null);
  const notify = useCallback((key, kind = 'success') => setToast({ key, kind, id: Date.now() }), []);
  const appearance = useAppearance(notify);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 6500);
    return () => clearTimeout(timer);
  }, [toast]);
  const tRef = useRef(t);
  tRef.current = t;
  const langRef = useRef(lang);
  langRef.current = lang;

  const [status, setStatus] = useState({
    running: false,
    players: [],
    player_count: 0,
    last_backup: "Ninguno",
    backup_in_progress: false,
    update_in_progress: false,
    uptime: 0,
    hardware: { ram_mb: 0, ram_pct: 0, cpu_pct: 0, total_ram_gb: 23.6 }
  });

  const [logs, setLogs] = useState([]);
  const [backups, setBackups] = useState([]);
  const [playersData, setPlayersData] = useState(null);
  const [isUpdateModalOpen, setIsUpdateModalOpen] = useState(false);
  const [isPropsModalOpen, setIsPropsModalOpen] = useState(false);
  const [propsFields, setPropsFields] = useState({});
  const [propsServerRunning, setPropsServerRunning] = useState(false);
  const [isScheduleModalOpen, setIsScheduleModalOpen] = useState(false);
  const [scheduleConfig, setScheduleConfig] = useState(null);
  const [updateInfo, setUpdateInfo] = useState(null);
  const [isUpdating, setIsUpdating] = useState(false);
  const [updateStarted, setUpdateStarted] = useState(false);
  const [latency, setLatency] = useState(null);
  const [connectionState, setConnectionState] = useState('connecting');
  const wsRef = useRef(null);
  const updateStartedRef = useRef(false);
  const logSeqRef = useRef(0);
  const [setupInfo, setSetupInfo] = useState(null);
  const [setupFetchError, setSetupFetchError] = useState(false);
  const [setupAttempt, setSetupAttempt] = useState(0);
  const [connectivity, setConnectivity] = useState(null);

  const fetchConnectivity = async (refresh = false) => {
    try {
      const res = await fetch(`/api/connectivity${refresh ? '?refresh=1' : ''}`);
      if (!res.ok) throw new Error(res.statusText || `HTTP ${res.status}`);
      const data = await res.json();
      setConnectivity(data);
    } catch (e) {
      reportFetchError('/api/connectivity', e);
    }
  };

  // IP local/publica una sola vez al montar (el endpoint tiene su propia cache)
  useEffect(() => {
    fetchConnectivity();
  }, []);

  const makeLog = (text, type) => {
    logSeqRef.current += 1;
    return { id: `client-${logSeqRef.current}`, time: new Date().toLocaleTimeString(), text, type };
  };

  // Tope de logs en el cliente: el backend recorta a 500 (max_log_history);
  // sin este tope el array crecia sin cota en sesiones de dias y el filtrado
  // de la consola se degradaba progresivamente.
  const MAX_CLIENT_LOGS = 600;
  const pushLog = (entry) =>
    setLogs((prev) => {
      const next = [...prev, entry];
      return next.length > MAX_CLIENT_LOGS ? next.slice(next.length - MAX_CLIENT_LOGS) : next;
    });

  // Aviso VISIBLE de fallos de lectura de la API: reutiliza el mismo canal
  // que los handlers de acción (entrada 'error' en la consola de la GUI) en
  // vez de perderlos en console.error con la UI mostrando datos vacíos.
  const reportFetchError = (endpoint, err) => {
    console.error(err);
    const detail = err?.message || err?.detail || String(err);
    pushLog(makeLog(tRef.current('fetchError', { endpoint, err: detail }), 'error'));
  };

  // Estado del setup inicial (first-run): el wizard se muestra en
  // instalaciones nuevas; las ya usadas (mundo existente) no lo ven.
  // Si el backend no responde, la pantalla de carga muestra el error y
  // permite reintentar (antes quedaba un "Cargando…" eterno sin aviso).
  useEffect(() => {
    let cancelled = false;
    setSetupFetchError(false);
    (async () => {
      try {
        const res = await fetch('/api/setup_status');
        if (!res.ok) throw new Error(res.statusText || `HTTP ${res.status}`);
        const data = await res.json();
        if (!cancelled) setSetupInfo(data);
      } catch (e) {
        console.error(e);
        if (!cancelled) setSetupFetchError(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [setupAttempt]);

  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws?lang=${langRef.current}`;
    let disposed = false;
    let reconnectTimer = null;

    const connect = () => {
      if (disposed) return;
      reconnectTimer = null;
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;
      const isCurrent = () => !disposed && wsRef.current === ws;
      let pingTimer = null;
      const pingSentAt = { t: 0 };

      const sendPing = () => {
        if (ws.readyState === WebSocket.OPEN) {
          pingSentAt.t = Date.now();
          ws.send(JSON.stringify({ type: 'ping' }));
        }
      };

      ws.onopen = () => {
        if (!isCurrent()) return;
        pushLog(makeLog(tRef.current('wsConnected'), 'system'));
        fetchBackups();
        sendPing();
        ws.send(JSON.stringify({ type: 'set_lang', lang: langRef.current }));
        pingTimer = setInterval(sendPing, 3000);
      };

      ws.onmessage = (event) => {
        if (!isCurrent()) return;
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'init') {
            if (msg.logs) setLogs(msg.logs);
            if (msg.status) {
              setStatus(msg.status);
              setConnectionState('connected');
            }
          } else if (msg.type === 'log') {
            pushLog(msg.data);
          } else if (msg.type === 'status' && msg.data) {
            setStatus(msg.data);
            setConnectionState('connected');
          } else if (msg.type === 'pong') {
            setLatency(Date.now() - pingSentAt.t);
          }
        } catch (e) {
          console.error(e);
        }
      };

      ws.onerror = () => {
        if (!isCurrent()) return;
        setLatency(null);
        setConnectionState('reconnecting');
      };

      ws.onclose = () => {
        if (pingTimer) clearInterval(pingTimer);
        if (!isCurrent()) return; // sesión caducada o efecto desmontado
        wsRef.current = null;
        setLatency(null);
        setConnectionState('reconnecting');
        pushLog(makeLog(tRef.current('wsDisconnected'), 'error'));
        reconnectTimer = setTimeout(connect, 3000);
      };
    };

    connect();
    fetchBackups();

    return () => {
      // Sin esto, el close() disparaba onclose -> setTimeout(connect) y la
      // reconexión sobrevivía al cleanup (sockets huérfanos + logs
      // duplicados; visible en el doble montaje de React StrictMode).
      disposed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (wsRef.current) wsRef.current.close();
    };
  }, []);

  // Cierra el modal de actualización cuando el backend termina el proceso (flag update_in_progress)
  useEffect(() => {
    if (status.update_in_progress) updateStartedRef.current = true;
    if (updateStarted && isUpdating && updateStartedRef.current && status.update_in_progress === false) {
      setIsUpdating(false);
      setUpdateStarted(false);
      setIsUpdateModalOpen(false);
    }
  }, [status.update_in_progress, updateStarted, isUpdating]);

  // Reenvía el idioma al backend cuando el usuario cambia ES/EN en el navbar
  useEffect(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'set_lang', lang }));
    }
  }, [lang]);

  // Título dinámico de la pestaña del navegador (estado visible en background)
  useEffect(() => {
    document.title = connectionState !== 'connected'
      ? `${tRef.current(connectionState === 'connecting' ? 'guiConnecting' : 'guiReconnecting')} · Bedrock Suite`
      : status.running ? tRef.current('titleRunning', { count: status.player_count }) : tRef.current('titleStopped');
  }, [status.running, status.player_count, lang, connectionState]);

  const fetchBackups = async () => {
    try {
      const res = await fetch('/api/backups');
      if (!res.ok) throw new Error(res.statusText || `HTTP ${res.status}`);
      const data = await res.json();
      if (data.backups) setBackups(data.backups);
    } catch (e) {
      reportFetchError('/api/backups', e);
    }
  };

  const fetchPlayers = async () => {
    try {
      const res = await fetch('/api/players');
      if (!res.ok) throw new Error(res.statusText || `HTTP ${res.status}`);
      setPlayersData(await res.json());
    } catch (e) {
      reportFetchError('/api/players', e);
    }
  };

  // Vista de jugadores conocidos: al montar y cuando cambia quien esta online
  useEffect(() => {
    fetchPlayers();
  }, [status.player_count]);

  const handleOpenUpdate = async () => {
    setIsUpdateModalOpen(true);
    updateStartedRef.current = false;
    try {
      const res = await fetch('/api/check_update');
      if (!res.ok) throw new Error(res.statusText || `HTTP ${res.status}`);
      const data = await res.json();
      setUpdateInfo(data);
    } catch (e) {
      reportFetchError('/api/check_update', e);
    }
  };

  const handleOpenProps = async () => {
    setIsPropsModalOpen(true);
    try {
      const res = await fetch('/api/server_properties');
      if (!res.ok) throw new Error(res.statusText || `HTTP ${res.status}`);
      const data = await res.json();
      setPropsFields(data.fields || {});
      setPropsServerRunning(!!data.server_running);
    } catch (e) {
      reportFetchError('/api/server_properties', e);
    }
  };

  const handleOpenSchedule = async () => {
    setIsScheduleModalOpen(true);
    try {
      const res = await fetch('/api/schedule');
      if (!res.ok) throw new Error(res.statusText || `HTTP ${res.status}`);
      setScheduleConfig(await res.json());
    } catch (e) {
      reportFetchError('/api/schedule', e);
    }
  };

  const handleConfirmUpdate = async () => {
    setIsUpdating(true);
    setUpdateStarted(true);
    try {
      const res = await fetch('/api/action/update_bds', { method: 'POST' });
      // Un rechazo HTTP (409 instancia externa, 400...) resuelve sin lanzar:
      // sin este chequeo el modal quedaba en "Actualizando..." para siempre
      // (el efecto de cierre exige haber visto update_in_progress === true,
      // que el backend nunca setea al rechazar) y el motivo no se mostraba.
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        pushLog(makeLog(tRef.current('actionError', { action: 'update_bds', err: data.detail || res.statusText }), 'error'));
        setIsUpdating(false);
        setUpdateStarted(false);
        setIsUpdateModalOpen(false);
      }
    } catch (e) {
      console.error(e);
      setIsUpdating(false);
      setUpdateStarted(false);
      setIsUpdateModalOpen(false);
    }
  };

  // La reversión reusa el flag update_in_progress: el cierre del modal al
  // terminar ya lo maneja el efecto existente.
  const handleRollback = async () => {
    setIsUpdating(true);
    setUpdateStarted(true);
    try {
      const res = await fetch('/api/action/rollback_bds', { method: 'POST' });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        pushLog(makeLog(tRef.current('actionError', { action: 'rollback_bds', err: data.detail || res.statusText }), 'error'));
        setIsUpdating(false);
        setUpdateStarted(false);
        setIsUpdateModalOpen(false);
      }
    } catch (e) {
      console.error(e);
      setIsUpdating(false);
      setUpdateStarted(false);
      setIsUpdateModalOpen(false);
    }
  };

  const handleAction = async (actionName) => {
    try {
      const res = await fetch(`/api/action/${actionName}`, { method: 'POST' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        // El backend rechaza con HTTPException {detail} (p. ej. 409 por
        // instancia externa): mostrarlo como error en vez de un
        // "ejecutada (undefined)" con aspecto de éxito.
        pushLog(makeLog(tRef.current('actionError', { action: actionName, err: data.detail || res.statusText }), 'error'));
      } else {
        pushLog(makeLog(tRef.current('actionExecuted', { action: actionName, status: data.status }), 'system'));
      }
      fetchBackups();
    } catch (e) {
      pushLog(makeLog(tRef.current('actionError', { action: actionName, err: e }), 'error'));
    }
  };

  const handleSendCommand = async (command) => {
    if (!status.running) {
      pushLog(makeLog(`> ${command}`, 'command'));
      pushLog(makeLog(tRef.current('serverOff'), 'error'));
      return;
    }

    try {
      const res = await fetch('/api/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command })
      });
      // Mismo criterio que los demas handlers: un rechazo HTTP (403/500) debe
      // verse en la consola, no quedar en silencio.
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        pushLog(makeLog(tRef.current('commandError', { err: data.detail || res.statusText }), 'error'));
      }
    } catch (e) {
      pushLog(makeLog(tRef.current('commandError', { err: e }), 'error'));
    }
  };

  const ready = setupInfo !== null && !setupInfo.required;
  const section = SECTIONS.find(view => view.id === activeView) || SECTIONS[0];

  return <MotionConfig reducedMotion={appearance.effectiveEffects === 'reduced' ? 'always' : 'user'}>
    <GlassStage settings={{ ...appearance.settings, effects: appearance.effectiveEffects }} imageUrl={appearance.url}
      headerRef={headerRef} dockRef={dockRef} onStatus={setGlassStatus} layoutKey={ready} />
    <div className="app-shell" data-glass={glassStatus}>
      <a href="#main" className="skip-link">{t('skipContent')}</a>
      <Navbar headerRef={headerRef} status={status} showServerActions={ready} latency={latency} connectionState={connectionState}
        onOpenUpdate={handleOpenUpdate} onOpenProps={handleOpenProps} onOpenSchedule={handleOpenSchedule}
        onOpenAppearance={() => setAppearanceOpen(true)} onOpenAbout={() => setAboutOpen(true)}
        appearanceTipEnabled={ready && !appearanceOpen && !aboutOpen && !isUpdateModalOpen && !isPropsModalOpen && !isScheduleModalOpen} />
      <main id="main" className={`main-content ${ready ? activeView === 'server' ? 'server-content' : '' : 'setup-content'}`} tabIndex={-1}>
        {setupInfo === null ? <div className="panel loading-panel">
          <div className="loading-state" role="status"><span className="loading-spinner" aria-hidden="true" />{t('loading')}</div>
          {setupFetchError && <div className="notice error" role="alert">
            <TriangleAlert size={18} /><span>{t('setupNetError')}</span>
            <button type="button" className="button" onClick={() => setSetupAttempt(value => value + 1)}>{t('retry')}</button>
          </div>}
        </div> : setupInfo.required ? <SetupWizard bdsInstalled={!!setupInfo.bds_installed} logs={logs}
          onDone={() => setSetupAttempt(value => value + 1)} /> : <>
          {activeView !== 'server' && <div className="section-heading">
            <div><span className="eyebrow">Minecraft Bedrock <span className="eyebrow-separator">/</span>{t('localManagement')}</span>
              <h1>{t(section.label)}</h1><p>{t(section.subtitle)}</p></div>
            {status.running && <span className="player-count">{t('connectedPlayers', { count: status.player_count })}</span>}
          </div>}
          {/* Mantener la consola montada conserva entrada, filtros e historial al navegar. */}
          <div id="server-panel" role="tabpanel" aria-labelledby="server-tab" hidden={activeView !== 'server'} className={`server-view ${consoleExpanded ? 'console-expanded' : ''}`}>
            <ControlsBar status={status} onAction={handleAction} />
            <div className="server-console-grid">
              <TerminalConsole logs={logs} onSendCommand={handleSendCommand} onClearLogs={() => setLogs([])} isRunning={status.running}
                expanded={consoleExpanded} onToggleExpand={() => setConsoleExpanded(value => !value)} />
              <aside className="server-insights" aria-label={t('serverDetails')}>
                <HardwareMeter hardware={status.hardware} running={status.running} version={status.installed_version} />
                <ConnectivityCard connectivity={connectivity} running={status.running} onRefresh={() => fetchConnectivity(true)} />
              </aside>
            </div>
          </div>
          <SidebarTabs activeTab={activeView} showTabs={false} players={status.players} playersData={playersData}
            backups={backups} onRefreshBackups={fetchBackups} onRefreshPlayers={fetchPlayers} isRunning={status.running} />
        </>}
      </main>
      <Dock dockRef={dockRef} hidden={!ready} active={activeView} onChange={view => { setActiveView(view); setConsoleExpanded(false); }} players={status.player_count} backups={backups.length} />
    </div>
    {ready && <Suspense fallback={null}><AiDrawer onSendCommand={handleSendCommand} isRunning={status.running} /></Suspense>}
    <Appearance open={appearanceOpen} onClose={() => setAppearanceOpen(false)} appearance={appearance} glassStatus={glassStatus} />
    {aboutOpen && <AboutModal onClose={() => setAboutOpen(false)} />}
    {toast && <div className={`toast ${toast.kind}`} role={toast.kind === 'error' ? 'alert' : 'status'}>
      {toast.kind === 'error' ? <TriangleAlert size={18} /> : <Check size={18} />}<span>{t(toast.key)}</span>
      <button type="button" aria-label={t('closeMessage')} onClick={() => setToast(null)}><X size={16} /></button>
    </div>}
    <UpdateModal isOpen={isUpdateModalOpen} onClose={() => setIsUpdateModalOpen(false)} updateInfo={updateInfo}
      onConfirmUpdate={handleConfirmUpdate} onRollback={handleRollback} isUpdating={isUpdating} />
    <PropsModal isOpen={isPropsModalOpen} onClose={() => setIsPropsModalOpen(false)} fields={propsFields} serverRunning={propsServerRunning} />
    <ScheduleModal isOpen={isScheduleModalOpen} onClose={() => setIsScheduleModalOpen(false)} config={scheduleConfig} />
  </MotionConfig>;
}
