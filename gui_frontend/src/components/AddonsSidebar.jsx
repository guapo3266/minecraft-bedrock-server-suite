import React, { useCallback, useEffect, useMemo, useState } from 'react';
import SpotlightCard from './reactbits/SpotlightCard';
import GlassSelect from './GlassSelect';
import { Boxes, RefreshCw, TriangleAlert, XCircle, ChevronDown, ChevronRight, ShieldAlert } from 'lucide-react';
import { useI18n } from '../i18n.jsx';
import {
  CLAVES_RESOLUCION,
  agruparPorAmbito,
  contarSeveridad,
  filtrarInventario,
  resolucionDe,
  textoVersion
} from '../addonsLogic.js';

// Estilos por gravedad del diagnostico (mismo lenguaje visual que el resto).
const SEVERITY_STYLES = {
  error: 'border-rose-500/40 bg-rose-500/10 text-rose-300',
  aviso: 'border-amber-500/40 bg-amber-500/10 text-amber-300',
  info: 'border-cyan-500/40 bg-cyan-500/10 text-cyan-300'
};

const PACK_STATUS_KEYS = {
  invalid: 'addonsStatusInvalid',
  unreadable: 'addonsStatusUnreadable',
  unsupported: 'addonsStatusUnsupported'
};

export default function AddonsSidebar() {
  const { t, lang } = useI18n();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [world, setWorld] = useState('');
  const [kind, setKind] = useState('');
  const [expanded, setExpanded] = useState(null);
  const [showAllDiagnostics, setShowAllDiagnostics] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/addons');
      if (!res.ok) {
        const cuerpo = await res.json().catch(() => ({}));
        throw new Error(cuerpo.detail || res.statusText || `HTTP ${res.status}`);
      }
      setData(await res.json());
    } catch (e) {
      // La pestaña no puede quedarse muda mostrando un inventario vacio: el
      // fallo se presenta con su motivo y boton de reintento.
      setError(String(e.message || e));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const vista = useMemo(() => filtrarInventario(data, { world, kind }), [data, world, kind]);
  const conteo = useMemo(() => contarSeveridad(vista?.diagnostics || []), [vista]);
  const grupos = useMemo(() => agruparPorAmbito(vista), [vista]);
  const diagnosticos = useMemo(() => {
    const lista = vista?.diagnostics || [];
    return showAllDiagnostics ? lista : lista.filter((d) => d.severity !== 'info');
  }, [vista, showAllDiagnostics]);

  const mensaje = (d) => (lang === 'es' ? d.message_es : d.message_en);

  const refreshButton = (
    <button
      type="button"
      onClick={load}
      disabled={loading}
      title={t('addonsRefresh')}
      aria-label={t('addonsRefresh')}
      className="flex items-center gap-1.5 rounded-lg border border-cyan-500/40 bg-cyan-500/10 px-2.5 py-1 text-[11px] font-bold text-cyan-300 transition hover:bg-cyan-500/25 disabled:opacity-50"
    >
      <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
      <span>{loading ? t('addonsRefreshing') : t('addonsRefresh')}</span>
    </button>
  );

  if (loading && !data) {
    return (
      <SpotlightCard spotlightColor="rgba(6, 182, 212, 0.15)">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
          <Boxes className="h-4 w-4 text-cyan-400" />
          <h3>{t('addonsTitle')}</h3>
        </div>
        <p role="status" className="mt-4 text-center text-xs italic text-slate-400">
          {t('addonsLoading')}
        </p>
      </SpotlightCard>
    );
  }

  if (error) {
    return (
      <SpotlightCard spotlightColor="rgba(244, 63, 94, 0.15)">
        <div className="flex items-center justify-between gap-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
          <div className="flex items-center gap-2">
            <Boxes className="h-4 w-4 text-cyan-400" />
            <h3>{t('addonsTitle')}</h3>
          </div>
          {refreshButton}
        </div>
        <div role="alert" className="mt-4 flex items-start gap-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs font-semibold text-rose-300">
          <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span className="break-all">{t('addonsError', { err: error })}</span>
        </div>
        <button
          type="button"
          onClick={load}
          className="mt-3 w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-xs font-bold text-slate-200 transition hover:bg-white/15"
        >
          {t('addonsRetry')}
        </button>
      </SpotlightCard>
    );
  }

  const resumen = vista.summary;
  const soportado = vista.supported || {};

  return (
    <div className="addons-grid legacy-ui">
      <SpotlightCard spotlightColor="rgba(6, 182, 212, 0.15)">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
            <Boxes className="h-4 w-4 text-cyan-400" />
            <h3>{t('addonsTitle')}</h3>
          </div>
          {refreshButton}
        </div>

        <div
          className={`mt-3 flex items-start gap-2 rounded-lg border px-3 py-2 text-[11px] font-semibold ${
            vista.complete
              ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
              : 'border-amber-500/40 bg-amber-500/10 text-amber-300'
          }`}
        >
          <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <div>
            <p>{vista.complete ? t('addonsComplete') : t('addonsPartial')}</p>
            {!vista.complete && (
              <p className="mt-1 font-mono text-[10px] font-normal">
                {t('addonsPartialReasons', { reasons: (vista.partial_reasons || []).join(', ') })}
              </p>
            )}
          </div>
        </div>

        <dl className="mt-3 grid grid-cols-2 gap-2 text-[11px] text-slate-300">
          <div>
            <dt className="text-slate-500">{t('addonsPacks')}</dt>
            <dd className="font-bold text-white">{resumen.packs_total}</dd>
          </div>
          <div>
            <dt className="text-slate-500">{t('addonsWorlds')}</dt>
            <dd className="font-bold text-white">{resumen.mundos_total}</dd>
          </div>
          <div>
            <dt className="text-slate-500">{t('addonsActiveWorld')}</dt>
            <dd className="truncate font-bold text-white">{vista.active_world || t('addonsUnknown')}</dd>
          </div>
          <div>
            <dt className="text-slate-500">{t('addonsReferences')}</dt>
            <dd className="font-bold text-white">
              {resumen.referencias_resueltas}/{resumen.referencias_total}
            </dd>
          </div>
        </dl>

        <p className="mt-3 text-[10px] text-slate-500">
          {t('addonsSupported', {
            formats: (soportado.manifest_format_versions || []).join(', ')
          })}
        </p>

        <div className="mt-3 flex flex-wrap gap-2 text-[10px] font-bold">
          <span className="rounded-full border border-rose-500/40 bg-rose-500/10 px-2 py-0.5 text-rose-300">
            {conteo.error} {t('addonsErrors')}
          </span>
          <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-amber-300">
            {conteo.aviso} {t('addonsWarnings')}
          </span>
          <span className="rounded-full border border-cyan-500/40 bg-cyan-500/10 px-2 py-0.5 text-cyan-300">
            {conteo.info} {t('addonsInfo')}
          </span>
        </div>
      </SpotlightCard>

      <SpotlightCard spotlightColor="rgba(16, 185, 129, 0.12)">
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex flex-1 flex-col gap-1 text-[10px] font-bold uppercase tracking-wide text-slate-500">
            {t('addonsFilterWorld')}
            <GlassSelect
              value={world}
              onChange={setWorld}
              label={t('addonsFilterWorld')}
              options={[{ id: '', label: t('filterAll') }, ...(data.worlds || []).map(w => ({ id: w.name, label: w.name }))]}
            />
          </label>
          <label className="flex flex-1 flex-col gap-1 text-[10px] font-bold uppercase tracking-wide text-slate-500">
            {t('addonsFilterKind')}
            <GlassSelect
              value={kind}
              onChange={setKind}
              label={t('addonsFilterKind')}
              options={[{ id: '', label: t('filterAll') }, { id: 'behavior', label: t('addonsKindBehavior') }, { id: 'resource', label: t('addonsKindResource') }]}
            />
          </label>
        </div>

        <div className="mt-3 max-h-[380px] overflow-y-auto pr-1">
          {grupos.length === 0 ? (
            <p className="py-4 text-center text-xs italic text-slate-400">{t('addonsNoPacks')}</p>
          ) : (
            grupos.map(({ scope, packs }) => (
              <div key={scope.id} className="mb-3">
                <p className="mb-1 text-[10px] font-bold uppercase tracking-wide text-slate-500">
                  {scope.root} &bull; {packs.length}
                </p>
                <ul className="flex flex-col gap-1">
                  {packs.map((p) => {
                    const abierto = expanded === p.id;
                    const propios = (vista.diagnostics || []).filter((d) => d.pack === p.id);
                    return (
                      <li key={p.id} className="rounded-lg border border-white/5 bg-white/5 px-2 py-1.5">
                        <button
                          type="button"
                          onClick={() => setExpanded(abierto ? null : p.id)}
                          aria-expanded={abierto}
                          className="flex w-full items-start gap-1.5 text-left"
                        >
                          {abierto ? (
                            <ChevronDown className="mt-0.5 h-3 w-3 shrink-0 text-cyan-400" />
                          ) : (
                            <ChevronRight className="mt-0.5 h-3 w-3 shrink-0 text-slate-500" />
                          )}
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-[11px] font-bold text-white">
                              {p.name || t('addonsNoName')}
                            </span>
                            <span className="block truncate font-mono text-[9px] text-slate-500">
                              {p.folder}
                            </span>
                            <span className="mt-0.5 flex flex-wrap items-center gap-1">
                              <span className="rounded border border-cyan-500/30 bg-cyan-500/10 px-1 text-[9px] font-bold text-cyan-300">
                                {p.kind === 'behavior' ? t('addonsKindBehavior') : t('addonsKindResource')}
                              </span>
                              <span className="rounded border border-white/10 bg-white/5 px-1 text-[9px] text-slate-300">
                                {textoVersion(p.version)}
                              </span>
                              <span className="rounded border border-white/10 bg-white/5 px-1 text-[9px] text-slate-400">
                                {t('addonsOrigin_' + p.origin)}
                              </span>
                              {PACK_STATUS_KEYS[p.status] && (
                                <span className="rounded border border-amber-500/40 bg-amber-500/10 px-1 text-[9px] font-bold text-amber-300">
                                  {t(PACK_STATUS_KEYS[p.status])}
                                </span>
                              )}
                              {propios.length > 0 && (
                                <span className="rounded border border-rose-500/40 bg-rose-500/10 px-1 text-[9px] font-bold text-rose-300">
                                  {propios.length}
                                </span>
                              )}
                            </span>
                          </span>
                        </button>

                        {abierto && (
                          <div className="mt-2 flex flex-col gap-1.5 border-t border-white/5 pt-2 text-[10px] text-slate-300">
                            <p className="font-mono break-all text-slate-400">
                              {t('addonsUuid')}: {p.header_uuid || t('addonsUnknown')}
                            </p>
                            {p.description && (
                              <p className="break-words">{p.description}</p>
                            )}
                            <p>
                              {t('addonsFormatVersion')}: {textoVersion(p.format_version)} &bull;{' '}
                              {t('addonsMinEngine')}: {textoVersion(p.min_engine_version)}
                            </p>
                            <div>
                              <p className="font-bold text-slate-400">{t('addonsModules')}</p>
                              {p.modules.length === 0 ? (
                                <p className="italic text-slate-500">{t('addonsNone')}</p>
                              ) : (
                                <ul className="mt-0.5 flex flex-col gap-0.5">
                                  {p.modules.map((m) => (
                                    <li key={`${p.id}-m-${m.index}`} className="font-mono break-all">
                                      {m.type || '?'} &bull; {m.uuid || '—'} &bull; {textoVersion(m.version)}
                                    </li>
                                  ))}
                                </ul>
                              )}
                            </div>
                            <div>
                              <p className="font-bold text-slate-400">{t('addonsPackDeps')}</p>
                              {p.pack_dependencies.length === 0 ? (
                                <p className="italic text-slate-500">{t('addonsNone')}</p>
                              ) : (
                                <ul className="mt-0.5 flex flex-col gap-0.5">
                                  {p.pack_dependencies.map((d) => {
                                    const resolucion = resolucionDe(p, d);
                                    return (
                                      <li key={`${p.id}-d-${d.index}`} className="font-mono break-all">
                                        {d.uuid || '?'} &bull; {textoVersion(d.version)}
                                        {resolucion && (
                                          <span className="ml-1 font-sans text-slate-400">
                                            [{t(CLAVES_RESOLUCION[resolucion.status] || 'addonsRefPending')}]
                                          </span>
                                        )}
                                        {(resolucion?.world_resolutions || []).filter((r) => r.world !== null).map((r) => (
                                          <span key={r.world} className="block font-sans text-slate-400">
                                            {r.world}: {t(CLAVES_RESOLUCION[r.status] || 'addonsRefPending')}
                                          </span>
                                        ))}
                                      </li>
                                    );
                                  })}
                                </ul>
                              )}
                            </div>
                            <div>
                              <p className="font-bold text-slate-400">{t('addonsScriptDeps')}</p>
                              {p.script_dependencies.length === 0 ? (
                                <p className="italic text-slate-500">{t('addonsNone')}</p>
                              ) : (
                                <ul className="mt-0.5 flex flex-col gap-0.5">
                                  {p.script_dependencies.map((d) => (
                                    <li key={`${p.id}-s-${d.index}`} className="font-mono break-all">
                                      {d.module_name || '?'} &bull; {d.version || '—'}
                                      {d.beta && (
                                        <span className="ml-1 font-sans font-bold text-amber-300">
                                          beta
                                        </span>
                                      )}
                                    </li>
                                  ))}
                                </ul>
                              )}
                            </div>
                            <p>
                              <span className="font-bold text-slate-400">{t('addonsReferencedBy')}: </span>
                              {p.referenced_by_worlds.length
                                ? p.referenced_by_worlds.join(', ')
                                : t('addonsNone')}
                            </p>
                          </div>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))
          )}
        </div>
      </SpotlightCard>

      <SpotlightCard spotlightColor="rgba(244, 63, 94, 0.12)">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
            <TriangleAlert className="h-4 w-4 text-amber-400" />
            <h3>{t('addonsDiagnostics')}</h3>
          </div>
          <button
            type="button"
            onClick={() => setShowAllDiagnostics((v) => !v)}
            className="rounded-md border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] font-bold text-slate-300 transition hover:bg-white/15"
          >
            {showAllDiagnostics ? t('addonsHideInfo') : t('addonsShowInfo')}
          </button>
        </div>

        {diagnosticos.length === 0 ? (
          <p className="mt-3 text-center text-xs italic text-slate-400">{t('addonsNoDiagnostics')}</p>
        ) : (
          <ul className="mt-3 flex max-h-[320px] flex-col gap-2 overflow-y-auto pr-1">
            {diagnosticos.map((d, i) => (
              <li
                key={`${d.code}-${d.source_file}-${d.field || ''}-${i}`}
                className={`rounded-lg border px-2 py-1.5 text-[10px] ${SEVERITY_STYLES[d.severity] || SEVERITY_STYLES.info}`}
              >
                <p className="flex items-center justify-between gap-2 font-mono font-bold">
                  <span className="break-all">{d.code}</span>
                  <span className="shrink-0 opacity-80">{d.source}</span>
                </p>
                <p className="mt-0.5 font-normal text-slate-200">{mensaje(d)}</p>
                <p className="mt-0.5 font-mono text-[9px] text-slate-400 break-all">
                  {d.source_file}
                  {d.field ? ` • ${d.field}` : ''}
                </p>
                {!d.determined && (
                  <p className="mt-0.5 text-[9px] font-bold uppercase">{t('addonsNotDetermined')}</p>
                )}
              </li>
            ))}
          </ul>
        )}

        {(vista.not_analyzed || []).length > 0 && (
          <div className="mt-3">
            <p className="text-[10px] font-bold uppercase tracking-wide text-slate-500">
              {t('addonsNotAnalyzed')}
            </p>
            <ul className="mt-1 flex flex-col gap-0.5 text-[10px] text-slate-400">
              {vista.not_analyzed.slice(0, 20).map((n) => (
                <li key={`${n.reason_code}-${n.path}`} className="break-all font-mono">
                  {n.path} &bull; {n.reason_code}
                </li>
              ))}
            </ul>
          </div>
        )}
      </SpotlightCard>
    </div>
  );
}
