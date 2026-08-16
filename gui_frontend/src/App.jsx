import React, { useState, useEffect, useRef } from 'react';
import PixelSnow from './components/reactbits/PixelSnow';
import Navbar from './components/Navbar';
import HardwareMeter from './components/HardwareMeter';
import ConnectivityCard from './components/ConnectivityCard';
import ControlsBar from './components/ControlsBar';
import TerminalConsole from './components/TerminalConsole';
import SidebarTabs from './components/SidebarTabs';
import UpdateModal from './components/UpdateModal';
import PropsModal from './components/PropsModal';
import ScheduleModal from './components/ScheduleModal';
import SetupWizard from './components/SetupWizard';
import { useI18n } from './i18n.jsx';

export default function App() {
  const { t, lang } = useI18n();
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
  const wsRef = useRef(null);
  const updateStartedRef = useRef(false);
  const logSeqRef = useRef(0);
  const [setupInfo, setSetupInfo] = useState(null);
  const [setupAttempt, setSetupAttempt] = useState(0);
  const [connectivity, setConnectivity] = useState(null);

  const fetchConnectivity = async (refresh = false) => {
    try {
      const res = await fetch(`/api/connectivity${refresh ? '?refresh=1' : ''}`);
      const data = await res.json();
      setConnectivity(data);
    } catch (e) {
      console.error(e);
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

  // Estado del setup inicial (first-run): el wizard se muestra en
  // instalaciones nuevas; las ya usadas (mundo existente) no lo ven.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch('/api/setup_status');
        const data = await res.json();
        if (!cancelled) setSetupInfo(data);
      } catch (e) {
        console.error(e);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [setupAttempt]);

  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws?lang=${langRef.current}`;

    const connect = () => {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;
      let pingTimer = null;
      const pingSentAt = { t: 0 };

      const sendPing = () => {
        if (ws.readyState === WebSocket.OPEN) {
          pingSentAt.t = Date.now();
          ws.send(JSON.stringify({ type: 'ping' }));
        }
      };

      ws.onopen = () => {
        setLogs((prev) => [...prev, makeLog(tRef.current('wsConnected'), 'system')]);
        fetchBackups();
        sendPing();
        ws.send(JSON.stringify({ type: 'set_lang', lang: langRef.current }));
        pingTimer = setInterval(sendPing, 3000);
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'init') {
            if (msg.logs) setLogs(msg.logs);
            if (msg.status) setStatus(msg.status);
          } else if (msg.type === 'log') {
            setLogs((prev) => [...prev, msg.data]);
          } else if (msg.type === 'status') {
            setStatus(msg.data);
          } else if (msg.type === 'pong') {
            setLatency(Date.now() - pingSentAt.t);
          }
        } catch (e) {
          console.error(e);
        }
      };

      ws.onclose = () => {
        if (pingTimer) clearInterval(pingTimer);
        setLogs((prev) => [...prev, makeLog(tRef.current('wsDisconnected'), 'error')]);
        setTimeout(connect, 3000);
      };
    };

    connect();
    fetchBackups();

    return () => {
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
    document.title = status.running
      ? tRef.current('titleRunning', { count: status.player_count })
      : tRef.current('titleStopped');
  }, [status.running, status.player_count, lang]);

  const fetchBackups = async () => {
    try {
      const res = await fetch('/api/backups');
      const data = await res.json();
      if (data.backups) setBackups(data.backups);
    } catch (e) {
      console.error(e);
    }
  };

  const fetchPlayers = async () => {
    try {
      const res = await fetch('/api/players');
      setPlayersData(await res.json());
    } catch (e) {
      console.error(e);
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
      const data = await res.json();
      setUpdateInfo(data);
    } catch (e) {
      console.error(e);
    }
  };

  const handleOpenProps = async () => {
    setIsPropsModalOpen(true);
    try {
      const res = await fetch('/api/server_properties');
      const data = await res.json();
      setPropsFields(data.fields || {});
      setPropsServerRunning(!!data.server_running);
    } catch (e) {
      console.error(e);
    }
  };

  const handleOpenSchedule = async () => {
    setIsScheduleModalOpen(true);
    try {
      const res = await fetch('/api/schedule');
      setScheduleConfig(await res.json());
    } catch (e) {
      console.error(e);
    }
  };

  const handleConfirmUpdate = async () => {
    setIsUpdating(true);
    setUpdateStarted(true);
    try {
      await fetch('/api/action/update_bds', { method: 'POST' });
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
      await fetch('/api/action/rollback_bds', { method: 'POST' });
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
      const data = await res.json();
      setLogs((prev) => [...prev, makeLog(tRef.current('actionExecuted', { action: actionName, status: data.status }), 'system')]);
      fetchBackups();
    } catch (e) {
      setLogs((prev) => [...prev, makeLog(tRef.current('actionError', { action: actionName, err: e }), 'error')]);
    }
  };

  const handleSendCommand = async (command) => {
    if (!status.running) {
      setLogs((prev) => [
        ...prev,
        makeLog(`> ${command}`, 'command'),
        makeLog(tRef.current('serverOff'), 'error')
      ]);
      return;
    }

    try {
      await fetch('/api/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command })
      });
    } catch (e) {
      setLogs((prev) => [...prev, makeLog(tRef.current('commandError', { err: e }), 'error')]);
    }
  };

  // Loader mientras se determina si hay setup inicial pendiente
  if (setupInfo === null) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950 font-sans text-slate-100">
        <div className="flex items-center gap-3">
          <svg className="h-5 w-5 animate-spin text-emerald-400" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          <span className="animate-pulse text-sm font-bold text-slate-300">{t('loading')}</span>
        </div>
      </div>
    );
  }

  // Setup inicial: reemplaza el dashboard hasta completarlo (instalaciones nuevas)
  if (setupInfo && setupInfo.required) {
    return (
      <SetupWizard
        bdsInstalled={!!setupInfo.bds_installed}
        logs={logs}
        onDone={() => setSetupAttempt((a) => a + 1)}
      />
    );
  }

  return (
    <div className="relative min-h-screen text-slate-100 p-5 font-sans">
      {/* Capa de nieve sutil (ReactBits PixelSnow): entre el fondo y el contenido,
          sin bloquear clics, con caída diagonal natural y baja densidad/brillo
          para no competir con las tarjetas del dashboard.
          IMPORTANTE: el posicionamiento va por style inline porque
          .pixel-snow-container define position:relative sin @layer, y en la
          cascada CSS eso pisa las utilities de Tailwind (fixed inset-0). */}
      <PixelSnow
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          width: '100vw',
          height: '100vh',
          zIndex: 1,
          pointerEvents: 'none'
        }}
        color="#e2e8f0"
        flakeSize={0.008}
        minFlakeSize={1.1}
        pixelResolution={220}
        speed={0.85}
        density={0.22}
        depthFade={9}
        farPlane={22}
        brightness={0.55}
        gamma={0.4545}
        variant="round"
        direction={125}
      />

      <div className="relative z-10 mx-auto max-w-7xl space-y-5">
        {/* Cabecera Principal */}
        <Navbar status={status} onOpenUpdate={handleOpenUpdate} onOpenProps={handleOpenProps} onOpenSchedule={handleOpenSchedule} latency={latency} />

        {/* Botonera de Control con ClickSpark & ConfirmButton */}
        <ControlsBar status={status} onAction={handleAction} />

        {/* Métricas de Hardware y Conectividad en 2 Columnas */}
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
          <HardwareMeter hardware={status.hardware} running={status.running} />
          <ConnectivityCard
            connectivity={connectivity}
            running={status.running}
            onRefresh={() => fetchConnectivity(true)}
          />
        </div>

        {/* Área Principal Dividida: Consola Terminal y Panel Lateral por Pestañas (Hover.dev ChipTabs) */}
        <main className="grid grid-cols-1 gap-5 lg:grid-cols-[1fr_340px]">
          <TerminalConsole
            logs={logs}
            onSendCommand={handleSendCommand}
            onClearLogs={() => setLogs([])}
            isRunning={status.running}
          />
          <aside>
            <SidebarTabs
              players={status.players}
              playersData={playersData}
              backups={backups}
              onRefreshBackups={fetchBackups}
              onRefreshPlayers={fetchPlayers}
              isRunning={status.running}
            />
          </aside>
        </main>

        <footer className="border-t border-white/10 pt-3 pb-2 text-center text-xs text-slate-500">
          Minecraft Bedrock Server Suite &bull; Not an official Minecraft product. Not approved by or associated with Mojang or Microsoft.
        </footer>
      </div>

      {/* Modal de Actualización de BDS (Hover.dev SpringModal) */}
      <UpdateModal
        isOpen={isUpdateModalOpen}
        onClose={() => setIsUpdateModalOpen(false)}
        updateInfo={updateInfo}
        onConfirmUpdate={handleConfirmUpdate}
        onRollback={handleRollback}
        isUpdating={isUpdating}
      />

      {/* Modal de Configuración (server.properties) */}
      <PropsModal
        isOpen={isPropsModalOpen}
        onClose={() => setIsPropsModalOpen(false)}
        fields={propsFields}
        serverRunning={propsServerRunning}
      />

      {/* Modal de Programación (backups + watchdog) */}
      <ScheduleModal
        isOpen={isScheduleModalOpen}
        onClose={() => setIsScheduleModalOpen(false)}
        config={scheduleConfig}
      />
    </div>
  );
}
