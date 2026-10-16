import { IMAGE_DB } from './settings.js';
import { imageDimensions } from './imageDimensions.js';

export const IMAGE_LIMITS = Object.freeze({ bytes: 10 * 1024 * 1024, pixels: 64000000, side: 2560 });
const TYPES = ['image/jpeg', 'image/png', 'image/webp'];

export function validateImageFile(file) {
  if (!TYPES.includes(file.type)) throw new Error('appearanceImageTypeError');
  if (!file.size || file.size > IMAGE_LIMITS.bytes) throw new Error('appearanceImageSizeError');
}

export function validateDimensions(width, height) {
  if (!Number.isInteger(width) || !Number.isInteger(height) || width <= 0 || height <= 0 || width * height > IMAGE_LIMITS.pixels) {
    throw new Error('appearanceImageDimensionsError');
  }
}

export function imageStore(action, value) {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(IMAGE_DB, 1);
    request.onupgradeneeded = () => request.result.createObjectStore('images');
    request.onerror = () => reject(request.error);
    request.onblocked = () => reject(new Error('storage-blocked'));
    request.onsuccess = () => {
      const db = request.result;
      db.onversionchange = () => db.close();
      try {
        const tx = db.transaction('images', action === 'get' ? 'readonly' : 'readwrite');
        const store = tx.objectStore('images');
        const operation = action === 'get' ? store.get('background')
          : action === 'delete' ? store.delete('background') : store.put(value, 'background');
        tx.oncomplete = () => { db.close(); resolve(operation.result); };
        tx.onerror = tx.onabort = () => { db.close(); reject(tx.error || new Error('storage-failed')); };
      } catch (error) { db.close(); reject(error); }
    };
  });
}

export async function normalizeImage(file) {
  validateImageFile(file);
  const [width, height] = imageDimensions(await file.arrayBuffer());
  validateDimensions(width, height);
  let bitmap;
  try { bitmap = await createImageBitmap(file); }
  catch { throw new Error('appearanceImageDecodeError'); }
  try {
    validateDimensions(bitmap.width, bitmap.height);
    const ratio = Math.min(1, IMAGE_LIMITS.side / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(bitmap.width * ratio));
    canvas.height = Math.max(1, Math.round(bitmap.height * ratio));
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('appearanceImageDecodeError');
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    return await new Promise((resolve, reject) => canvas.toBlob(
      blob => blob ? resolve(blob) : reject(new Error('appearanceImageDecodeError')), 'image/webp', 0.9
    ));
  } finally { bitmap.close(); }
}
