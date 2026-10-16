import { useCallback, useEffect, useRef } from 'react';

// Menús en portal: el Tab nativo no parte del botón que los abrió. Se comparte
// el mismo ciclo de foco/cierre entre cabecera, comandos rápidos y backups.
export default function useActionMenu(open, onClose) {
  const menuRef = useRef(null), triggerRef = useRef(null), closeRef = useRef(onClose);
  closeRef.current = onClose;
  const closeMenu = useCallback((restoreFocus = false) => {
    if (restoreFocus && triggerRef.current?.isConnected) triggerRef.current.focus({ preventScroll: true });
    closeRef.current();
  }, []);

  useEffect(() => {
    if (!open || !menuRef.current) return;
    const menu = menuRef.current, trigger = triggerRef.current;
    const anchor = trigger?.getBoundingClientRect();
    const inside = (element, target) => target instanceof Node && element?.contains(target);
    const items = () => [...menu.querySelectorAll('[role="menuitem"]')]
      .filter(item => !item.disabled && item.getAttribute('aria-disabled') !== 'true' && item.getClientRects().length);
    const outside = event => {
      if (!inside(menu, event.target) && !inside(trigger, event.target)) closeMenu();
    };
    const onKey = event => {
      if (event.defaultPrevented || (!inside(menu, event.target) && !inside(trigger, event.target))) return;
      if (event.key === 'Escape') {
        event.preventDefault(); event.stopPropagation(); closeMenu(true);
      } else if (event.key === 'Tab') {
        // Tab/Shift+Tab continúan desde el trigger, no desde las opciones
        // que están al final de body por el portal.
        closeMenu(true);
      } else if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
        event.preventDefault();
        const options = items();
        if (!options.length) return;
        const current = options.indexOf(document.activeElement);
        const index = event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1
          : current < 0 ? (event.key === 'ArrowUp' ? options.length - 1 : 0)
            : (current + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length;
        options[index].focus({ preventScroll: true });
        options[index].scrollIntoView({ block: 'nearest' });
      }
    };
    const onScroll = event => {
      if (inside(menu, event.target)) return;
      const rect = trigger?.getBoundingClientRect();
      // El scroll que acaba de revelar el botón puede notificarse DESPUÉS
      // de abrir el menú; lo mismo pasa con el autoscroll de logs. Cerrar
      // solo si el ancla se movió, no por una notificación pendiente.
      const moved = anchor && rect && ['top', 'left', 'width', 'height']
        .some(key => Math.abs(rect[key] - anchor[key]) > .5);
      if (!trigger?.isConnected || moved) closeMenu(menu.contains(document.activeElement));
    };
    const onResize = () => closeMenu(menu.contains(document.activeElement));
    document.addEventListener('pointerdown', outside);
    document.addEventListener('focusin', outside);
    document.addEventListener('keydown', onKey);
    window.addEventListener('scroll', onScroll, true);
    window.addEventListener('resize', onResize);
    items()[0]?.focus({ preventScroll: true });
    return () => {
      document.removeEventListener('pointerdown', outside);
      document.removeEventListener('focusin', outside);
      document.removeEventListener('keydown', onKey);
      window.removeEventListener('scroll', onScroll, true);
      window.removeEventListener('resize', onResize);
    };
  }, [open, closeMenu]);

  return { menuRef, triggerRef, closeMenu };
}
