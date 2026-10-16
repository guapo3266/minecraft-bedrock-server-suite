// Logica pura del inventario de addons (sin React), para poder probarla con
// vitest sin jsdom. Es el ESPEJO de `addon_inventory.filter_payload` (Python):
// con los mismos filtros, la GUI muestra exactamente lo que muestra la CLI.

export const KINDS = ['behavior', 'resource'];
export const SEVERITIES = ['error', 'aviso', 'info'];

// Orden de gravedad para pintar y ordenar (el analizador ya los envia
// ordenados; esto es defensa ante datos reordenados en el cliente).
export const ORDEN_SEVERIDAD = { error: 0, aviso: 1, info: 2 };

// Estado de resolucion -> clave i18n (dependencias de pack y referencias de
// mundo). Debe cubrir TODO estado que emita el analizador
// (addon_inventory._Analisis.resolver_dependencias / resolver_referencias): un
// estado sin clave se pintaria como "pendiente" en vez de decir la verdad.
export const CLAVES_RESOLUCION = {
  resolved: 'addonsRefResolved',
  unresolved: 'addonsRefUnresolved',
  ambiguous: 'addonsRefAmbiguous',
  version_unavailable: 'addonsRefVersionUnavailable',
  version_mismatch: 'addonsRefVersionMismatch',
  version_missing: 'addonsRefVersionMissing',
  kind_mismatch: 'addonsRefKindMismatch',
  invalid: 'addonsRefInvalid',
  missing: 'addonsRefUnresolved',
  other_kind: 'addonsRefOtherKind',
  unchecked: 'addonsRefUnchecked',
  context_dependent: 'addonsRefContextDependent',
  pending: 'addonsRefPending'
};

function esAusente(valor) {
  return valor === null || valor === undefined;
}

function mismaVersion(a, b) {
  if (!Array.isArray(a) || !Array.isArray(b)) return esAusente(a) && esAusente(b);
  return a.length === b.length && a.every((valor, i) => valor === b[i]);
}

// Resolucion de UNA dependencia de pack concreta. El analizador emite una
// entrada por (uuid, version) declarados, asi que buscar solo por uuid
// devolveria el estado de OTRA dependencia del mismo UUID con version distinta
// (p. ej. "resuelta" en una dependencia que en realidad no coincide). Si no hay
// entrada exacta se devuelve null: sin estado, nunca un estado ajeno.
export function resolucionDe(pack, dep) {
  const lista = (pack && pack.dependency_resolution) || [];
  return lista.find((r) => r.uuid === dep.uuid && mismaVersion(r.version, dep.version)) || null;
}

// Resumen de la VISTA filtrada. Espejo exacto del `resumen.update(...)` de
// `addon_inventory.filter_payload`: si la GUI no lo recalculara, el panel de
// resumen seguiria mostrando los totales de la instalacion (13 packs, 3
// mundos) mientras la lista ya esta filtrada. Igual que en Python, los campos
// que describen la INSTALACION (complete, packs_sin_analizar/ilegibles/
// invalidos) NO se recalculan; el resumen original se conserva en
// `summary_installation`.
function resumenDeVista(payload, packs, worlds, diagnostics) {
  const cuantos = (lista, condicion) => lista.filter(condicion).length;
  const referencias = worlds.flatMap((w) => w.references || []);
  const porEstado = (estado) => cuantos(referencias, (r) => r.status === estado);
  return {
    ...payload.summary,
    packs_total: packs.length,
    packs_analizados: cuantos(packs, (p) => p.status === 'ok'),
    packs_behavior: cuantos(packs, (p) => p.kind === 'behavior'),
    packs_resource: cuantos(packs, (p) => p.kind === 'resource'),
    packs_compartidos: cuantos(packs, (p) => p.origin === 'compartido'),
    packs_de_sistema: cuantos(packs, (p) => p.origin === 'sistema'),
    packs_de_mundo: cuantos(packs, (p) => p.origin === 'mundo'),
    mundos_total: worlds.length,
    referencias_total: referencias.length,
    referencias_resueltas: porEstado('resolved'),
    referencias_sin_resolver: porEstado('unresolved'),
    referencias_ambiguas: porEstado('ambiguous'),
    referencias_tipo_cruzado: porEstado('kind_mismatch'),
    referencias_sin_version: porEstado('version_unavailable'),
    diagnosticos_total: diagnostics.length,
    errores: cuantos(diagnostics, (d) => d.severity === 'error'),
    avisos: cuantos(diagnostics, (d) => d.severity === 'aviso'),
    informativos: cuantos(diagnostics, (d) => d.severity === 'info')
  };
}

