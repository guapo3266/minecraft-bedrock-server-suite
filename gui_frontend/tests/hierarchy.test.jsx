import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { LanguageProvider, STRINGS } from '../src/i18n.jsx';
import ControlsBar from '../src/components/ControlsBar.jsx';
import HardwareMeter from '../src/components/HardwareMeter.jsx';

const render = element => renderToStaticMarkup(<LanguageProvider>{element}</LanguageProvider>);
const buttons = html => html.match(/<button\b[^>]*>[\s\S]*?<\/button>/g) || [];
const action = (html, text) => buttons(html).find(button => button.includes(text));
const hardware = {
  ram_mb: 428.5, cpu_pct: 7.2, total_ram_gb: 16, system_available_gb: 10.4,
  disk_free_gb: 210.2, disk_total_gb: 930, disk_used_pct: 77.4
};

describe('jerarquía de acciones sin alterar disponibilidad', () => {
  it('Iniciar es la única acción fuerte cuando está apagado', () => {
    const html = render(<ControlsBar status={{ running: false }} onAction={() => {}} />);
    expect(action(html, STRINGS.es.start)).toContain('strong-primary');
    expect(action(html, STRINGS.es.start)).not.toContain('disabled');
    expect(action(html, STRINGS.es.stop)).toContain('disabled');
    expect(action(html, STRINGS.es.restart)).toContain('disabled');
    expect(action(html, STRINGS.es.backup)).not.toContain('disabled');
  });
  it('encendido: Iniciar queda deshabilitado, sin llamada de atención primaria', () => {
    const html = render(<ControlsBar status={{ running: true, player_count: 2 }} onAction={() => {}} />);
    expect(action(html, STRINGS.es.start)).toContain('disabled');
    expect(html).not.toContain('strong-primary');
    expect(action(html, STRINGS.es.stop)).not.toContain('disabled');
    expect(action(html, STRINGS.es.restart)).not.toContain('disabled');
    expect(html).toContain('2 jugadores conectados');
  });
  it('un backup en curso sigue bloqueando otro envío de backup', () => {
    const html = render(<ControlsBar status={{ running: true, backup_in_progress: true }} onAction={() => {}} />);
    expect(action(html, STRINGS.es.backup)).toContain('disabled');
  });
  it('la franja compacta conserva título semántico y contexto de arranque', () => {
    const html = render(<ControlsBar status={{ running: false }} onAction={() => {}} />);
    expect(html).toContain('<h1>Servidor</h1>');
    expect(html).toContain(STRINGS.es.startServerHint);
  });
});

describe('recursos compactos sin perder datos ni historial', () => {
  it('mantiene RAM, CPU, disco y versión', () => {
    const html = render(<HardwareMeter hardware={hardware} running version="1.21.100.6" />);
    for (const label of [STRINGS.es.ram, STRINGS.es.cpu, STRINGS.es.disk, STRINGS.es.bdsVersion]) expect(html).toContain(label);
    for (const number of ['428.5', '7.2', '210.2', '930', '10.4', '1.21.100.6']) expect(html).toContain(number);
  });
  it('conserva los rangos 1/6/24 h y el rango inicial seleccionado', () => {
    const html = render(<HardwareMeter hardware={hardware} running />);
    for (const hours of [1, 6, 24]) expect(html).toContain(`${hours}h`);
    expect(action(html, '24h')).toContain('aria-pressed="true"');
  });
  it('no representa CPU ni RAM en uso con el servidor apagado', () => {
    const html = render(<HardwareMeter hardware={hardware} running={false} />);
    const values = [...html.matchAll(/class="metric-value">([\s\S]*?)<\/strong>/g)]
      .map(match => match[1].replace(/<[^>]*>/g, ''));
    expect(values).toEqual([STRINGS.es.off, '0.0%', '210.2']);
  });
  it('no oculta la advertencia de disco bajo al compactar', () => {
    const html = render(<HardwareMeter hardware={{ ...hardware, disk_free_gb: 1.2 }} running />);
    expect(html).toContain('metric-warning');
    expect(html).toContain(STRINGS.es.diskLow);
  });
});
