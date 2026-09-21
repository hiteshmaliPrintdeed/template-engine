/**
 * Transport for one full-resolution original.
 *
 * The client does not decide how to upload — it asks. POST /api/uploads/presign
 * answers either with credentials for a direct browser-to-bucket upload or with
 * `mode: "proxy"` pointing at the original multipart endpoint. That keeps this
 * one code path whether the server is in local-disk or S3 mode, and makes
 * flipping PIXOVO_DIRECT_UPLOAD=0 an instant rollback that needs no client
 * deploy.
 *
 * Nothing here ever persists a presigned URL. They live for 15 minutes; the
 * IndexedDB queue lives for 24 hours and survives refreshes, so a stored URL
 * would be expired far more often than not. Every attempt re-presigns.
 */

/** What the caller should do with this photo next. */
export const Outcome = {
  DONE: 'done',            // uploaded and verified; drop the blob
  PERMANENT: 'permanent',  // will never succeed; drop the blob, stop retrying
  RETRY: 'retry',          // transient; keep the blob and try later
};

/**
 * Status codes the server uses for conditions that cannot improve: wrong
 * session, unknown photo, expired session, over a hard limit. Matching the
 * server's existing semantics exactly matters — a blob kept for a permanent
 * failure is retried forever, and one dropped for a transient failure is lost.
 */
const PERMANENT_STATUSES = new Set([400, 403, 404, 410, 413, 415]);

/**
 * After this many opaque network failures in a row we stop asking for presigns
 * and use the proxy for the rest of the session.
 *
 * A misconfigured bucket CORS policy is indistinguishable from being offline
 * from inside the browser: the request fails with no status and no body,
 * because the preflight never produced readable headers. Without this the
 * client would retry a hopeless request forever. Two is enough to tell a
 * systematic misconfiguration from one flaky request.
 */
const OPAQUE_FAILURE_LIMIT = 2;

const transportState = {
  proxyOnly: false,
  consecutiveOpaqueFailures: 0,
};

/** Test/session hook: forget the circuit breaker. */
export function resetTransport() {
  transportState.proxyOnly = false;
  transportState.consecutiveOpaqueFailures = 0;
}

export function isProxyOnly() {
  return transportState.proxyOnly;
}

function reportMetric(stepName, details) {
  // Fire and forget: this is telemetry, and a failure here must never affect
  // the upload it is describing.
  try {
    fetch('/api/client-metrics', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ step_name: stepName, elapsed_ms: 0, details }),
    }).catch(() => {});
  } catch (_) { /* ignore */ }
}

function tripCircuitBreaker(reason) {
  transportState.proxyOnly = true;
  console.warn(
    `[Upload] Direct-to-bucket upload failed opaquely ${OPAQUE_FAILURE_LIMIT}x ` +
    `(${reason}). Falling back to proxy uploads for the rest of this session. ` +
    `This usually means the bucket's CORS policy does not allow this origin.`
  );
  reportMetric('Direct Upload Fallback (opaque network failure)', {
    reason,
    limit: OPAQUE_FAILURE_LIMIT,
  });
}

/**
 * Send a body with XMLHttpRequest rather than fetch.
 *
 * Two reasons fetch will not do here:
 *   1. fetch cannot report upload progress at all, so a 20 MB original would
 *      show nothing until it completed.
 *   2. fetch collapses a CORS/preflight rejection and a dropped connection into
 *      the same opaque TypeError. XHR gives status 0 on both but lets us
 *      distinguish them from a real HTTP response, which is what the circuit
 *      breaker keys on.
 */
function sendXhr({ method, url, body, headers = {}, onProgress }) {
  return new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    xhr.open(method, url, true);
    for (const [name, value] of Object.entries(headers)) {
      xhr.setRequestHeader(name, value);
    }
    if (onProgress && xhr.upload) {
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) onProgress(event.loaded, event.total);
      };
    }
    // status 0 means no HTTP response was readable: CORS preflight rejection,
    // DNS failure, offline, or an aborted connection.
    xhr.onload = () => resolve({ ok: xhr.status >= 200 && xhr.status < 300, status: xhr.status, body: xhr.responseText });
    xhr.onerror = () => resolve({ ok: false, status: 0, body: '' });
    xhr.ontimeout = () => resolve({ ok: false, status: 0, body: '' });
    xhr.send(body);
  });
}

