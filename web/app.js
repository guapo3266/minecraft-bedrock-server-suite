/**
 * app.js — Lógica de Cliente en Tiempo Real (WebSocket + REST)
 * ==========================================================
 */

let ws = null;
let isServerRunning = false;
let uptimeInterval = null;
let currentUptimeSec = 0;

// Elementos DOM
const statusBadge = document.getElementById('server-status-badge');
const statusText = document.getElementById('status-text');
const metricStatus = document.getElementById('metric-status');
const metricUptime = document.getElementById('metric-uptime');
const metricPlayerCount = document.getElementById('metric-player-count');
const metricPlayersSummary = document.getElementById('metric-players-list-summary');
const metricLastBackup = document.getElementById('metric-last-backup');
const metricBackupStatus = document.getElementById('metric-backup-status');

const btnStart = document.getElementById('btn-start');
const btnStop = document.getElementById('btn-stop');
const btnRestart = document.getElementById('btn-restart');
const btnBackup = document.getElementById('btn-backup');

const terminalBody = document.getElementById('terminal-body');
const commandForm = document.getElementById('command-form');
const commandInput = document.getElementById('command-input');
const playersListEl = document.getElementById('players-list');
const backupsListEl = document.getElementById('backups-list');
const btnRefreshBackups = document.getElementById('btn-refresh-backups');
const btnClearLogs = document.getElementById('btn-clear-logs');

