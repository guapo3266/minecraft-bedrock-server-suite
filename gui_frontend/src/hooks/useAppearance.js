import { useCallback, useEffect, useRef, useState } from 'react';
import { DEFAULTS, SETTINGS_KEY, normalizeSettings, readSettings, resetBackground } from '../appearance/settings.js';
import { imageStore, normalizeImage } from '../appearance/imageStorage.js';

export function useAppearance(notify) {
  const [reducedMotion, setReducedMotion] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const [settings, setSettings] = useState(() => {
    try { return readSettings(window.localStorage, reducedMotion); }
    catch { return normalizeSettings(null, reducedMotion); }
  });
  const [blob, setBlob] = useState(null);
  const [url, setUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false), warning = useRef(false), revision = useRef(0);
  const notifyRef = useRef(notify);
  notifyRef.current = notify;

  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    const change = () => setReducedMotion(media.matches);
    media.addEventListener('change', change);
    return () => media.removeEventListener('change', change);
  }, []);

  useEffect(() => {
    let active = true;
    imageStore('get').then(value => {
      if (active && revision.current === 0 && value instanceof Blob) setBlob(value);
    }).catch(() => { if (active) notifyRef.current('appearanceImageLoadError', 'error'); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!blob) { setUrl(''); return; }
    const next = URL.createObjectURL(blob);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [blob]);

  const effectiveEffects = reducedMotion ? 'reduced' : settings.effects;
  useEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = settings.theme;
    root.dataset.effects = effectiveEffects;
    root.dataset.readability = settings.readability ? 'protected' : 'free';
    root.style.colorScheme = settings.theme;
    root.style.setProperty('--material-opacity', String((100 - settings.transparency) / 100));
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', settings.theme === 'dark' ? '#0b1921' : '#dcebf1');
    try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings)); }
    catch {
      if (!warning.current) { warning.current = true; notifyRef.current('appearanceSaveError', 'error'); }
    }
  }, [settings, effectiveEffects]);

  const update = useCallback((key, value) => {
    if (Object.hasOwn(DEFAULTS, key)) setSettings(previous => normalizeSettings({ ...previous, [key]: value }));
  }, []);
  const chooseImage = async file => {
    if (!file || busyRef.current) return;
    revision.current++;
    busyRef.current = true; setBusy(true);
    try {
      const next = await normalizeImage(file);
      setBlob(next);
      try { await imageStore('put', next); notifyRef.current('appearanceImageSaved'); }
      catch { notifyRef.current('appearanceImageSessionOnly', 'error'); }
    } catch (error) {
      notifyRef.current(error.message.startsWith('appearanceImage') ? error.message : 'appearanceImageDecodeError', 'error');
    } finally { busyRef.current = false; setBusy(false); }
  };
  const reset = async () => {
    if (busyRef.current) return;
    revision.current++;
    busyRef.current = true; setBusy(true); setBlob(null);
    setSettings(resetBackground);
    try { await imageStore('delete'); notifyRef.current('appearanceImageReset'); }
    catch { notifyRef.current('appearanceImageResetError', 'error'); }
    finally { busyRef.current = false; setBusy(false); }
  };
  return { settings, effectiveEffects, reducedMotion, update, url, busy, chooseImage, reset };
}
