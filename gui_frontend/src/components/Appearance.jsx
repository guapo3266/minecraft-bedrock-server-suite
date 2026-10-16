import { RotateCw, X, Image } from 'lucide-react';
import Modal from './Modal';
import GlassSelect from './GlassSelect';
import { useI18n } from '../i18n.jsx';

export default function Appearance({ open, onClose, appearance, glassStatus }) {
  const { t } = useI18n();
  const { settings: s, update, url, busy, chooseImage, reset, effectiveEffects, reducedMotion } = appearance;
  if (!open) return null;
  const sliders = [
    ['zoom', 'appearanceZoom', 25, 180], ['x', 'appearanceX', 0, 100],
    ['y', 'appearanceY', 0, 100], [s.theme === 'dark' ? 'darkShade' : 'lightShade', 'appearanceShade', 0, 70]
  ];
  const selector = (key, labelKey, choices) => <div className="field">
    <label htmlFor={`appearance-${key}`}>{t(labelKey)}</label>
    <GlassSelect id={`appearance-${key}`} label={t(labelKey)} value={s[key]}
      options={choices.map(([id, key]) => ({ id, label: t(key) }))} onChange={value => update(key, value)} />
  </div>;
  const slider = (key, labelKey, min, max, hint) => <div className="field" key={key}>
    <label htmlFor={`appearance-${key}`}><span>{t(labelKey)}</span><output htmlFor={`appearance-${key}`}>{s[key]} %</output></label>
    <input id={`appearance-${key}`} type="range" min={min} max={max} value={s[key]}
      aria-label={t(labelKey)} onChange={event => update(key, Number(event.target.value))} aria-describedby={hint ? `appearance-${key}-hint` : undefined} />
    {hint && <small id={`appearance-${key}-hint`}>{t(hint)}</small>}
  </div>;
  return <Modal onClose={() => { if (!busy) onClose(); }} label={t('appearanceTitle')} className="appearance-dialog">
    <div className="dialog-heading">
      <div><span className="eyebrow">{t('appearanceEyebrow')}</span><h2>{t('appearanceTitle')}</h2></div>
      <button className="button icon-button" type="button" aria-label={t('close')} onClick={onClose} disabled={busy}><X size={18} /></button>
    </div>
    <div className="appearance-content">
      <p>{t('appearanceLocal')}</p>
      <div className="appearance-preview" data-custom={Boolean(url)}>
        {url ? <img src={url} alt={t('appearancePreview')} style={{ objectFit: s.fit, objectPosition: `${s.x}% ${s.y}%`,
          transform: `scale(${s.zoom / 100})`, transformOrigin: `${s.x}% ${s.y}%` }} />
          : <span><Image size={18} aria-hidden="true" />{t('appearanceAbstract')}</span>}
      </div>
      <div className="field">
        <label htmlFor="background-file">{t('appearanceImage')}</label>
        <input id="background-file" type="file" accept="image/jpeg,image/png,image/webp" disabled={busy}
          aria-describedby="background-file-hint" onChange={event => { chooseImage(event.target.files[0]); event.target.value = ''; }} />
        <small id="background-file-hint">{t('appearanceImageHint')}</small>
      </div>
      <div className="form-grid">
        {selector('theme', 'appearanceTheme', [['dark', 'appearanceDark'], ['light', 'appearanceLight']])}
        {selector('effects', 'appearanceEffects', [['full', 'appearanceFull'], ['reduced', 'appearanceReduced']])}
      </div>
      {selector('fit', 'appearanceFit', [['contain', 'appearanceContain'], ['cover', 'appearanceCover']])}
      <small>{t('appearanceFitHint')}</small>
      <div className="background-treatment">
        <span>{t('appearanceTreatment')}</span>
        <div className="segments" role="group" aria-label={t('appearanceTreatment')}>
          {[['integrated', 'appearanceIntegrated'], ['free', 'appearanceFree']].map(([value, key]) =>
            <button type="button" key={value} aria-pressed={s.backgroundMode === value}
              className={s.backgroundMode === value ? 'selected' : ''} onClick={() => update('backgroundMode', value)}>{t(key)}</button>)}
        </div>
      </div>
      <label className="checkbox-label"><input type="checkbox" checked={s.readability}
        onChange={event => update('readability', event.target.checked)} />{t('appearanceReadability')}</label>
      <p className="caption" role="status">{t(reducedMotion ? 'appearanceSystemReduced' : effectiveEffects === 'reduced' ? 'appearanceReducedActive'
        : glassStatus === 'ready' ? 'appearanceGlassReady' : glassStatus === 'loading' ? 'appearanceGlassLoading' : 'appearanceGlassFallback')}</p>
      {slider('transparency', 'appearanceTransparency', 0, 100, s.readability ? 'appearanceTransparencyProtected' : 'appearanceTransparencyHint')}
      <div className="slider-grid">{sliders.map(([key, label, min, max]) => slider(key, label, min, max))}</div>
    </div>
    <div className="dialog-actions">
      <button type="button" className="button" onClick={reset} disabled={busy}><RotateCw size={16} />{t('appearanceReset')}</button>
      <button type="button" className="button primary" onClick={onClose} disabled={busy}>{t(busy ? 'appearancePreparing' : 'appearanceDone')}</button>
    </div>
  </Modal>;
}
