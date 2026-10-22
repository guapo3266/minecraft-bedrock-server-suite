// Tests de la logica pura de la pestaña de addons (sin jsdom). El fixture es
// el MISMO que usa el test de Python (tests/fixtures/addons_payload.json): si
// el filtro de la GUI y el de la CLI divergieran, uno de los dos tests falla.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import {
  CLAVES_RESOLUCION,
  KINDS,
  agruparPorAmbito,
  contarSeveridad,
  filtrarInventario,
  resolucionDe,
  textoVersion
} from '../src/addonsLogic.js';

const RAIZ = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const payload = JSON.parse(readFileSync(join(RAIZ, 'tests', 'fixtures', 'addons_payload.json'), 'utf8'));

const ids = (p) => p.packs.map((x) => x.id);
const codigos = (p) => p.diagnostics.map((d) => d.code);

describe('filtrarInventario (espejo de addon_inventory.filter_payload)', () => {
  it('sin filtros devuelve el payload intacto', () => {
    expect(filtrarInventario(payload, {})).toBe(payload);
    expect(filtrarInventario(payload, { world: '', kind: '' })).toBe(payload);
  });

  it('filtra por mundo: propios + compartidos + sistema, y solo ese mundo', () => {
    const vista = filtrarInventario(payload, { world: 'Alfa' });
    expect(ids(vista)).toEqual([
      'behavior_packs/CompartidoBP',
      'system_behavior_packs/SysBP',
      'worlds/Alfa/behavior_packs/AlfaBP',
      'resource_packs/CompartidoRes'
    ]);
    expect(vista.worlds.map((w) => w.name)).toEqual(['Alfa']);
    expect(codigos(vista)).toEqual(['UNO', 'TRES', 'CUATRO']);
    expect(vista.filter).toEqual({ world: 'Alfa', kind: null });
  });

  it('filtra por tipo conservando todos los ambitos de ese tipo', () => {
    const vista = filtrarInventario(payload, { kind: 'behavior' });
    expect(ids(vista)).toEqual([
      'behavior_packs/CompartidoBP',
      'system_behavior_packs/SysBP',
      'worlds/Alfa/behavior_packs/AlfaBP',
      'worlds/Beta/behavior_packs/BetaBP'
    ]);
    expect(vista.worlds.map((w) => w.name)).toEqual(['Alfa', 'Beta']);
    expect(codigos(vista)).toEqual(['UNO', 'DOS', 'TRES', 'CUATRO']);
  });

  it('combina mundo y tipo y descarta diagnosticos de packs no conservados', () => {
    const vista = filtrarInventario(payload, { world: 'Beta', kind: 'resource' });
    expect(ids(vista)).toEqual(['resource_packs/CompartidoRes']);
    expect(vista.worlds.map((w) => w.name)).toEqual(['Beta']);
    // DOS es de un pack de Beta no conservado (tipo behavior) y UNO/CUATRO son
    // de ambitos fuera del filtro: solo queda el diagnostico global TRES.
    expect(codigos(vista)).toEqual(['TRES']);
    expect(vista.filter).toEqual({ world: 'Beta', kind: 'resource' });
  });

  it('un tipo desconocido no filtra nada (no rompe la vista)', () => {
    const vista = filtrarInventario(payload, { kind: 'inexistente' });
    expect(ids(vista)).toEqual(ids(payload));
  });

  it('recalcula el resumen de la vista y conserva el de la instalacion', () => {
    // Espejo de addon_inventory.filter_payload: sin esto el panel seguia
    // diciendo "13 packs / 3 mundos" con la lista ya filtrada.
    const vista = filtrarInventario(payload, { world: 'Alfa' });
    expect(vista.summary).toMatchObject({
      packs_total: 4,
      packs_compartidos: 2,
      packs_de_sistema: 1,
      packs_de_mundo: 1,
      mundos_total: 1,
      diagnosticos_total: 3,
      errores: 1,
      avisos: 1,
      informativos: 1
    });
    // Campos que describen la INSTALACION: no se recalculan.
    expect(vista.summary.complete).toBe(payload.summary.complete);
    expect(vista.summary.packs_sin_analizar).toBe(payload.summary.packs_sin_analizar);
    expect(vista.summary_installation).toBe(payload.summary);
    expect(payload.summary.packs_total).toBe(5);

    // Mismos numeros que el test de Python con el mismo fixture
    // (test_filter_payload_mundo_y_tipo_descarta_diagnosticos_ajenos).
    const acotada = filtrarInventario(payload, { world: 'Beta', kind: 'resource' });
    expect(acotada.summary.packs_total).toBe(1);
    expect(acotada.summary.diagnosticos_total).toBe(1);

    const porTipo = filtrarInventario(payload, { kind: 'behavior' });
    expect(porTipo.summary.packs_total).toBe(4);
    expect(porTipo.summary.packs_resource).toBe(0);
    expect(porTipo.summary.mundos_total).toBe(2);
  });

  it('cuenta las referencias de mundo por estado en el resumen', () => {
    const base = {
      ...payload,
      worlds: [{
        name: 'Alfa',
        references: [
          { status: 'resolved' }, { status: 'unresolved' }, { status: 'ambiguous' },
          { status: 'kind_mismatch' }, { status: 'version_unavailable' }
        ]
      }]
    };
    const vista = filtrarInventario(base, { world: 'Alfa' });
    expect(vista.summary).toMatchObject({
      referencias_total: 5,
      referencias_resueltas: 1,
      referencias_sin_resolver: 1,
      referencias_ambiguas: 1,
      referencias_tipo_cruzado: 1,
      referencias_sin_version: 1
    });
  });

  it('expone los tipos soportados y no muta el payload original', () => {
    expect(KINDS).toEqual(['behavior', 'resource']);
    const antes = JSON.stringify(payload);
    filtrarInventario(payload, { world: 'Alfa', kind: 'behavior' });
    expect(JSON.stringify(payload)).toBe(antes);
  });
});

