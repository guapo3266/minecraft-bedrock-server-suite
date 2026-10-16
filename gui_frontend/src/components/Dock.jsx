import { useI18n } from '../i18n.jsx';
import { SECTIONS } from '../navigation.js';

export default function Dock({ active, onChange, dockRef, hidden, players, backups }) {
  const { t } = useI18n();
  const change = id => { onChange(id); document.querySelector('.main-content')?.scrollTo({ top: 0 }); };
  const keydown = event => {
    const index = SECTIONS.findIndex(section => section.id === active);
    const offset = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
    const next = offset ? SECTIONS[(index + offset + SECTIONS.length) % SECTIONS.length]
      : event.key === 'Home' ? SECTIONS[0] : event.key === 'End' ? SECTIONS.at(-1) : null;
    if (next) { event.preventDefault(); change(next.id); document.getElementById(`${next.id}-tab`)?.focus(); }
  };
  return <nav className="dock glass-shell" ref={dockRef} role="tablist" aria-label={t('sections')} onKeyDown={keydown} hidden={hidden}>
    {SECTIONS.map(({ id, label, icon: Icon }) => <button type="button" key={id} id={`${id}-tab`} role="tab"
      aria-label={t(label)} aria-selected={active === id} aria-controls={`${id}-panel`} tabIndex={active === id ? 0 : -1}
      className={active === id ? 'selected' : ''} onClick={() => change(id)}>
      <Icon size={19} aria-hidden="true" /><span>{t(label)}</span>
      {((id === 'players' && players > 0) || (id === 'backups' && backups > 0)) &&
        <span className="dock-count">{id === 'players' ? players : backups}</span>}
    </button>)}
  </nav>;
}
