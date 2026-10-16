import { LockKeyhole, X } from 'lucide-react';
import Modal from './Modal';
import { useI18n } from '../i18n.jsx';

export default function AboutModal({ onClose }) {
  const { t } = useI18n();
  return <Modal onClose={onClose} label={t('aboutTitle')} className="about-dialog">
    <div className="dialog-heading">
      <div><span className="eyebrow">{t('aboutTitle')}</span><h2>Minecraft Bedrock Server Suite</h2></div>
      <button type="button" className="button icon-button" onClick={onClose} aria-label={t('close')}><X size={18} /></button>
    </div>
    <p className="about-local"><LockKeyhole size={16} aria-hidden="true" />{t('localManagement')}</p>
    <p>Not an official Minecraft product. Not approved by or associated with Mojang or Microsoft.</p>
  </Modal>;
}
