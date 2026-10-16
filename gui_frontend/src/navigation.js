import { Server, Users, FolderArchive, Boxes } from 'lucide-react';

export const SECTIONS = [
  { id: 'server', label: 'serverTab', subtitle: 'serverViewHint', icon: Server },
  { id: 'players', label: 'playersTab', subtitle: 'playersViewHint', icon: Users },
  { id: 'backups', label: 'backupsTab', subtitle: 'backupsViewHint', icon: FolderArchive },
  { id: 'addons', label: 'addonsTab', subtitle: 'addonsViewHint', icon: Boxes }
];
