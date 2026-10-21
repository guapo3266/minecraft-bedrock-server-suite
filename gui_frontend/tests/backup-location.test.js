// Lógica pura de la carpeta de backups (sin jsdom): vista previa de
// <raíz>\<servidor> y traducción de los códigos de error del backend.
import { describe, expect, it } from 'vitest';
import {
  BACKUP_LOCATION_ERRORS,
  backupLocationErrorKey,
  previewBackupDir
} from '../src/backupLocationLogic.js';
import { STRINGS } from '../src/i18n.jsx';

const location = {
  server_name: 'Servidor de Guapo',
  default_backup_dir: 'C:\\Users\\x\\Backups_Minecraft\\auto_backups\\Servidor de Guapo'
};

describe('previewBackupDir', () => {
  it('sin raíz muestra la carpeta predeterminada', () => {
    expect(previewBackupDir('', location)).toBe(location.default_backup_dir);
    expect(previewBackupDir('   ', location)).toBe(location.default_backup_dir);
  });

  it('añade la subcarpeta del servidor sin duplicar separadores', () => {
    expect(previewBackupDir('D:\\Backups', location)).toBe('D:\\Backups\\Servidor de Guapo');
    expect(previewBackupDir('D:\\Backups\\', location)).toBe('D:\\Backups\\Servidor de Guapo');
    expect(previewBackupDir('D:/Backups/', location)).toBe('D:\\Backups\\Servidor de Guapo');
    expect(previewBackupDir('D:\\', location)).toBe('D:\\Servidor de Guapo');
  });

  it('sin datos del backend no inventa una ruta', () => {
    expect(previewBackupDir('D:\\Backups', null)).toBe('');
  });
});

describe('backupLocationErrorKey', () => {
  it('cada código conocido tiene su texto en ES y EN', () => {
    for (const code of BACKUP_LOCATION_ERRORS) {
      const key = backupLocationErrorKey(code);
      expect(typeof STRINGS.es[key]).toBe('string');
      expect(typeof STRINGS.en[key]).toBe('string');
    }
  });

  it('un detail desconocido se muestra tal cual', () => {
    expect(backupLocationErrorKey('Cuerpo JSON invalido')).toBeNull();
    expect(backupLocationErrorKey(undefined)).toBeNull();
  });
});
