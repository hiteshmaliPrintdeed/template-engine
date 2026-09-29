/**
 * Stage 2.1 — OffscreenCanvas Downsample Worker.
 * Receives a File, extracts EXIF DateTimeOriginal + GPS before decode,
 * downsamples to a 512px JPEG blob off the main thread, closes the ImageBitmap
 * immediately to release decoded RGBA memory, and posts the result back.
 */

import { parseExif } from './exif.js';

self.onmessage = async (e) => {
  const { photoId, file, maxDimension = 512, quality = 0.85 } = e.data || {};
  let bitmap = null;

  try {
    // 1. Read EXIF from raw file header BEFORE canvas decode strips APP1 metadata
    const exif = await parseExif(file);

    // 2. Decode off the main thread
    bitmap = await createImageBitmap(file);
    const origWidth = bitmap.width;
    const origHeight = bitmap.height;

    let width = origWidth;
    let height = origHeight;
    const nativeAspect = width / Math.max(1, height);

    if (width > height) {
      if (width > maxDimension) {
        height = Math.max(1, Math.round((height * maxDimension) / width));
        width = maxDimension;
      }
    } else {
      if (height > maxDimension) {
        width = Math.max(1, Math.round((width * maxDimension) / height));
        height = maxDimension;
      }
    }

    // 3. Render onto OffscreenCanvas
    const canvas = new OffscreenCanvas(width, height);
    const ctx = canvas.getContext('2d');
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(bitmap, 0, 0, width, height);

    // Release ~48MB decoded RGBA bitmap immediately before encoding
    bitmap.close();
    bitmap = null;

    const blob = await canvas.convertToBlob({ type: 'image/jpeg', quality });

    const fallbackEpoch = file.lastModified ? Math.floor(file.lastModified / 1000) : Math.floor(Date.now() / 1000);
    const timestampEpoch = exif.timestamp_epoch || fallbackEpoch;
    const timestampIso = exif.timestamp_iso || new Date(timestampEpoch * 1000).toISOString();

    const result = {
      photoId,
      thumbnail_blob: blob,
      thumbnail_size_bytes: blob.size,
      original_width: origWidth,
      original_height: origHeight,
      aspect_ratio: parseFloat(nativeAspect.toFixed(4)),
      orientation: nativeAspect >= 1.2 ? 'LANDSCAPE' : (nativeAspect <= 0.8 ? 'PORTRAIT' : 'SQUARE'),
      timestamp: timestampIso,
      timestamp_epoch: timestampEpoch,
      timestamp_source: exif.timestamp_epoch ? 'exif' : 'file_mtime',
      latitude: exif.latitude ?? null,
      longitude: exif.longitude ?? null,
    };

    self.postMessage({ ok: true, result });
  } catch (err) {
    if (bitmap && typeof bitmap.close === 'function') {
      try { bitmap.close(); } catch (_) {}
    }
    self.postMessage({
      ok: false,
      photoId,
      error: err?.message || 'Worker downsample failed'
    });
  }
};
