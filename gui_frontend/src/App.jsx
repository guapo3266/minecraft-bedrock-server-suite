import React, { useState, useEffect, useRef } from 'react';
import PixelSnow from './components/reactbits/PixelSnow';
import Navbar from './components/Navbar';
import HardwareMeter from './components/HardwareMeter';
import ControlsBar from './components/ControlsBar';
import TerminalConsole from './components/TerminalConsole';
import SidebarTabs from './components/SidebarTabs';
import UpdateModal from './components/UpdateModal';
import { useI18n } from './i18n.jsx';

export default function App() {
  const { t } = useI18n();
  const tRef = useRef(t);
  tRef.current = t;

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
  const [isUpdateModalOpen, setIsUpdateModalOpen] = useState(false);
  const [updateInfo, setUpdateInfo] = useState(null);
  const [isUpdating, setIsUpdating] = useState(false);
  const [updateStarted, setUpdateStarted] = useState(false);
  const [latency, setLatency] = useState(null);
  const wsRef = useRef(null);
  const updateStartedRef = useRef(false);

  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

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
        setLogs((prev) => [...prev, { time: new Date().toLocaleTimeString(), text: tRef.current('wsConnected'), type: 'system' }]);
        fetchBackups();
        sendPing();
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
        setLogs((prev) => [...prev, { time: new Date().toLocaleTimeString(), text: tRef.current('wsDisconnected'), type: 'error' }]);
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

  const fetchBackups = async () => {
    try {
      const res = await fetch('/api/backups');
      const data = await res.json();
      if (data.backups) setBackups(data.backups);
    } catch (e) {
      console.error(e);
    }
  };

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

  const handleAction = async (actionName) => {
    try {
      const res = await fetch(`/api/action/${actionName}`, { method: 'POST' });
      const data = await res.json();
      setLogs((prev) => [...prev, { time: new Date().toLocaleTimeString(), text: tRef.current('actionExecuted', { action: actionName, status: data.status }), type: 'system' }]);
      fetchBackups();
    } catch (e) {
      setLogs((prev) => [...prev, { time: new Date().toLocaleTimeString(), text: tRef.current('actionError', { action: actionName, err: e }), type: 'error' }]);
    }
  };

  const handleSendCommand = async (command) => {
    if (!status.running) {
      setLogs((prev) => [
        ...prev,
        { time: new Date().toLocaleTimeString(), text: `> ${command}`, type: 'command' },
        { time: new Date().toLocaleTimeString(), text: tRef.current('serverOff'), type: 'error' }
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
      setLogs((prev) => [...prev, { time: new Date().toLocaleTimeString(), text: tRef.current('commandError', { err: e }), type: 'error' }]);
    }
  };

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
        <Navbar status={status} onOpenUpdate={handleOpenUpdate} latency={latency} />

        {/* Botonera de Control con ClickSpark & ConfirmButton */}
        <ControlsBar status={status} onAction={handleAction} />

        {/* Medidor Compacto de Hardware (RAM & CPU) */}
        <HardwareMeter hardware={status.hardware} />

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
              backups={backups}
              onRefreshBackups={fetchBackups}
            />
          </aside>
        </main>

        <footer className="border-t border-white/10 pt-3 text-center text-xs text-slate-400">
          Bedrock Dedicated Server &bull; ReactBits + ItsHover + Hover.dev &bull; Clean Dashboard
        </footer>
      </div>

      {/* Modal de Actualización de BDS (Hover.dev SpringModal) */}
      <UpdateModal
        isOpen={isUpdateModalOpen}
        onClose={() => setIsUpdateModalOpen(false)}
        updateInfo={updateInfo}
        onConfirmUpdate={handleConfirmUpdate}
        isUpdating={isUpdating}
      />
    </div>
  );
}