async function requestPresign(sessionId, photoId, file) {
  const res = await fetch('/api/uploads/presign', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      photo_id: photoId,
      content_type: file?.type || undefined,
      // The server uses this only to reserve quota for bytes it will never
      // see. It verifies the real size with head_object at confirm time.
      declared_bytes: file?.size || 0,
    }),
  });
  return res;
}

/** The pre-existing multipart path, unchanged. */
async function uploadViaProxy({ url, sessionId, photoId, file, onProgress }) {
  const formData = new FormData();
  formData.append('file', file, file.name || `${photoId}.jpg`);

  const target = url || (
    `/api/upload-originals?session_id=${encodeURIComponent(sessionId)}` +
    `&photo_id=${encodeURIComponent(photoId)}`
  );

  const res = await sendXhr({ method: 'POST', url: target, body: formData, onProgress });
  if (res.ok) return Outcome.DONE;
  if (PERMANENT_STATUSES.has(res.status)) {
    console.warn(`[Upload] Proxy rejected ${photoId} (${res.status}); discarding.`);
    return Outcome.PERMANENT;
  }
  return Outcome.RETRY;
}

/**
 * Send the bytes straight to storage using the credentials from presign.
 * Returns an XHR-shaped result so the caller can branch on status.
 */
function uploadToBucket(presign, file, photoId, onProgress) {
  if (presign.mode === 's3_post') {
    const form = new FormData();
    // Every policy field must precede the file part. S3 parses the multipart
    // body in order and rejects the request if `file` arrives before the
    // policy and signature it is validated against.
    for (const [name, value] of Object.entries(presign.fields || {})) {
      form.append(name, value);
    }
    form.append('file', file, file.name || `${photoId}.jpg`);
    return sendXhr({ method: 'POST', url: presign.url, body: form, onProgress });
  }

  // s3_put
  return sendXhr({
    method: 'PUT',
    url: presign.url,
    body: file,
    headers: presign.headers || {},
    onProgress,
  });
}

/**
 * Tell the server an upload landed, so it can verify and account for it.
 *
 * Safe to call speculatively and repeatedly: the server verifies with
 * head_object and the update is a no-op once the recorded size already
 * matches, so a replay adds nothing to the session's byte total.
 */
export async function confirmUpload(sessionId, photoId, etag) {
  const res = await fetch('/api/uploads/confirm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, photo_id: photoId, etag: etag || undefined }),
  });

  if (res.ok) return Outcome.DONE;

  // 409 means the object is not in storage. For a speculative confirm that is
  // the expected answer and simply means "upload it"; it is never permanent.
  if (res.status === 409) return Outcome.RETRY;

  if (PERMANENT_STATUSES.has(res.status)) {
    console.warn(`[Upload] Confirm rejected ${photoId} (${res.status}); discarding.`);
    return Outcome.PERMANENT;
  }
  return Outcome.RETRY;
}

/**
 * Upload one original, whichever way the server says to.
 *
 * @param {object}   args
 * @param {string}   args.sessionId
 * @param {string}   args.photoId
 * @param {File|Blob} args.file
 * @param {function} [args.onProgress] - (loaded, total) during the transfer
 * @param {boolean}  [args.confirmFirst] - ask whether it already landed before
 *   spending bandwidth. Used on resume: an upload that succeeded while the
 *   confirm call was lost is otherwise re-uploaded in full.
 * @returns {Promise<string>} one of Outcome
 */
