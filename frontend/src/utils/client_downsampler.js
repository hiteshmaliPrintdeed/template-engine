/**
 * Pixovo Stage 2.1 — Client-Side Worker Downsampling & Chunked Ingestion Module
 * -----------------------------------------------------------------------------
 * Downsamples raw high-resolution images (4K/8K JPEGs, PNGs, WebP) in a bounded
 * Web Worker pool using OffscreenCanvas + createImageBitmap (with automatic
 * fallback to main-thread HTML5 Canvas when OffscreenCanvas is unavailable).
 * Extracts EXIF DateTimeOriginal & GPS metadata from the raw file header before
 * canvas encoding strips APP1 metadata.
 */

import { WorkerPool, getOptimalWorkerCount } from './worker_pool';
import { parseExif } from '../workers/exif';

export const SUPPORTS_WORKER_CANVAS =
  typeof Worker !== 'undefined' &&
  typeof OffscreenCanvas !== 'undefined' &&
  typeof createImageBitmap !== 'undefined';

export class PixovoClientDownsampler {
  constructor(options = {}) {
    this.maxDimension = options.maxDimension || 512;
    this.quality = options.quality || 0.85;
    this.concurrency = options.concurrency || getOptimalWorkerCount();
    this.useWorkers = options.useWorkers !== undefined ? options.useWorkers : SUPPORTS_WORKER_CANVAS;
    this.pool = null;
  }

  /**
   * Generate a unique photo_id for tracking across client, storage, and engine.
   */
  generatePhotoId() {
    return 'px_' + Math.random().toString(36).substring(2, 11) + '_' + Date.now().toString(36);
  }

  /**
   * Terminate the underlying Web Worker pool if active.
   */
  terminate() {
    if (this.pool) {
      this.pool.terminate();
      this.pool = null;
    }
  }

  /**
   * Main-thread fallback: Downsample a single File object using DOM Canvas and extract EXIF.
   * Retained for Safari < 16.4 or environments without OffscreenCanvas.
   * @param {File} file - Raw image file from input/dropzone
   * @param {string} [existingPhotoId] - Optional pre-minted photo_id
   * @returns {Promise<Object>} Processed photo object with thumbnail and metadata
   */
  async processSinglePhoto(file, existingPhotoId = null) {
    const photoId = existingPhotoId || this.generatePhotoId();
    const startTime = performance.now();
    const exif = await parseExif(file);

    return new Promise((resolve, reject) => {
      const img = new Image();
      const url = URL.createObjectURL(file);

      img.onload = () => {
        try {
          let width = img.width;
          let height = img.height;
          const nativeAspectRatio = width / Math.max(1, height);

          if (width > height) {
            if (width > this.maxDimension) {
              height = Math.max(1, Math.round((height * this.maxDimension) / width));
              width = this.maxDimension;
            }
          } else {
            if (height > this.maxDimension) {
              width = Math.max(1, Math.round((width * this.maxDimension) / height));
              height = this.maxDimension;
            }
          }

          const canvas = document.createElement('canvas');
          canvas.width = width;
          canvas.height = height;

          const ctx = canvas.getContext('2d');
          ctx.imageSmoothingEnabled = true;
          ctx.imageSmoothingQuality = 'high';
          ctx.drawImage(img, 0, 0, width, height);

          canvas.toBlob(
            (blob) => {
              URL.revokeObjectURL(url);

              const fallbackEpoch = file.lastModified
                ? Math.floor(file.lastModified / 1000)
                : Math.floor(Date.now() / 1000);
              const timestampEpoch = exif.timestamp_epoch || fallbackEpoch;
              const timestamp = exif.timestamp_iso || new Date(timestampEpoch * 1000).toISOString();
              const processingTimeMs = Math.round(performance.now() - startTime);

              resolve({
                photo_id: photoId,
                filename: file.name,
                original_file: file,
                original_size_bytes: file.size,
                original_width: img.width,
                original_height: img.height,
                aspect_ratio: parseFloat(nativeAspectRatio.toFixed(4)),
                orientation: nativeAspectRatio >= 1.2 ? 'LANDSCAPE' : (nativeAspectRatio <= 0.8 ? 'PORTRAIT' : 'SQUARE'),
                timestamp: timestamp,
                timestamp_epoch: timestampEpoch,
                timestamp_source: exif.timestamp_epoch ? 'exif' : 'file_mtime',
                latitude: exif.latitude ?? null,
                longitude: exif.longitude ?? null,
                thumbnail_blob: blob,
                thumbnail_size_bytes: blob ? blob.size : 0,
                processing_time_ms: processingTimeMs
              });
            },
            'image/jpeg',
            this.quality
          );
        } catch (err) {
          URL.revokeObjectURL(url);
          reject(err);
        }
      };

      img.onerror = () => {
        URL.revokeObjectURL(url);
        reject(new Error(`Failed to load image file: ${file.name}`));
      };

      img.src = url;
    });
  }