describe('contarSeveridad y agruparPorAmbito', () => {
  it('cuenta por gravedad con total', () => {
    expect(contarSeveridad(payload.diagnostics)).toEqual({ error: 1, aviso: 2, info: 1, total: 4 });
    expect(contarSeveridad([])).toEqual({ error: 0, aviso: 0, info: 0, total: 0 });
  });

  it('agrupa respetando el orden de scopes y sin ambitos vacios', () => {
    const grupos = agruparPorAmbito(payload);
    expect(grupos.map((g) => g.scope.id)).toEqual([
      'compartido:behavior',
      'compartido:resource',
      'sistema:behavior',
      'mundo:Alfa:behavior',
      'mundo:Beta:behavior'
    ]);
    expect(grupos[0].packs.map((p) => p.id)).toEqual(['behavior_packs/CompartidoBP']);
    expect(agruparPorAmbito(null)).toEqual([]);
  });

  it('textoVersion pinta vectores, texto y ausencia', () => {
    expect(textoVersion([3, 2, 0])).toBe('[3, 2, 0]');
    expect(textoVersion('2.9.0-beta')).toBe('2.9.0-beta');
    expect(textoVersion(null)).toBe('—');
  });
});

describe('resolucionDe (estado de UNA dependencia de pack)', () => {
  const pack = {
    dependency_resolution: [
      { uuid: 'aaa', version: [1, 0, 0], status: 'resolved' },
      { uuid: 'aaa', version: [9, 9, 9], status: 'version_mismatch' },
      { uuid: 'bbb', version: null, status: 'unchecked' }
    ]
  };

  it('empareja por uuid Y version, no solo por uuid', () => {
    // Regresion: buscar solo por uuid devolvia "resuelta" para la dependencia
    // de la misma UUID con OTRA version (la GUI mentia sobre ese enlace).
    expect(resolucionDe(pack, { uuid: 'aaa', version: [1, 0, 0] }).status).toBe('resolved');
    expect(resolucionDe(pack, { uuid: 'aaa', version: [9, 9, 9] }).status).toBe('version_mismatch');
  });

  it('empareja la ausencia de version (null) y devuelve null si no hay entrada', () => {
    expect(resolucionDe(pack, { uuid: 'bbb', version: null }).status).toBe('unchecked');
    expect(resolucionDe(pack, { uuid: 'aaa', version: [2, 0, 0] })).toBe(null);
    expect(resolucionDe(pack, { uuid: 'zzz', version: [1, 0, 0] })).toBe(null);
    expect(resolucionDe({}, { uuid: 'aaa', version: [1, 0, 0] })).toBe(null);
    expect(resolucionDe(null, { uuid: 'aaa', version: [1, 0, 0] })).toBe(null);
  });

  it('la clave i18n cubre todos los estados que emite el analizador', () => {
    // Espejo de addon_inventory: un estado sin clave se pintaria como
    // "pendiente", que es una afirmacion falsa sobre el enlace.
    expect(Object.keys(CLAVES_RESOLUCION).sort()).toEqual([
      'ambiguous', 'context_dependent', 'invalid', 'kind_mismatch', 'missing', 'other_kind',
      'pending', 'resolved', 'unchecked', 'unresolved', 'version_mismatch',
      'version_missing', 'version_unavailable'
    ]);
    for (const clave of Object.values(CLAVES_RESOLUCION)) {
      expect(clave).toMatch(/^addonsRef/);
    }
  });
});


