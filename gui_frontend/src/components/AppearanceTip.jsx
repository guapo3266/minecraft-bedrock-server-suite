import { useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { useI18n } from '../i18n.jsx';

// Consejo no modal: no roba el foco ni modifica la altura de la cabecera.
export default function AppearanceTip({ anchorRef, onDismiss, onCustomize }) {
  const { t } = useI18n();
  const tipRef = useRef(null);
  const dismissRef = useRef(onDismiss);
  dismissRef.current = onDismiss;
  const [position, setPosition] = useState(null);
  useLayoutEffect(() => {
    const anchor = anchorRef.current, tip = tipRef.current;
    if (!anchor || !tip) return;
    const place = () => {
      const rect = anchor.getBoundingClientRect();
      setPosition({
        left: Math.max(12, Math.min(rect.right - tip.offsetWidth, window.innerWidth - tip.offsetWidth - 12)),
        top: Math.max(12, Math.min(rect.bottom + 10, window.innerHeight - tip.offsetHeight - 12))
      });
    };
    const observer = new ResizeObserver(place);
    observer.observe(tip);
    observer.observe(anchor.parentElement);
    const outside = event => {
      if (event.target instanceof Node && !tip.contains(event.target) && !anchor.contains(event.target)) dismissRef.current();
    };
    document.addEventListener('pointerdown', outside, true);
    window.addEventListener('resize', place);
    place();
    return () => {
      observer.disconnect();
      document.removeEventListener('pointerdown', outside, true);
      window.removeEventListener('resize', place);
    };
  }, [anchorRef]);

  const dismiss = () => { onDismiss(); anchorRef.current?.focus({ preventScroll: true }); };
  return createPortal(<aside ref={tipRef} className="glass-menu appearance-tip" role="note"
    aria-labelledby="appearance-tip-title" style={position || { visibility: 'hidden' }}
    onKeyDown={event => { if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); dismiss(); } }}>
    <div className="appearance-tip-heading">
      <strong id="appearance-tip-title">{t('appearanceTipTitle')}</strong>
      <button type="button" className="button icon-button" onClick={dismiss} aria-label={t('appearanceTipClose')}><X size={16} /></button>
    </div>
    <p id="appearance-tip-body">{t('appearanceTipBody')}</p>
    <button type="button" className="button primary" onClick={onCustomize}>{t('appearanceTipAction')}</button>
  </aside>, document.body);
}
