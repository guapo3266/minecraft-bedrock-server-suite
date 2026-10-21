// Lógica pura de la carpeta de backups (sin React, probada con vitest).
// Espejo de backup_location.py: los backups de una instalación van a
// <raíz>\<servidor>. La vista previa solo orienta; la ruta real la decide y
// la devuelve el backend al guardar.

// Códigos estables de POST /api/backups/location (detail). Todo código que
// emita el backend necesita su clave i18n backupDirErr_<código>:
// tests/test_carpeta_backups.py lo comprueba contra backup_location.py.
export const BACKUP_LOCATION_ERRORS = [
  'invalid_path',
  'not_absolute',
  'too_long',
  'inside_installation',
  'contains_installation',
  'not_a_directory',
  'not_writable',
  'busy',
  'backup_in_progress'
];

export function previewBackupDir(root, location) {
  if (!location) return '';
  const trimmed = (root || '').trim();
  if (!trimmed) return location.default_backup_dir;
  const base = trimmed.replace(/\//g, '\\').replace(/\\+$/, '');
  return `${base}\\${location.server_name}`;
}

// Clave i18n del error, o null si el detail no es un código conocido (se
// muestra tal cual: p. ej. "Cuerpo JSON invalido").
export function backupLocationErrorKey(detail) {
  return BACKUP_LOCATION_ERRORS.includes(detail) ? `backupDirErr_${detail}` : null;
}