describe('regresiones de filtros y dependencias por mundo', () => {
  it.each(['behavior', 'resource'])('no deduce el tipo del nombre del mundo %s', (nombre) => {
    const instalado = {
      ...payload,
      worlds: [{ ...payload.worlds[0], name: nombre }],
      diagnostics: [{ ...payload.diagnostics[3], scope: `mundo:${nombre}`, world: nombre, pack: null }]
    };
    const vista = filtrarInventario(instalado, { world: nombre, kind: nombre === 'behavior' ? 'resource' : 'behavior' });
    expect(vista.diagnostics).toHaveLength(1);
  });

  const base = {
    ...payload,
    worlds: [{
      ...payload.worlds[0],
      references: [{ kind: 'behavior', status: 'unresolved' }, { kind: 'resource', status: 'resolved' }],
      ref_files: [{ kind: 'behavior' }, { kind: 'resource' }]
    }],
    diagnostics: [{ ...payload.diagnostics[3], code: 'BP_AUSENTE', scope: 'behavior', pack: null }]
  };

  it.each(['', 'Alfa'])('filtra referencias y errores del otro tipo (mundo %s)', (world) => {
    const antes = JSON.stringify(base);
    const vista = filtrarInventario(base, { world, kind: 'resource' });
    expect(vista.worlds[0].references).toEqual([{ kind: 'resource', status: 'resolved' }]);
    expect(vista.worlds[0].ref_files).toEqual([{ kind: 'resource' }]);
    expect(vista.diagnostics).toEqual([]);
    expect(vista.summary.referencias_resueltas).toBe(1);
    expect(vista.summary.referencias_total).toBe(1);
    expect(JSON.stringify(base)).toBe(antes);
  });

  it('elige la resolucion del mundo y no filtra errores de otro mundo como globales', () => {
    const porMundo = [
      { world: 'Alfa', status: 'resolved', candidates: [] },
      { world: 'Beta', status: 'missing', candidates: [] }
    ];
    const instalado = {
      ...payload,
      packs: [{ ...payload.packs[0], dependency_resolution: [{
        uuid: 'dep', version: [1, 0, 0], status: 'context_dependent', candidates: [], world_resolutions: porMundo
      }] }],
      diagnostics: [{ ...payload.diagnostics[0], world: 'Beta' }]
    };
    const antes = JSON.stringify(instalado);
    const alfa = filtrarInventario(instalado, { world: 'Alfa' });
    expect(alfa.packs[0].dependency_resolution[0].status).toBe('resolved');
    expect(alfa.packs[0].dependency_resolution[0].world_resolutions).toEqual([porMundo[0]]);
    expect(alfa.diagnostics).toEqual([]);
    expect(filtrarInventario(instalado, { world: 'Beta' }).packs[0].dependency_resolution[0].status).toBe('missing');
    expect(CLAVES_RESOLUCION.context_dependent).toBe('addonsRefContextDependent');
    expect(JSON.stringify(instalado)).toBe(antes);
    const soloBeta = {
      ...instalado,
      packs: [{ ...instalado.packs[0], dependency_resolution: [{
        ...instalado.packs[0].dependency_resolution[0], status: 'missing', world_resolutions: [porMundo[1]]
      }] }]
    };
    const noEvaluada = filtrarInventario(soloBeta, { world: 'Alfa' });
    expect(noEvaluada.packs[0].dependency_resolution[0].status).toBe('unchecked');
    expect(noEvaluada.packs[0].dependency_resolution[0].world_resolutions).toEqual([]);
  });
});

// Fixture generado con el analizador real (tests/fixtures/addons_tipo_cruzado.json,
// compartido con tests/test_revision_2026-10-21.py): un pack de comportamiento
// listado en world_resource_packs.json.
const tipoCruzado = JSON.parse(readFileSync(join(RAIZ, 'tests', 'fixtures', 'addons_tipo_cruzado.json'), 'utf8'));

describe('diagnostico de referencia de tipo cruzado (2026-10-21)', () => {
  it('filtrando por el tipo del archivo de referencias se ve junto a su referencia', () => {
    const vista = filtrarInventario(tipoCruzado, { kind: 'resource' });
    expect(ids(vista)).toEqual(['resource_packs/RP']);
    expect(codigos(vista)).toEqual(['WORLD_REF_KIND_MISMATCH', 'SCOPE_ROOT_MISSING']);
    expect(vista.worlds[0].references.map((r) => r.status)).toEqual(['kind_mismatch', 'resolved']);
    expect(codigos(filtrarInventario(tipoCruzado, { world: 'Alfa', kind: 'resource' })))
      .toEqual(['WORLD_REF_KIND_MISMATCH', 'SCOPE_ROOT_MISSING']);
  });

  it('filtrando por el tipo del pack no aparece (la referencia tampoco)', () => {
    const vista = filtrarInventario(tipoCruzado, { kind: 'behavior' });
    expect(ids(vista)).toEqual(['behavior_packs/BP']);
    expect(codigos(vista)).toEqual(['SCOPE_ROOT_MISSING']);
    expect(vista.worlds[0].references).toEqual([]);
  });
});