export function textoVersion(valor) {
  if (Array.isArray(valor)) return `[${valor.join(', ')}]`;
  if (valor === null || valor === undefined) return '—';
  return String(valor);
}

export function contarSeveridad(diagnostics = []) {
  const conteo = { error: 0, aviso: 0, info: 0, total: diagnostics.length };
  for (const d of diagnostics) {
    if (Object.hasOwn(conteo, d.severity)) conteo[d.severity] += 1;
  }
  return conteo;
}

// Mismos criterios que addon_inventory.filter_payload:
//  - world: packs propios de ese mundo mas los compartidos y de sistema (los
//    que pueden resolver sus referencias); solo ese mundo en la lista.
//  - kind: packs de ese tipo.
//  - los diagnosticos se limitan a los ambitos/paquetes/mundos conservados.
function tipoDeScope(scope) {
  if (KINDS.includes(scope)) return scope;
  const partes = (scope || '').split(':');
  if ((partes.length === 2 && ['compartido', 'sistema'].includes(partes[0])) ||
      (partes.length === 3 && partes[0] === 'mundo')) {
    return KINDS.includes(partes.at(-1)) ? partes.at(-1) : null;
  }
  return null;
}

export function filtrarInventario(payload, { world = '', kind = '' } = {}) {
  if (!payload) return payload;
  const tipo = KINDS.includes(kind) ? kind : '';
  const mundo = world || '';
  if (!mundo && !tipo) return payload;

  const kinds = tipo ? [tipo] : KINDS;
  const scopes = new Set(kinds.map((k) => `compartido:${k}`));
  for (const k of kinds) scopes.add(`sistema:${k}`);
  if (!mundo) {
    for (const s of payload.scopes || []) {
      if (s.id.startsWith('mundo:')) scopes.add(s.id);
    }
  } else {
    for (const k of kinds) scopes.add(`mundo:${mundo}:${k}`);
  }

  let packs = (payload.packs || []).filter(
    (p) =>
      scopes.has(p.scope) &&
      kinds.includes(p.kind) &&
      (!mundo || p.origin === 'compartido' || p.origin === 'sistema' || p.world === mundo)
  );
  const ids = new Set(packs.map((p) => p.id));
  const worlds = (payload.worlds || []).filter((w) => !mundo || w.name === mundo).map((w) => ({
    ...w,
    references: (w.references || []).filter((r) => !tipo || kinds.includes(r.kind)),
    ref_files: (w.ref_files || []).filter((f) => kinds.includes(f.kind)),
    pack_dirs: Object.fromEntries(Object.entries(w.pack_dirs || {}).filter(([k]) => kinds.includes(k)))
  }));
  const nombres = new Set(worlds.map((w) => w.name));
  const diagnostics = (payload.diagnostics || []).filter(
    (d) =>
      (!mundo || !d.world || d.world === mundo) &&
      (!tipo || tipoDeScope(d.scope) === null || tipoDeScope(d.scope) === tipo) &&
      (scopes.has(d.scope) || (d.world && nombres.has(d.world)) || d.scope === null) &&
      (!d.pack || ids.has(d.pack))
  );
  if (mundo) {
    packs = packs.map((p) => ({
      ...p,
      dependency_resolution: (p.dependency_resolution || []).map((r) => {
        const contextos = r.world_resolutions || [];
        const contexto = contextos.find((c) => c.world === mundo);
        if (contexto) return { ...r, status: contexto.status, candidates: contexto.candidates, world_resolutions: [contexto] };
        // No trasladar el resultado de otro mundo al mundo seleccionado.
        if (contextos.some((c) => c.world !== null)) {
          return { ...r, status: 'unchecked', candidates: [], world_resolutions: [] };
        }
        return r;
      })
    }));
  }

  return {
    ...payload,
    filter: { world: mundo || null, kind: tipo || null },
    summary: resumenDeVista(payload, packs, worlds, diagnostics),
    summary_installation: payload.summary,
    packs,
    worlds,
    diagnostics
  };
}

// Agrupa packs por ambito respetando el orden de `payload.scopes`.
export function agruparPorAmbito(payload) {
  if (!payload) return [];
  const porScope = new Map();
  for (const p of payload.packs || []) {
    if (!porScope.has(p.scope)) porScope.set(p.scope, []);
    porScope.get(p.scope).push(p);
  }
  const grupos = [];
  for (const scope of payload.scopes || []) {
    const packs = porScope.get(scope.id);
    if (packs && packs.length) grupos.push({ scope, packs });
  }
  return grupos;
}