// ═══════════════════════════════════════════════════════════════
// WEBSOCKET LOG & STATUS CLIENT
// ═══════════════════════════════════════════════════════════════
function connectWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws`;

  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    appendLog('[WEBSOCKET] Conectado al backend en tiempo real.', 'system');
    fetchBackupsList();
  };

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === 'init') {
        // Historial inicial
        terminalBody.innerHTML = '';
        if (msg.logs) {
          msg.logs.forEach(log => appendLog(`[${log.time}] ${log.text}`, log.type));
        }
        if (msg.status) {
          updateUIStatus(msg.status);
        }
      } else if (msg.type === 'log') {
        appendLog(`[${msg.data.time}] ${msg.data.text}`, msg.data.type);
      } else if (msg.type === 'status') {
        updateUIStatus(msg.data);
      }
    } catch (e) {
      console.error('Error procesando mensaje WebSocket:', e);
    }
  };

  ws.onclose = () => {
    appendLog('[WEBSOCKET] Desconectado. Reintentando en 3 segundos...', 'error');
    setTimeout(connectWebSocket, 3000);
  };
}

// ═══════════════════════════════════════════════════════════════
// ACTUALIZACIÓN DE INTERFAZ DE USUARIO
// ═══════════════════════════════════════════════════════════════
function updateUIStatus(data) {
  isServerRunning = data.running;

  // Actualizar Badge de Estado
  if (data.backup_in_progress) {
    statusBadge.className = 'status-badge backup glow-border';
    statusText.textContent = 'BACKUP EN PROCESO';
    metricStatus.textContent = 'Backup en Vivo';
    metricBackupStatus.textContent = 'Guardando datos...';
  } else if (data.running) {
    statusBadge.className = 'status-badge online glow-border';
    if (statusText.textContent !== 'ONLINE') {
      DecryptedText.animate(statusText, 'ONLINE');
    }
    metricStatus.textContent = 'En Línea (BDS)';
    metricBackupStatus.textContent = 'Listo (30m Interval)';
  } else {
    statusBadge.className = 'status-badge offline glow-border';
    statusText.textContent = 'OFFLINE';
    metricStatus.textContent = 'Detenido';
    metricBackupStatus.textContent = 'Standby';
  }

  // Botones e Inputs
  btnStart.disabled = data.running;
  btnStop.disabled = !data.running;
  btnRestart.disabled = !data.running;

  if (commandInput) {
    commandInput.placeholder = data.running
      ? "Escribe un comando de Minecraft (ej: op player, say Hola, list)..."
      : "Servidor APAGADO — Haz clic en '▶ Iniciar Servidor' primero...";
  }

  // Contador de Jugadores
  metricPlayerCount.textContent = data.player_count || 0;
  if (data.players && data.players.length > 0) {
    metricPlayersSummary.textContent = data.players.join(', ');
    renderPlayersList(data.players);
  } else {
    metricPlayersSummary.textContent = 'Sin jugadores online';
    renderPlayersList([]);
  }

  // Backup
  if (data.last_backup) {
    metricLastBackup.textContent = data.last_backup;
  }

  // Uptime
  currentUptimeSec = data.uptime || 0;
  updateUptimeDisplay();
}

function updateUptimeDisplay() {
  if (!isServerRunning || currentUptimeSec <= 0) {
    metricUptime.textContent = 'Uptime: 00:00:00';
    return;
  }
  const hrs = String(Math.floor(currentUptimeSec / 3600)).padStart(2, '0');
  const mins = String(Math.floor((currentUptimeSec % 3600) / 60)).padStart(2, '0');
  const secs = String(currentUptimeSec % 60).padStart(2, '0');
  metricUptime.textContent = `Uptime: ${hrs}:${mins}:${secs}`;
}

// Timer secundario para actualizar Uptime visualmente cada segundo
setInterval(() => {
  if (isServerRunning) {
    currentUptimeSec++;
    updateUptimeDisplay();
  }
}, 1000);

// ═══════════════════════════════════════════════════════════════
// LOGS Y TERMINAL
// ═══════════════════════════════════════════════════════════════
function appendLog(text, type = 'info') {
  const entry = document.createElement('div');
  entry.className = `log-entry ${type}`;
  entry.textContent = text;
  terminalBody.appendChild(entry);

  // Mantener scroll abajo automáticamente
  terminalBody.scrollTop = terminalBody.scrollHeight;
}

btnClearLogs.addEventListener('click', () => {
  terminalBody.innerHTML = '';
});

// ═══════════════════════════════════════════════════════════════
// ACCIONES DE BOTONES Y FORMULARIO DE COMANDOS
// ═══════════════════════════════════════════════════════════════
async function triggerAction(actionName) {
  try {
    const res = await fetch(`/api/action/${actionName}`, { method: 'POST' });
    const data = await res.json();
    appendLog(`[GUI] Acción '${actionName}' solicitada: ${data.status}`, 'system');
    fetchBackupsList();
  } catch (e) {
    appendLog(`[GUI] Error al ejecutar acción '${actionName}': ${e}`, 'error');
  }
}

btnStart.addEventListener('click', () => triggerAction('start'));
btnStop.addEventListener('click', () => triggerAction('stop'));
btnRestart.addEventListener('click', () => triggerAction('restart'));
btnBackup.addEventListener('click', () => triggerAction('backup'));

commandForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const cmd = commandInput.value.trim();
  if (!cmd) return;

  commandInput.value = '';

  if (!isServerRunning) {
    appendLog(`> ${cmd}`, 'command');
    appendLog('[SISTEMA] El servidor está APAGADO. Haz clic en "▶ Iniciar Servidor" para encenderlo.', 'error');
    return;
  }

  try {
    const res = await fetch('/api/command', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: cmd })
    });
    const data = await res.json();
    if (data.status === 'offline') {
      appendLog('[SISTEMA] El servidor no está en ejecución.', 'error');
    }
  } catch (e) {
    appendLog(`[GUI] Error enviando comando: ${e}`, 'error');
  }
});

// Quick Commands Chips
document.querySelectorAll('.chip-cmd').forEach(chip => {
  chip.addEventListener('click', () => {
    const cmd = chip.getAttribute('data-cmd');
    if (cmd) {
      commandInput.value = cmd;
      commandForm.dispatchEvent(new Event('submit'));
    }
  });
});

// ═══════════════════════════════════════════════════════════════
// LISTAS DE JUGADORES Y BACKUPS
// ═══════════════════════════════════════════════════════════════
function renderPlayersList(players) {
  playersListEl.innerHTML = '';
  if (!players || players.length === 0) {
    playersListEl.innerHTML = '<li class="empty-msg">No hay jugadores conectados</li>';
    return;
  }

  players.forEach(p => {
    const li = document.createElement('li');
    li.className = 'player-item';
    const initial = p.charAt(0).toUpperCase();
    li.innerHTML = `
      <div class="player-avatar">${initial}</div>
      <span class="player-name">${p}</span>
    `;
    playersListEl.appendChild(li);
  });
}

async function fetchBackupsList() {
  try {
    const res = await fetch('/api/backups');
    const data = await res.json();
    backupsListEl.innerHTML = '';

    if (!data.backups || data.backups.length === 0) {
      backupsListEl.innerHTML = '<div class="empty-msg">No se encontraron respaldos ZIP</div>';
      return;
    }

    data.backups.slice(0, 8).forEach(b => {
      const item = document.createElement('div');
      item.className = 'backup-item';
      item.innerHTML = `
        <div>
          <strong style="color: #fff;">${b.filename}</strong>
          <div style="color: var(--text-muted); font-size: 0.75rem;">${b.date} &bull; ${b.size_mb} MB</div>
        </div>
      `;
      backupsListEl.appendChild(item);
    });
  } catch (e) {
    backupsListEl.innerHTML = '<div class="empty-msg">Error al cargar respaldos</div>';
  }
}

btnRefreshBackups.addEventListener('click', fetchBackupsList);

// Inicializar conexión
document.addEventListener('DOMContentLoaded', connectWebSocket);
