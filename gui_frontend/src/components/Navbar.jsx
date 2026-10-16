import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Settings, CalendarClock, Download, Server, Palette, Ellipsis, Info } from 'lucide-react';
import { useI18n } from '../i18n.jsx';
import ServerStatus from './ServerStatus';
import useActionMenu from '../hooks/useActionMenu';
import AppearanceTip from './AppearanceTip';

const APPEARANCE_TIP_KEY = 'bedrock-appearance-tip-seen';

// Configuración y personalización visibles; las herramientas quedan en el menú.
export default function Navbar({ status, onOpenUpdate, onOpenProps, onOpenSchedule, onOpenSuiteUpdate = () => {}, suiteUpdateAvailable = false, latency = null,
  headerRef, onOpenAppearance, onOpenAbout, showServerActions = true, appearanceTipEnabled = false, connectionState = 'connecting' }) {
  const { t, lang, setLang } = useI18n();
  const [menuOpen, setMenuOpen] = useState(false);
  const [menuRect, setMenuRect] = useState(null);
  const appearanceRef = useRef(null);
  const [tipDismissed, setTipDismissed] = useState(() => {
    try { return localStorage.getItem(APPEARANCE_TIP_KEY) === '1'; }
    catch { return false; }
  });
  const showTip = appearanceTipEnabled && !tipDismissed && !menuOpen;
  useEffect(() => {
    if (showTip) {
      try { localStorage.setItem(APPEARANCE_TIP_KEY, '1'); }
      catch { /* El consejo sigue siendo descartable en esta sesión. */ }
    }
  }, [showTip]);
  const dismissTip = () => {
    setTipDismissed(true);
    try { localStorage.setItem(APPEARANCE_TIP_KEY, '1'); }
    catch { /* No bloquear personalización si el almacenamiento está deshabilitado. */ }
  };
  const customize = () => {
    appearanceRef.current?.focus({ preventScroll: true });
    dismissTip();
    onOpenAppearance();
  };

  const hideMenu = () => {
    setMenuOpen(false);
    setMenuRect(null);
  };
  const { menuRef, triggerRef: menuTriggerRef, closeMenu } = useActionMenu(menuOpen, hideMenu);

  const toggleMenu = (e) => {
    if (menuOpen) {
      closeMenu();
      return;
    }
    const rect = e.currentTarget.getBoundingClientRect();
    const w = 264;
    const h = showServerActions ? 232 : 96;
    setMenuRect({
      top: Math.max(8, Math.min(rect.bottom + 4, window.innerHeight - h - 8)),
      left: Math.max(8, Math.min(rect.right - w, window.innerWidth - w - 8))
    });
    setMenuOpen(true);
  };

  const menuActions = [
    ...(showServerActions ? [
      { id: 'schedule', group: 'serverTools', label: t('schedMenu'), icon: <CalendarClock size={16} aria-hidden="true" />, onClick: onOpenSchedule },
      { id: 'update', group: 'serverTools', label: t('updateBds'), icon: <Download size={16} aria-hidden="true" />, onClick: onOpenUpdate }
    ] : []),
    { id: 'suiteUpdate', group: 'interfaceSettings', label: t('suiteUpdateTitle'), icon: <Download size={16} aria-hidden="true" />, onClick: onOpenSuiteUpdate },
    { id: 'about', group: 'interfaceSettings', label: t('aboutTitle'), icon: <Info size={16} aria-hidden="true" />, onClick: onOpenAbout }
  ];

  const runMenuAction = (action) => {
    closeMenu(true);
    action.onClick();
  };

  return (
    <header className="app-header glass-shell" ref={headerRef}>
      <div className="brand"><span className="brand-icon"><Server size={24} aria-hidden="true" /></span>
        <div><strong>Bedrock Suite<span className="brand-dot">.</span></strong><span>{t('brandTagline')}</span></div>
      </div>
      <div className="header-controls">
        {showServerActions && <ServerStatus status={status} connectionState={connectionState} latency={latency} />}
        <div className="segments language-switch" role="group" aria-label={t('setupLangLabel')}>
          {['es', 'en'].map(code => <button type="button" key={code} onClick={() => setLang(code)}
            aria-pressed={lang === code} className={lang === code ? 'selected' : ''}>{code.toUpperCase()}</button>)}
        </div>
        <button ref={appearanceRef} type="button" className="button appearance-button" onClick={customize}
          aria-label={t('appearanceCustomize')} title={t('appearanceTitle')}
          aria-describedby={showTip ? 'appearance-tip-body' : undefined}>
          <Palette size={18} aria-hidden="true" />
          <span className="appearance-label">{t('appearanceCustomize')}</span>
          <span className="appearance-label-short" aria-hidden="true">{t('appearanceCustomizeShort')}</span>
        </button>
        {showServerActions && <button type="button" className="button settings-button" onClick={onOpenProps} aria-label={t('settings')}>
          <Settings size={17} aria-hidden="true" /><span>{t('settings')}</span>
        </button>}
        <button ref={menuTriggerRef} type="button" onClick={toggleMenu} data-nav-menu-trigger="true"
          aria-haspopup="menu" aria-expanded={menuOpen} aria-controls={menuOpen ? 'nav-actions-menu' : undefined}
          aria-label={t('moreActions')} title={t('moreActions')} className="button icon-button nav-more">
          <Ellipsis size={20} aria-hidden="true" />
          {suiteUpdateAvailable && <span className="suite-update-dot" title={t('suiteUpdateBadge')} aria-hidden="true" />}
        </button>
      </div>
      {showTip && <AppearanceTip anchorRef={appearanceRef} onDismiss={dismissTip} onCustomize={customize} />}

      {/* Desplegable de acciones secundarias (portal: mismo patron que el menu
          de comandos rapidos y el de backups, fuera del stacking del header) */}
      {createPortal(
        <AnimatePresence>
          {menuOpen && menuRect && (
            <motion.div
              ref={menuRef}
              initial={{ opacity: 0, scale: 0.95, y: -4 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: -4 }}
              transition={{ duration: 0.12 }}
              style={{
                position: 'fixed',
                top: menuRect.top,
                left: menuRect.left,
                maxHeight: `calc(100dvh - ${menuRect.top + 8}px)`,
                zIndex: 60
              }}
              className="glass-menu nav-menu"
              id="nav-actions-menu" role="menu" aria-label={t('moreActions')}
            >
              {menuActions.map((action, index) => <React.Fragment key={action.id}>
                {(index === 0 || action.group !== menuActions[index - 1].group) &&
                  <div className="menu-heading" role="presentation">{t(action.group)}</div>}
                <button
                  role="menuitem"
                  tabIndex={-1}
                  onClick={() => runMenuAction(action)}
                  className="menu-action"
                >
                  {action.icon}
                  <span>{action.label}</span>
                  {action.id === 'suiteUpdate' && suiteUpdateAvailable && <span className="menu-badge">{t('suiteUpdateBadge')}</span>}
                </button>
              </React.Fragment>)}
            </motion.div>
          )}
        </AnimatePresence>,
        document.body
      )}
    </header>
  );
}
