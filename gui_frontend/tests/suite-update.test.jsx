import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { LanguageProvider, STRINGS } from '../src/i18n.jsx';
import SuiteUpdateModal from '../src/components/SuiteUpdateModal.jsx';
import ControlsBar from '../src/components/ControlsBar.jsx';
import { ACTIVE_PHASES, FINAL_PHASES, PHASE_KEYS, nextPollAction, startProgressPolling } from '../src/suiteUpdateLogic';

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

describe('sondeo del progreso de la actualización', () => {
  it('idle termina el sondeo: no hay ninguna actualización que esperar', () => {
    expect(nextPollAction({ phase: 'idle' }, '2.1.1')).toBe('finish');
  });
  it('las fases finales terminan y solo una entrega nueva recarga la página', () => {
    for (const phase of FINAL_PHASES) expect(nextPollAction({ phase }, '2.1.1')).toBe('finish');
    for (const phase of ['complete', 'restart_failed']) {
      expect(nextPollAction({ phase, version: '9.9.9' }, '2.1.1')).toBe('reload');
      expect(nextPollAction({ phase, version: '2.1.1' }, '2.1.1')).toBe('finish');
    }
    expect(nextPollAction({ phase: 'rolled_back', version: '9.9.9' }, '2.1.1')).toBe('finish');
  });
  it('las fases activas, la reconexión y lo desconocido siguen sondeando', () => {
    for (const phase of ACTIVE_PHASES) expect(nextPollAction({ phase }, '2.1.1')).toBe('continue');
    for (const value of [{ phase: 'fase_de_un_backend_nuevo' }, {}, null]) {
      expect(nextPollAction(value, '2.1.1')).toBe('continue');
    }
  });

  const flush = () => new Promise(resolve => setTimeout(resolve, 0));
  const poller = responses => {
    const pending = [];
    const calls = { progress: [], finish: 0, reload: 0 };
    const stop = startProgressPolling({
      bundleVersion: '2.1.1',
      fetchProgress: async () => {
        const next = responses.shift();
        if (next instanceof Error) throw next;
        return next;
      },
      onProgress: value => calls.progress.push(value.phase),
      onFinish: () => { calls.finish += 1; },
      onReload: () => { calls.reload += 1; },
      schedule: fn => pending.push(fn),
      cancel: () => {}
    });
    const runNext = async () => {
      pending.shift()();
      await flush();
    };
    return { calls, pending, runNext, stop };
  };

  it('una pestaña que recordaba una actualización deja de sondear con idle', async () => {
    const { calls, pending } = poller([{ phase: 'idle' }]);
    await flush();
    expect(calls.progress).toEqual(['idle']);
    expect(calls.finish).toBe(1);
    expect(pending).toHaveLength(0);
  });
  it('sigue sondeando durante el relevo y termina al completarse', async () => {
    const { calls, pending, runNext } = poller([
      { phase: 'downloading' }, new Error('GUI caída durante el relevo'), { phase: 'checking' },
      { phase: 'complete', version: '2.1.1' }
    ]);
    await flush();
    await runNext();
    await runNext();
    await runNext();
    expect(calls.progress).toEqual(['downloading', 'reconnecting', 'checking', 'complete']);
    expect(calls.finish).toBe(1);
    expect(calls.reload).toBe(0);
    expect(pending).toHaveLength(0);
  });
  it('recarga la página cuando la GUI nueva sirve otra versión', async () => {
    const { calls, pending } = poller([{ phase: 'complete', version: '9.9.9' }]);
    await flush();
    expect(calls.reload).toBe(1);
    expect(calls.finish).toBe(0);
    expect(pending).toHaveLength(0);
  });
  it('detenerlo descarta la respuesta pendiente', async () => {
    const { calls, pending, stop } = poller([{ phase: 'checking' }]);
    stop();
    await flush();
    expect(calls.progress).toEqual([]);
    expect(pending).toHaveLength(0);
  });
});
