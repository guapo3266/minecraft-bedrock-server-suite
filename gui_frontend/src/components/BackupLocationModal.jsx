import React, { useState } from 'react';
import { FolderCog, Save, RotateCcw, TriangleAlert, CircleCheck as FilledCheckedIcon } from 'lucide-react';
import ConfirmButton from './hover/ConfirmButton';
import Modal from './Modal';
import { useI18n } from '../i18n.jsx';
import { backupLocationErrorKey, previewBackupDir } from '../backupLocationLogic.js';

// Cambia la carpeta raíz de los backups (POST /api/backups/location). Los
// backups existentes no se mueven: el resultado dice cuántos quedan atrás.
export default function BackupLocationModal({ location, onClose, onSaved }) {
  const { t } = useI18n();
  const [value, setValue] = useState(location.custom ? location.root : '');
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState(null); // { ok, message, note }

  const preview = previewBackupDir(value, location);

  const handleSave = async () => {
    setSaving(true);
    setResult(null);
    try {
      const res = await fetch('/api/backups/location', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ root: value.trim() || null })
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        let note = '';
        if (data.left_behind === 1) {
          note = t('backupDirLeftBehindOne', { dir: data.previous_backup_dir });
        } else if (data.left_behind > 1) {
          note = t('backupDirLeftBehind', { count: data.left_behind, dir: data.previous_backup_dir });
        }
        setResult({ ok: true, message: t('backupDirSaved', { dir: data.location.backup_dir }), note });
        setValue(data.location.custom ? data.location.root : '');
        onSaved(data.location);
      } else {
        const key = backupLocationErrorKey(data.detail);
        setResult({ ok: false, message: key ? t(key) : (data.detail || res.statusText) });
      }
    } catch (e) {
      setResult({ ok: false, message: String(e) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal onClose={onClose} label={t('backupDirTitle')} className="max-w-md border-amber-500/40">
      <div className="flex items-center gap-3">
        <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-amber-500/20 border border-amber-500/50">
          <FolderCog className="h-5 w-5 text-amber-400" />
        </div>
        <div>
          <h3 className="text-base font-bold text-white">{t('backupDirTitle')}</h3>
          <p className="text-xs text-slate-400">{t('backupDirSubtitle')}</p>
        </div>
      </div>

      <p className="mt-4 text-[11px] text-slate-400">{t('backupDirCurrent')}</p>
      <p className="break-all font-mono text-[11px] text-slate-200">{location.backup_dir}</p>

      <label htmlFor="backup-dir-root" className="mt-4 block text-xs font-semibold text-slate-300">
        {t('backupDirRootLabel')}
      </label>
      <input
        id="backup-dir-root"
        type="text" autoComplete="off" spellCheck={false}
        value={value}
        placeholder={t('backupDirPlaceholder')}
        onChange={(e) => setValue(e.target.value)}
        className="settings-input mt-1.5 font-mono"
      />
      <p className="mt-2 text-[11px] text-slate-400">{t('backupDirPreview')}</p>
      <p className="break-all font-mono text-[11px] text-amber-300">{preview}</p>
      <p className="mt-3 text-[11px] leading-relaxed text-slate-400">{t('backupDirHelp')}</p>

      {result && (
        <div
          aria-live="polite"
          className={`mt-4 rounded-lg border px-3 py-2 text-xs font-semibold ${
            result.ok
              ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
              : 'border-rose-500/40 bg-rose-500/10 text-rose-300'
          }`}
        >
          <div className="flex items-center gap-2">
            {result.ok ? <FilledCheckedIcon size={18} className="shrink-0 text-emerald-400" /> : <TriangleAlert className="h-4 w-4 shrink-0" />}
            <span className="break-all">{result.message}</span>
          </div>
          {result.note && <p className="mt-1.5 break-all font-normal text-amber-200">{result.note}</p>}
        </div>
      )}

      <div className="mt-5 flex justify-end gap-3">
        <ConfirmButton variant="amber" onClick={() => setValue('')} disabled={saving || !value} className="px-4 py-2">
          <RotateCcw className="h-4 w-4" />
          <span>{t('backupDirUseDefault')}</span>
        </ConfirmButton>
        <ConfirmButton variant="amber" onClick={onClose} className="px-4 py-2">
          {t('close')}
        </ConfirmButton>
        <ConfirmButton variant="emerald" onClick={handleSave} disabled={saving} className="px-4 py-2">
          <Save className="h-4 w-4" />
          <span>{saving ? t('saving') : t('save')}</span>
        </ConfirmButton>
      </div>
    </Modal>
  );
}
