// Campos editables de server.properties (UI): UNA sola fuente compartida
// entre PropsModal y el SetupWizard (first-run). Las claves deben existir
// en PROPS_FIELDS del backend (server_gui_server.py).
export const FIELDS = [
  { key: 'server-name', type: 'text', label: 'propsServerName' },
  { key: 'gamemode', type: 'select', label: 'propsGamemode', options: ['survival', 'creative', 'adventure'] },
  { key: 'difficulty', type: 'select', label: 'propsDifficulty', options: ['peaceful', 'easy', 'normal', 'hard'] },
  { key: 'allow-cheats', type: 'bool', label: 'propsAllowCheats' },
  { key: 'max-players', type: 'number', label: 'propsMaxPlayers', min: 1, max: 999 },
  { key: 'online-mode', type: 'bool', label: 'propsOnlineMode' },
  { key: 'allow-list', type: 'bool', label: 'propsAllowList' },
  { key: 'server-port', type: 'number', label: 'propsServerPort', min: 1, max: 65535 },
  { key: 'view-distance', type: 'number', label: 'propsViewDistance', min: 5, max: 96 },
  { key: 'tick-distance', type: 'number', label: 'propsTickDistance', min: 4, max: 12 },
  { key: 'player-idle-timeout', type: 'number', label: 'propsIdleTimeout', min: 0, max: 10080 },
  { key: 'default-player-permission-level', type: 'select', label: 'propsPermLevel', options: ['visitor', 'member', 'operator'] }
];