  /**
   * Batch process multiple files using the OffscreenCanvas Web Worker pool
   * (or main-thread fallback if unsupported) without freezing the UI thread.
   * @param {FileList|Array<File>} fileList - List of raw image files
   * @param {Function} onProgress - Progress callback function (completed, total, currentItem)
   * @returns {Promise<Array<Object>>} Array of processed photo objects
   */
  async processBatch(fileList, onProgress = null) {
    const files = Array.from(fileList).filter(
      f => f.type.startsWith('image/') || /\.(jpe?g|png|webp|heic|tiff)$/i.test(f.name)
    );
    const total = files.length;
    if (total === 0) return [];

    // Worker pool path (Stage 2.1)
    if (this.useWorkers && SUPPORTS_WORKER_CANVAS) {
      if (!this.pool || this.pool.terminated) {
        this.pool = new WorkerPool(
          () => new Worker(new URL('../workers/downsample.worker.js', import.meta.url), { type: 'module' }),
          this.concurrency
        );
      }

      let completed = 0;
      const results = await Promise.all(
        files.map(async (file) => {
          const photoId = this.generatePhotoId();
          const startTime = performance.now();
          try {
            const r = await this.pool.run({
              photoId,
              file,
              maxDimension: this.maxDimension,
              quality: this.quality,
            });
            const item = {
              ...r,
              photo_id: photoId,
              filename: file.name,
              original_file: file,
              original_size_bytes: file.size,
              processing_time_ms: Math.round(performance.now() - startTime),
            };
            completed++;
            onProgress?.(completed, total, item);
            return item;
          } catch (err) {
            // Automatic fallback to main-thread decode if worker fails for a specific file
            try {
              const fallbackItem = await this.processSinglePhoto(file, photoId);
              completed++;
              onProgress?.(completed, total, fallbackItem);
              return fallbackItem;
            } catch (fallbackErr) {
              console.warn(`[Downsampler] Skipping ${file.name}:`, fallbackErr);
              completed++;
              onProgress?.(completed, total, { filename: file.name, error: fallbackErr.message });
              return null;
            }
          }
        })
      );

      return results.filter(Boolean);
    }

    // Main-thread fallback path (Safari < 16.4 or forced fallback)
    const results = [];
    let completed = 0;

    for (let i = 0; i < files.length; i += this.concurrency) {
      const chunk = files.slice(i, i + this.concurrency);
      const chunkPromises = chunk.map(async (file) => {
        try {
          const result = await this.processSinglePhoto(file);
          completed++;
          if (onProgress) onProgress(completed, total, result);
          return result;
        } catch (err) {
          console.warn(`[Downsampler] Skipping corrupt file ${file.name}:`, err);
          completed++;
          if (onProgress) onProgress(completed, total, { filename: file.name, error: err.message });
          return null;
        }
      });

      const chunkResults = await Promise.all(chunkPromises);
      results.push(...chunkResults.filter(Boolean));
    }

    return results;
  }

  /**
   * Split an array into fixed-size chunks.
   * Static so callers can chunk without holding a downsampler instance.
   */
  static chunk(items, size = 40) {
    const out = [];
    for (let i = 0; i < items.length; i += size) {
      out.push(items.slice(i, i + size));
    }
    return out;
  }

  /**
   * Build ONE ingest chunk payload: 512px thumbnails + metadata JSON only.
   */
  buildChunkPayload(processedPhotos, sessionId, chunkIndex, chunkCount) {
    const formData = new FormData();
    const metadataArray = [];

    processedPhotos.forEach((photo) => {
      if (photo.thumbnail_blob) {
        formData.append('thumbnails', photo.thumbnail_blob, `${photo.photo_id}_thumb.jpg`);
      }

      const tsMs = Date.parse(photo.timestamp);
      const fallbackEpoch = Number.isFinite(tsMs) ? Math.floor(tsMs / 1000) : 0;
      const timestampEpoch = photo.timestamp_epoch || fallbackEpoch;

      metadataArray.push({
        photo_id: photo.photo_id,
        filename: photo.filename,
        original_size_bytes: photo.original_size_bytes,
        original_width: photo.original_width,
        original_height: photo.original_height,
        aspect_ratio: photo.aspect_ratio,
        orientation: photo.orientation,
        timestamp: photo.timestamp,
        timestamp_epoch: timestampEpoch,
        timestamp_source: photo.timestamp_source || 'file_mtime',
        latitude: photo.latitude ?? null,
        longitude: photo.longitude ?? null,
        thumbnail_size_bytes: photo.thumbnail_size_bytes
      });
    });

    formData.append('session_id', sessionId);
    formData.append('chunk_index', String(chunkIndex));
    formData.append('chunk_count', String(chunkCount));
    formData.append('metadata_json', JSON.stringify(metadataArray));
    return formData;
  }
}

export default PixovoClientDownsampler;
