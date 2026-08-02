import { createContext, useContext, useEffect, useMemo, useState } from 'react';

// Contexto + hook en el mismo archivo es el patrón idiomático de React
/* oxlint-disable react/only-export-components */

// Diccionario de textos de la GUI (ES por defecto)
const STRINGS = {
  es: {
    start: 'Iniciar Servidor',
    stop: 'Detener',
    restart: 'Reiniciar',
    backup: 'Forzar Backup',
    updateBds: 'Actualización BDS',
    online: 'ONLINE',
    offline: 'OFFLINE',
    backupInProgress: 'BACKUP EN PROCESO',
    hotBackup: 'HOT BACKUP',
    disconnected: 'DISCONNECTED',
    latency: '{ms}ms LATENCY',
    terminalTitle: 'TERMINAL DE CONSOLA (LOGS EN VIVO)',
    clear: 'Limpiar',
    send: 'Enviar',
    waitingLogs: '[SISTEMA] Esperando logs del servidor...',
    placeholderRunning: 'Escribe un comando (ej: op player, say Hola, list)...',
    placeholderStopped: 'Servidor APAGADO — Presiona Iniciar Servidor...',
    playersOnline: 'Jugadores en Línea',
    noPlayers: 'No hay jugadores conectados',
    backupsTitle: 'Historial de Backups',
    noBackups: 'No se encontraron respaldos ZIP',
    ram: 'Memoria RAM',
    cpu: 'Procesador CPU',
    off: 'Apagado',
    mbOf: 'MB / {total} GB',
    cpuUsage: '% de uso BDS',
    playersTab: 'Jugadores',
    backupsTab: 'Backups',
    updaterTitle: 'Actualizador Oficial Mojang BDS',
    updaterSubtitle: 'Verificación de versión del ejecutable',
    newVersion: '¡NUEVA VERSIÓN DETECTADA DE MOJANG!',
    currentVersion: 'Versión actual en tu servidor:',
    upToDate: 'TU SERVIDOR ESTÁ EN LA ÚLTIMA VERSIÓN',
    activeVersion: 'Versión Activa:',
    protectionTitle: 'Protocolo de Protección de Datos Activo:',
    protection1: 'Se ejecutará un Backup Preventivo Automático antes de actualizar.',
    protection2: 'Tus mundos (worlds/) y configs (server.properties) no se borrarán.',
    cancel: 'Cancelar',
    updateNow: 'Descargar & Actualizar Ahora',
    updating: 'Actualizando BDS...',
    wsConnected: '[WEBSOCKET] Conectado a React Backend.',
    wsDisconnected: '[WEBSOCKET] Desconectado. Reintentando...',
    actionExecuted: "[GUI] Acción '{action}' ejecutada ({status}).",
    actionError: "[GUI] Error al ejecutar acción '{action}': {err}",
    commandError: '[GUI] Error enviando comando: {err}',
    serverOff: '[SISTEMA] El servidor está APAGADO. Haz clic en "Iniciar Servidor" primero.',
    restore: 'Reestablecer',
    restoreTitle: 'Reestablecer backup',
    restoreConfirm: '¿Restaurar este backup?',
    restoreWarning: 'El mundo actual será reemplazado por este punto de restauración. Esta acción no se puede deshacer.',
    restoreServerOn: 'El servidor está encendido',
    restoreServerOnMsg: 'Debes apagar el servidor antes de reestablecer un backup.',
    restoreSuccess: 'Backup restaurado correctamente',
    restoreFailed: 'No se pudo restaurar el backup',
    restoring: 'Restaurando...'
  },
  en: {
    start: 'Start Server',
    stop: 'Stop',
    restart: 'Restart',
    backup: 'Force Backup',
    updateBds: 'BDS Update',
    online: 'ONLINE',
    offline: 'OFFLINE',
    backupInProgress: 'BACKUP IN PROGRESS',
    hotBackup: 'HOT BACKUP',
    disconnected: 'DISCONNECTED',
    latency: '{ms}ms LATENCY',
    terminalTitle: 'LIVE CONSOLE TERMINAL',
    clear: 'Clear',
    send: 'Send',
    waitingLogs: '[SYSTEM] Waiting for server logs...',
    placeholderRunning: 'Type a command (e.g. op player, say Hello, list)...',
    placeholderStopped: 'Server OFF — Press Start Server...',
    playersOnline: 'Online Players',
    noPlayers: 'No players connected',
    backupsTitle: 'Backup History',
    noBackups: 'No ZIP backups found',
    ram: 'RAM Memory',
    cpu: 'CPU',
    off: 'Off',
    mbOf: 'MB / {total} GB',
    cpuUsage: '% BDS usage',
    playersTab: 'Players',
    backupsTab: 'Backups',
    updaterTitle: 'Official Mojang BDS Updater',
    updaterSubtitle: 'Executable version check',
    newVersion: 'NEW MOJANG VERSION DETECTED!',
    currentVersion: 'Your current server version:',
    upToDate: 'YOUR SERVER IS UP TO DATE',
    activeVersion: 'Active Version:',
    protectionTitle: 'Data Protection Protocol Active:',
    protection1: 'An automatic preventive backup will run before updating.',
    protection2: 'Your worlds (worlds/) and configs (server.properties) will not be deleted.',
    cancel: 'Cancel',
    updateNow: 'Download & Update Now',
    updating: 'Updating BDS...',
    wsConnected: '[WEBSOCKET] Connected to React Backend.',
    wsDisconnected: '[WEBSOCKET] Disconnected. Retrying...',
    actionExecuted: "[GUI] Action '{action}' executed ({status}).",
    actionError: "[GUI] Error running action '{action}': {err}",
    commandError: '[GUI] Error sending command: {err}',
    serverOff: '[SYSTEM] The server is OFF. Click "Start Server" first.',
    restore: 'Restore',
    restoreTitle: 'Restore backup',
    restoreConfirm: 'Restore this backup?',
    restoreWarning: 'The current world will be replaced by this restore point. This action cannot be undone.',
    restoreServerOn: 'The server is running',
    restoreServerOnMsg: 'You must stop the server before restoring a backup.',
    restoreSuccess: 'Backup restored successfully',
    restoreFailed: 'Could not restore the backup',
    restoring: 'Restoring...'
  }
};

const LanguageContext = createContext(null);

export function LanguageProvider({ children }) {
  const [lang, setLang] = useState(() => {
    try {
      return localStorage.getItem('gui_lang') || 'es';
    } catch {
      return 'es';
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem('gui_lang', lang);
    } catch {
      // sin localStorage (modo privado): se ignora
    }
  }, [lang]);

  const value = useMemo(() => {
    const t = (key, vars = {}) => {
      let s = STRINGS[lang]?.[key] ?? STRINGS.es[key] ?? key;
      for (const [k, v] of Object.entries(vars)) {
        s = s.replaceAll(`{${k}}`, String(v));
      }
      return s;
    };
    return { lang, setLang, t };
  }, [lang]);

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useI18n() {
  return useContext(LanguageContext);
}
