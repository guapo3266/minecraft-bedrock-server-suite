import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { LanguageProvider, STRINGS } from '../src/i18n.jsx';
import ServerStatus from '../src/components/ServerStatus.jsx';

const status = { running: true, backup_in_progress: false, uptime: 3723 };
const render = props => renderToStaticMarkup(<LanguageProvider><ServerStatus status={status} latency={12} {...props} /></LanguageProvider>);

describe('estado confirmado del servidor vs. conexión de la GUI', () => {
  it('conectado conserva estado, uptime y latencia', () => {
    const html = render({ connectionState: 'connected' });
    expect(html).toContain(STRINGS.es.serverStatusOnline);
    expect(html).toContain('1h 02m 03s');
    expect(html).toContain('12 ms');
  });
  it('antes del primer init no afirma que BDS esté detenido', () => {
    const html = render({ status: { running: false } });
    expect(html).toContain(STRINGS.es.guiConnecting);
    expect(html).not.toContain(`>${STRINGS.es.serverStatusOffline}<`);
    expect(html).not.toContain('server-uptime');
    expect(html).not.toContain('server-latency');
  });
  it.each([
    { running: true, backup_in_progress: false, uptime: 3723 },
    { running: false, backup_in_progress: false },
    { running: true, backup_in_progress: true, uptime: 3723 }
  ])('desconectado oculta estado y métricas obsoletas: %j', lastStatus => {
    const html = render({ status: lastStatus, connectionState: 'reconnecting' });
    expect(html).toContain(STRINGS.es.guiReconnecting);
    expect(html).toContain(STRINGS.es.guiConnectionUnknown);
    for (const key of ['serverStatusOnline', 'serverStatusOffline', 'serverStatusBackup']) {
      expect(html).not.toContain(`>${STRINGS.es[key]}<`);
    }
    expect(html).not.toContain('server-uptime');
    expect(html).not.toContain('server-latency');
  });
  it('un estado conectado y detenido es distinto de una desconexión', () => {
    const html = render({ status: { running: false }, connectionState: 'connected' });
    expect(html).toContain(`>${STRINGS.es.serverStatusOffline}<`);
    expect(html).not.toContain(STRINGS.es.guiReconnecting);
    expect(html).not.toContain('server-latency');
  });
  it('mantiene el indicador de backup solo con datos confirmados', () => {
    const html = render({ status: { ...status, backup_in_progress: true }, connectionState: 'connected' });
    expect(html).toContain('status-badge backup');
    expect(html).toContain(STRINGS.es.serverStatusBackup);
  });
  it('no inventa una latencia si aún no hubo pong tras reconectar', () => {
    expect(render({ connectionState: 'connected', latency: null })).not.toContain('server-latency');
    expect(render({ connectionState: 'connected', latency: 0 })).toContain('0 ms');
  });
  it('no anuncia cada tick del uptime en el área live', () => {
    const html = render({ connectionState: 'connected' });
    const live = html.match(/role="status">([^<]*)<\/span>/)?.[1];
    expect(live).toBe(STRINGS.es.serverStatusOnline);
    expect(live).not.toContain('1h');
  });
});
