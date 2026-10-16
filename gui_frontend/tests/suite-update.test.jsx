import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { LanguageProvider, STRINGS } from '../src/i18n.jsx';
import SuiteUpdateModal from '../src/components/SuiteUpdateModal.jsx';
import ControlsBar from '../src/components/ControlsBar.jsx';
import { ACTIVE_PHASES, FINAL_PHASES, PHASE_KEYS } from '../src/suiteUpdateLogic';

vi.mock('../src/components/Modal', () => ({ default: ({ children }) => <section>{children}</section> }));
const render = element => renderToStaticMarkup(<LanguageProvider>{element}</LanguageProvider>);
const update = info => ({ info, progress: { phase: 'idle' }, setOpen: () => {}, check: () => {}, install: () => {} });

describe('actualizador de la suite', () => {
  it('distingue falta de Release de una suite actualizada', () => {
    const html = render(<SuiteUpdateModal update={update({ state: 'no_release', has_update: false })} />);
    expect(html).toContain(STRINGS.es.suiteNoRelease);
    expect(html).not.toContain(STRINGS.es.suiteUpToDate);
  });
  it('no permite instalar sobre un checkout Git', () => {
    const html = render(<SuiteUpdateModal update={update({ state: 'available', has_update: true, latest_version: '2.2.0', install_block: 'git_checkout' })} />);
    expect(html).toContain(STRINGS.es.suiteGitCheckout);
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Preparar actualización<\/button>/);
  });
  it('una consulta fallida no se presenta como estar al día', () => {
    const html = render(<SuiteUpdateModal update={update({ state: 'unavailable', has_update: null })} />);
    expect(html).toContain(STRINGS.es.suiteCheckUnavailable);
    expect(html).not.toContain(STRINGS.es.suiteUpToDate);
  });
  it('todas las fases tienen traducción ES/EN y finales separados de las fases activas', () => {
    for (const phase of [...ACTIVE_PHASES, ...FINAL_PHASES]) {
      expect(STRINGS.es[PHASE_KEYS[phase]]).toBeTruthy();
      expect(STRINGS.en[PHASE_KEYS[phase]]).toBeTruthy();
    }
    expect([...ACTIVE_PHASES].filter(phase => FINAL_PHASES.has(phase))).toEqual([]);
  });
  it('bloquea los cuatro controles mientras se actualiza la suite', () => {
    for (const running of [false, true]) {
      const html = render(<ControlsBar status={{ running, suite_update_in_progress: true }} onAction={() => {}} />);
      const buttons = html.match(/<button\b[^>]*>/g);
      expect(buttons).toHaveLength(4);
      expect(buttons.every(button => button.includes('disabled=""'))).toBe(true);
    }
  });
  it('informa el fallo de reinicio de Minecraft sin ocultarlo tras éxito completo', () => {
    const value = { ...update({ state: 'available' }), progress: { phase: 'restart_failed' } };
    const html = render(<SuiteUpdateModal update={value} />);
    expect(html).toContain(STRINGS.es.suitePhaseRestartFailed);
    expect(html).not.toContain(STRINGS.es.suitePhaseComplete);
  });
});
