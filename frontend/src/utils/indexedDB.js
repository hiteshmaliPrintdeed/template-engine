/**
 * IndexedDB Offline-First Persistence Utility for Pixovo PTE Engine
 * Caches high-res original photo blobs in browser disk storage (IndexedDB).
 * Prevents data loss during network disconnections, browser crashes, or tab closes.
 */

const DB_NAME = 'pixovo_offline_db';
const DB_VERSION = 1;
const STORE_NAME = 'pending_originals';

function openDB() {
  return new Promise((resolve, reject) => {
    if (!window.indexedDB) {
      reject(new Error("IndexedDB not supported in this browser"));
      return;
    }

    const request = window.indexedDB.open(DB_NAME, DB_VERSION);

    request.onerror = (e) => reject(e.target.error);

    request.onsuccess = (e) => resolve(e.target.result);

    request.onupgradeneeded = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: 'photoId' });
      }
    };
  });
}

/**
 * Saves original file blob to IndexedDB linked to photoId.
 *
 * `sessionId` is stored alongside the blob so that after a page refresh the
 * auto-resume path knows which session to upload it into. Without it a queued
 * blob could not be attributed to a session and would retry forever.
 */
export async function saveOriginalBlob(photoId, fileBlob, sessionId = null) {
  try {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const transaction = db.transaction([STORE_NAME], 'readwrite');
      const store = transaction.objectStore(STORE_NAME);

      const record = {
        photoId,
        sessionId,
        blob: fileBlob,
        filename: fileBlob.name,
        timestamp: Date.now()
      };

      const req = store.put(record);
      req.onsuccess = () => resolve(true);
      req.onerror = (e) => reject(e.target.error);
    });
  } catch (err) {
    console.warn(`[IndexedDB] Failed to save blob for ${photoId}:`, err);
    return false;
  }
}

/**
 * Retrieves all pending unsynced original file blobs from IndexedDB.
 */
export async function getPendingBlobs() {
  try {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const transaction = db.transaction([STORE_NAME], 'readonly');
      const store = transaction.objectStore(STORE_NAME);
      const req = store.getAll();

      req.onsuccess = () => resolve(req.result || []);
      req.onerror = (e) => reject(e.target.error);
    });
  } catch (err) {
    console.warn("[IndexedDB] Failed to get pending blobs:", err);
    return [];
  }
}

/**
 * Drops records older than `maxAgeMs` (default 24h).
 *
 * Stage 1.3: an abandoned session used to leave its full-resolution blobs in
 * the user's browser storage forever — potentially gigabytes, and IndexedDB
 * quota exhaustion silently breaks the next upload's crash-safety net.
 * Returns the number of records evicted.
 */
export async function sweepStaleBlobs(maxAgeMs = 24 * 60 * 60 * 1000) {
  try {
    const db = await openDB();
    const cutoff = Date.now() - maxAgeMs;

    return new Promise((resolve, reject) => {
      const transaction = db.transaction([STORE_NAME], 'readwrite');
      const store = transaction.objectStore(STORE_NAME);
      const req = store.getAll();

      req.onsuccess = () => {
        const stale = (req.result || []).filter(r => !r.timestamp || r.timestamp < cutoff);
        stale.forEach(r => store.delete(r.photoId));
        transaction.oncomplete = () => {
          if (stale.length > 0) {
            console.log(`[IndexedDB] Swept ${stale.length} stale original blob(s).`);
          }
          resolve(stale.length);
        };
        transaction.onerror = (e) => reject(e.target.error);
      };
      req.onerror = (e) => reject(e.target.error);
    });
  } catch (err) {
    console.warn('[IndexedDB] Sweep failed:', err);
    return 0;
  }
}

/**
 * Removes original file blob from IndexedDB after successful server upload.
 */
export async function removeOriginalBlob(photoId) {
  try {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const transaction = db.transaction([STORE_NAME], 'readwrite');
      const store = transaction.objectStore(STORE_NAME);
      const req = store.delete(photoId);

      req.onsuccess = () => resolve(true);
      req.onerror = (e) => reject(e.target.error);
    });
  } catch (err) {
    console.warn(`[IndexedDB] Failed to remove blob for ${photoId}:`, err);
    return false;
  }
}

/**
 * Drops every queued original. Used when the user explicitly clears the
 * session: the blobs belong to a session that no longer exists, so leaving
 * them would make auto-resume retry uploads into a dead session.
 */
export async function clearAllBlobs() {
  try {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const transaction = db.transaction([STORE_NAME], 'readwrite');
      const req = transaction.objectStore(STORE_NAME).clear();

      req.onsuccess = () => resolve(true);
      req.onerror = (e) => reject(e.target.error);
    });
  } catch (err) {
    console.warn('[IndexedDB] Failed to clear pending originals:', err);
    return false;
  }
}
