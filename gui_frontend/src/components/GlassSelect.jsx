import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Check, ChevronDown } from 'lucide-react';

// Selector de vidrio del proyecto de referencia: el foco permanece en el
// combobox, con opciones en portal y navegación por teclado/typeahead.
export default function GlassSelect({ options, value, onChange, label, id, disabled = false, className = '' }) {
  const uid = useId(), trigger = useRef(null), menu = useRef(null);
  const search = useRef({ text: '', time: 0 });
  const [open, setOpen] = useState(false), [active, setActive] = useState(0), [position, setPosition] = useState({});
  const selected = options.findIndex(option => option.id === value);
  const expanded = open && !disabled;
  const close = useCallback(() => setOpen(false), []);
  const measure = useCallback(() => {
    const rect = trigger.current.getBoundingClientRect();
    const width = Math.min(Math.max(rect.width, 240), window.innerWidth - 24);
    const below = window.innerHeight - rect.bottom - 20, above = rect.top - 20;
    const up = below < 180 && above > below;
    setPosition({ width, left: Math.max(12, Math.min(rect.left, window.innerWidth - width - 12)),
      maxHeight: Math.max(40, Math.min(320, up ? above : below)),
      ...(up ? { bottom: window.innerHeight - rect.top + 8 } : { top: rect.bottom + 8 }) });
  }, []);
  const show = (index = Math.max(0, selected)) => {
    if (disabled) return;
    measure(); setActive(index); search.current = { text: '', time: 0 }; setOpen(true);
  };
  const choose = index => {
    if (disabled || !options[index]) return;
    close(); onChange(options[index].id); trigger.current.focus();
  };
  useEffect(() => {
    if (!expanded) return;
    const dialog = trigger.current.closest('[role="dialog"]');
    dialog?.setAttribute('aria-owns', `${uid}-list`);
    const outside = event => { if (!trigger.current.contains(event.target) && !menu.current?.contains(event.target)) close(); };
    const observer = new ResizeObserver(measure);
    observer.observe(trigger.current);
    window.addEventListener('resize', measure);
    window.addEventListener('scroll', measure, true);
    document.addEventListener('pointerdown', outside);
    return () => {
      dialog?.removeAttribute('aria-owns'); observer.disconnect();
      window.removeEventListener('resize', measure); window.removeEventListener('scroll', measure, true);
      document.removeEventListener('pointerdown', outside);
    };
  }, [expanded, measure, close, uid]);
  useEffect(() => {
    if (expanded) document.getElementById(`${uid}-option-${active}`)?.scrollIntoView({ block: 'nearest' });
  }, [expanded, active, uid]);
  const keydown = event => {
    if (event.key === 'Tab') { close(); return; }
    if (event.key === 'Escape') {
      if (expanded) { event.preventDefault(); event.stopPropagation(); close(); }
      return;
    }
    if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      const index = event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1
        : expanded ? Math.max(0, Math.min(options.length - 1, active + (event.key === 'ArrowDown' ? 1 : -1))) : Math.max(0, selected);
      if (expanded) setActive(index); else show(index);
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault(); if (expanded) choose(active); else show();
    } else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
      const now = Date.now(), character = event.key.toLocaleLowerCase();
      const text = now - search.current.time > 600 ? character : search.current.text + character;
      const index = options.findIndex(option => option.label.toLocaleLowerCase().startsWith(text));
      if (index >= 0) { event.preventDefault(); if (expanded) setActive(index); else show(index); }
      search.current = { text, time: now };
    }
  };
  return <>
    <button ref={trigger} id={id} type="button" className={`button glass-select ${className}`} role="combobox"
      aria-label={label} aria-haspopup="listbox" aria-expanded={expanded}
      aria-controls={expanded ? `${uid}-list` : undefined}
      aria-activedescendant={expanded ? `${uid}-option-${active}` : undefined}
      disabled={disabled} onKeyDown={keydown} onBlur={close} onClick={() => expanded ? close() : show()}>
      <span>{options[selected]?.label || '—'}</span><ChevronDown size={16} aria-hidden="true" />
    </button>
    {expanded && createPortal(<div ref={menu} id={`${uid}-list`} className="glass-menu select-menu" role="listbox" aria-label={label} style={position}>
      {options.map((option, index) => <button type="button" key={option.id} id={`${uid}-option-${index}`} role="option" tabIndex={-1}
        aria-selected={option.id === value} className={index === active ? 'active' : ''}
        onPointerDown={event => event.preventDefault()} onPointerMove={() => setActive(index)} onClick={() => choose(index)}>
        <span>{option.label}</span>{option.id === value && <Check size={16} aria-hidden="true" />}
      </button>)}
    </div>, document.body)}
  </>;
}