export async function uploadOriginal({ sessionId, photoId, file, onProgress, confirmFirst = false }) {
  if (!sessionId || !photoId || !file) return Outcome.PERMANENT;

  if (confirmFirst) {
    // Cheap, and it turns "the PUT worked but the confirm was lost" — an
    // orphaned object the server would otherwise have to reconcile — into a
    // self-healing case that costs one request instead of 20 MB.
    const already = await confirmUpload(sessionId, photoId);
    if (already === Outcome.DONE || already === Outcome.PERMANENT) return already;
  }

  if (transportState.proxyOnly) {
    return uploadViaProxy({ sessionId, photoId, file, onProgress });
  }

  let presignRes;
  try {
    presignRes = await requestPresign(sessionId, photoId, file);
  } catch (_) {
    return Outcome.RETRY;   // our own API is unreachable; nothing to discard over
  }

  if (!presignRes.ok) {
    if (PERMANENT_STATUSES.has(presignRes.status)) {
      console.warn(`[Upload] Presign rejected ${photoId} (${presignRes.status}); discarding.`);
      return Outcome.PERMANENT;
    }
    return Outcome.RETRY;   // includes 429, which the caller should back off on
  }

  const presign = await presignRes.json();

  if (presign.mode === 'proxy') {
    return uploadViaProxy({ url: presign.url, sessionId, photoId, file, onProgress });
  }

  // Refuse locally what storage would refuse anyway, so a doomed 20 MB upload
  // is not attempted. Needed in particular for mode s3_put, where max_bytes is
  // null because a presigned PUT cannot constrain the size at all.
  const ceiling = presign.max_bytes || 0;
  if (ceiling && file.size > ceiling) {
    console.warn(
      `[Upload] ${photoId} is ${(file.size / 1024 ** 2).toFixed(1)}MB, over the ` +
      `${(ceiling / 1024 ** 2).toFixed(0)}MB limit; discarding.`
    );
    return Outcome.PERMANENT;
  }

  let result = await uploadToBucket(presign, file, photoId, onProgress);

  // A 403 from storage on a freshly-minted signature means it expired between
  // presign and the retry, or the clock moved. Re-presign once rather than
  // hammering a URL that can no longer work.
  if (result.status === 403) {
    console.warn(`[Upload] Signature rejected for ${photoId}; re-presigning once.`);
    const retryRes = await requestPresign(sessionId, photoId, file);
    if (!retryRes.ok) return Outcome.RETRY;
    const fresh = await retryRes.json();
    if (fresh.mode === 'proxy') {
      return uploadViaProxy({ url: fresh.url, sessionId, photoId, file, onProgress });
    }
    result = await uploadToBucket(fresh, file, photoId, onProgress);
  }

  if (result.status === 0) {
    transportState.consecutiveOpaqueFailures += 1;
    if (transportState.consecutiveOpaqueFailures >= OPAQUE_FAILURE_LIMIT) {
      tripCircuitBreaker('no HTTP status from the bucket');
      // Do the work now via the proxy rather than making the user wait for
      // another retry cycle to discover the fallback.
      return uploadViaProxy({ sessionId, photoId, file, onProgress });
    }
    return Outcome.RETRY;
  }

  transportState.consecutiveOpaqueFailures = 0;

  if (!result.ok) {
    // 400/413 from storage: the policy refused the body (usually its size).
    // Nothing about retrying the same file changes that.
    if (result.status >= 400 && result.status < 500) {
      console.warn(`[Upload] Bucket rejected ${photoId} (${result.status}); discarding.`);
      return Outcome.PERMANENT;
    }
    return Outcome.RETRY;   // 5xx / SlowDown
  }

  // The bytes are in storage but no server-side state has changed yet. Until
  // confirm succeeds the photo stays original_synced=0 and the PDF export gate
  // keeps blocking, which is the correct conservative state.
  const etag = extractEtag(result.body);
  return confirmUpload(sessionId, photoId, etag);
}

/**
 * Pull the ETag out of S3's 201 response body.
 *
 * Only a diagnostic: the server re-reads the authoritative ETag with
 * head_object and logs a mismatch. Parsed with a regex rather than an XML
 * parser because the shape is fixed and a parse failure must not fail an
 * upload that already succeeded.
 */
function extractEtag(body) {
  if (!body) return null;
  const match = /<ETag>\s*&quot;?"?([^<&"]+)"?&quot;?\s*<\/ETag>/i.exec(body);
  return match ? match[1] : null;
}
