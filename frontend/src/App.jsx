import React, { useState, useEffect, useRef } from 'react';
import ToolbarHeader from './components/ToolbarHeader';
import PhotoUploader from './components/PhotoUploader';
import AIChatbotWidget from './components/AIChatbotWidget';
import BookCarousel3D from './components/BookCarousel3D';
import SpreadViewer from './components/SpreadViewer';
import BoilerplateInspector from './components/BoilerplateInspector';
import SystemStatsDashboard from './components/SystemStatsDashboard';
import PixovoClientDownsampler from './utils/client_downsampler';
import { saveOriginalBlob, getPendingBlobs, removeOriginalBlob, sweepStaleBlobs, clearAllBlobs } from './utils/indexedDB';
import { uploadOriginal, resetTransport, Outcome } from './utils/uploadTransport';
import './styles/storymode.css';

export default function App() {
  const [activeMode, setActiveMode] = useState('story'); // 'story' | 'inspector' | 'stats'
  const [step, setStep] = useState('upload'); // 'upload' -> 'chat' -> 'generating' -> 'preview'
  const [uploadedPhotos, setUploadedPhotos] = useState([]);
  const [isPhotoUploadComplete, setIsPhotoUploadComplete] = useState(false);
  const [uploadedCount, setUploadedCount] = useState(0);
  const [userPrompt, setUserPrompt] = useState('Friends at ISKCON Temple');
  const [currentJobId, setCurrentJobId] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isReshufflingVars, setIsReshufflingVars] = useState(false);
  const [jobProgress, setJobProgress] = useState(0);
  const [jobMessage, setJobMessage] = useState('');
  const [variations, setVariations] = useState([]);
  const [activeVarIdx, setActiveVarIdx] = useState(0);
  const [variationSeedOffset, setVariationSeedOffset] = useState(1);
  const [isExportingPDF, setIsExportingPDF] = useState(false);
  const [syncStatus, setSyncStatus] = useState({ synced: 0, total: 0 });

  // Stage 1.1: one stable session token for the whole upload, persisted so a
  // mid-upload refresh does not orphan the HD originals queued in IndexedDB.
  const [sessionId, setSessionId] = useState(() => {
    try {
      return sessionStorage.getItem('pixovo_session_id');
    } catch (_) {
      return null; // private browsing / storage disabled
    }
  });
  const [ingestProgress, setIngestProgress] = useState({ done: 0, total: 0, survived: 0 });

  const spreadsRef = useRef(null);
  const uploadedPhotosRef = useRef([]);
  const sessionIdRef = useRef(sessionId);
  // Survivors' original files still awaiting HD upload, so a completed job can
  // re-prioritise them by actual placement in the chosen variation.
  const originalsQueueRef = useRef({});
  const syncedIdsRef = useRef(new Set());
  // Held so a session reset can stop an in-flight job poll; otherwise it keeps
  // ticking and pushes the user back to 'preview' after the reset.
  const pollIntervalRef = useRef(null);

  const persistSessionId = (id) => {
    sessionIdRef.current = id;
    setSessionId(id);
    try {
      if (id) sessionStorage.setItem('pixovo_session_id', id);
      else sessionStorage.removeItem('pixovo_session_id');
    } catch (_) {
      /* non-fatal: upload still works, refresh-resume does not */
    }
  };

  // Rehydrate a session that survived a page refresh, so the IndexedDB
  // auto-resume below has a session to resume *into*. Previously the session_id
  // lived only in a local variable inside handlePhotosUploaded, so a refresh
  // left queued HD blobs with nowhere to go.
  useEffect(() => {
    const stored = sessionIdRef.current;
    if (!stored) return;

    (async () => {
      try {
        const res = await fetch(`/api/sessions/${stored}`);
        if (res.status === 404 || res.status === 410) {
          console.log(`[Session] Stored session ${stored} is gone; starting clean.`);
          persistSessionId(null);
          return;
        }
        if (!res.ok) return;

        const data = await res.json();
        const photos = data.photos || [];
        if (photos.length > 0) {
          uploadedPhotosRef.current = photos;
          setUploadedPhotos(photos);
          setUploadedCount(data.received_photo_count || photos.length);
          setIsPhotoUploadComplete(data.status === 'ready');
          setStep('chat');
          console.log(
            `[Session] Resumed ${stored}: ${photos.length} photos already ingested (status ${data.status}).`
          );
        }
      } catch (err) {
        console.warn('[Session] Could not rehydrate stored session:', err);
      }
    })();
  }, []);

  // Auto-Resume Unsynced HD Blobs from IndexedDB on startup / reconnect
  useEffect(() => {
    async function resumePendingSync() {
      // Evict abandoned blobs before resuming, so a stale session cannot keep
      // gigabytes of originals in browser storage indefinitely (Stage 1.3).
      await sweepStaleBlobs();
      const pending = await getPendingBlobs();
      if (!pending || pending.length === 0) return;

      console.log(`[IndexedDB Auto-Resume] Found ${pending.length} unsynced HD blobs. Resuming background upload...`);
      setSyncStatus({ synced: 0, total: pending.length });
      let count = 0;

      for (const item of pending) {
        // Each record carries the session it belongs to. A blob whose session
        // is unknown can never be attributed, so drop it rather than retrying
        // forever against a session the server will reject.
        const itemSession = item.sessionId || sessionIdRef.current;
        if (!itemSession) {
          console.warn(`[IndexedDB Auto-Resume] No session for ${item.photoId}; discarding orphaned blob.`);
          await removeOriginalBlob(item.photoId);
          continue;
        }

        try {
          // confirmFirst: the object may already be in storage from before the
          // refresh, with only the confirm call lost. Asking costs one small
          // request; assuming otherwise costs a full re-upload of up to 20MB.
          const outcome = await uploadOriginal({
            sessionId: itemSession,
            photoId: item.photoId,
            file: item.blob,
            confirmFirst: true,
          });

          if (outcome === Outcome.DONE) {
            await removeOriginalBlob(item.photoId);
            count++;
            setSyncStatus({ synced: count, total: pending.length });
          } else if (outcome === Outcome.PERMANENT) {
            // The server will never accept this blob — stop retrying it.
            console.warn(`[IndexedDB Auto-Resume] Discarding ${item.photoId}; server will never accept it.`);
            await removeOriginalBlob(item.photoId);
          }
          // Outcome.RETRY: leave the blob queued for the next `online` event.
        } catch (err) {
          console.warn(`[IndexedDB Auto-Resume] Network offline, will retry later for ${item.photoId}:`, err);
        }
      }
    }

    resumePendingSync();
    window.addEventListener('online', resumePendingSync);
    return () => window.removeEventListener('online', resumePendingSync);
  }, []);

  /**
   * Extracts every photo_id actually occupying a slot in a variation.
   * These are the only originals the PDF export needs, so they upload first.
   */
  const collectPlacedPhotoIds = (variation) => {
    if (!variation || !variation.spreads) return new Set();
    const placed = new Set();
    for (const spread of variation.spreads) {
      for (const page of [spread.left_page, spread.right_page]) {
        for (const slot of page?.slots || []) {
          if (slot.photo_id) placed.add(slot.photo_id);
        }
      }
    }
    return placed;
  };

  /**
   * Re-runs the HD upload queue with photos placed in the chosen variation
   * first, so export becomes possible as early as possible instead of waiting
   * for every survivor to finish uploading.
   */
  const prioritiseOriginalsForVariation = (variation) => {
    const sid = sessionIdRef.current;
    const queue = originalsQueueRef.current;
    if (!sid || !queue || Object.keys(queue).length === 0) return;

    const placed = collectPlacedPhotoIds(variation);
    const pending = Object.keys(queue).filter(pid => !syncedIdsRef.current.has(pid));
    if (pending.length === 0) return;

    const ordered = pending.sort((a, b) => {
      const aPlaced = placed.has(a) ? 0 : 1;
      const bPlaced = placed.has(b) ? 0 : 1;
      return aPlaced - bPlaced;
    });

    const reordered = {};
    for (const pid of ordered) reordered[pid] = queue[pid];
    console.log(
      `[Background Sync] Re-prioritised ${ordered.length} pending originals; ` +
      `${ordered.filter(p => placed.has(p)).length} are placed in the chosen variation.`
    );
    streamOriginalsInBackground(reordered, sid);
  };

  // Background HD Original Asset Sync Queue with IndexedDB Persistence
  const streamOriginalsInBackground = async (originalFilesMap, uploadSessionId) => {
    const photoIds = Object.keys(originalFilesMap).filter(
      pid => !syncedIdsRef.current.has(pid)
    );
    const total = photoIds.length;
    if (total === 0) return;
    if (!uploadSessionId) {
      console.warn('[Background Sync] No session id; skipping original upload.');
      return;
    }

    setSyncStatus({ synced: 0, total });
    let syncedCount = 0;

    // Concurrency pool of 3 parallel streams
    const concurrency = 3;
    for (let i = 0; i < photoIds.length; i += concurrency) {
      const chunk = photoIds.slice(i, i + concurrency);
      await Promise.all(chunk.map(async (photoId) => {
        const file = originalFilesMap[photoId];
        if (!file) return;

        // 1. Immediately persist original file blob to IndexedDB, tagged with
        //    its session so auto-resume can attribute it after a refresh.
        await saveOriginalBlob(photoId, file, uploadSessionId);

        try {
          // The transport negotiates with the server: direct-to-bucket when
          // that is enabled, otherwise the original multipart endpoint. Either
          // way the outcome vocabulary here is the same.
          const outcome = await uploadOriginal({
            sessionId: uploadSessionId,
            photoId,
            file,
          });

          if (outcome === Outcome.DONE) {
            await removeOriginalBlob(photoId);
            syncedIdsRef.current.add(photoId);
            syncedCount++;
            setSyncStatus({ synced: syncedCount, total });
          } else if (outcome === Outcome.PERMANENT) {
            // Wrong session, unknown photo, or over the size/quota cap. Mark it
            // synced so the queue stops offering it back.
            console.warn(`[Background Sync] Discarding ${photoId}; server will never accept it.`);
            await removeOriginalBlob(photoId);
            syncedIdsRef.current.add(photoId);
          }
          // Outcome.RETRY: the blob stays in IndexedDB for auto-resume.
        } catch (err) {
          console.warn(`[Background Sync] Will retry later for ${photoId}:`, err);
        }
      }));
    }
  };

  /**
   * Upload one ingest chunk, retrying transient failures with exponential
   * backoff. 4xx responses are permanent (bad session, oversized batch) and are
   * not retried. Chunks are idempotent server-side — INSERT OR REPLACE keyed on
   * the client-minted photo_id — so a retry cannot duplicate photos.
   */
  const uploadChunkWithRetry = async (payload, attempt = 0) => {
    const MAX_RETRIES = 3;
    try {
      const res = await fetch('/api/photobook/ingest', { method: 'POST', body: payload });
      if (res.ok) return await res.json();

      if (res.status >= 400 && res.status < 500) {
        const body = await res.json().catch(() => ({}));
        const err = new Error(body.detail || `Ingestion rejected (${res.status})`);
        err.permanent = true;
        throw err;
      }
      throw new Error(`Server error ${res.status}`);
    } catch (err) {
      if (err.permanent || attempt >= MAX_RETRIES) throw err;
      const backoffMs = 2 ** attempt * 1000; // 1s, 2s, 4s
      console.warn(`[Ingest] Chunk failed (${err.message}); retrying in ${backoffMs}ms`);
      await new Promise(r => setTimeout(r, backoffMs));
      return uploadChunkWithRetry(payload, attempt + 1);
    }
  };

  // Triggered after Phase 1 client-side downsampling completes
  const handlePhotosUploaded = async (uploadPackage) => {
    const { processedCount, processedPhotos, downsampler, downsampleTimeMs } = uploadPackage;
    setUploadedCount(processedCount);
    setIsPhotoUploadComplete(false);
    setStep('chat'); // Immediately show AI Chatbot / Theme Selector in foreground!

    // Record Client-side Downsample telemetry to backend metrics
    if (downsampleTimeMs) {
      try {
        fetch('/api/client-metrics', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            step_name: 'Client Browser Downsampling (512px)',
            elapsed_ms: downsampleTimeMs,
            details: { total_photos: processedCount }
          })
        }).catch(() => {});
      } catch (_) {}
    }

    // Build raw original files mapping for background stream
    const origMap = {};
    if (processedPhotos) {
      processedPhotos.forEach(p => {
        if (p.photo_id && p.original_file) {
          origMap[p.photo_id] = p.original_file;
        }
      });
    }

    try {
      // 1. Open ONE session before uploading anything. Every chunk below carries
      //    this token, so a 1,000-photo upload is a single session rather than
      //    one orphaned session per chunk.
      const sessionRes = await fetch('/api/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ expected_photo_count: processedCount })
      });

      if (!sessionRes.ok) {
        const body = await sessionRes.json().catch(() => ({}));
        throw new Error(body.detail || `Could not open upload session (${sessionRes.status})`);
      }

      const { session_id, chunk_size } = await sessionRes.json();
      persistSessionId(session_id);

      // 2. Upload thumbnail chunks SEQUENTIALLY. Each chunk triggers CPU-bound
      //    filtering server-side; firing all chunks at once from 20 concurrent
      //    users would swamp the filter pool. Sequential per user, concurrent
      //    across users, is the shape the backend is sized for.
      const chunks = PixovoClientDownsampler.chunk(processedPhotos, chunk_size || 40);
      setIngestProgress({ done: 0, total: chunks.length, survived: 0 });

      const allPhotos = [];
      for (let i = 0; i < chunks.length; i++) {
        const payload = downsampler.buildChunkPayload(chunks[i], session_id, i, chunks.length);
        const data = await uploadChunkWithRetry(payload);

        allPhotos.push(...(data.photos || []));
        // Publish incrementally so generation can start on early chunks and the
        // UI can show real progress rather than waiting for the whole batch.
        uploadedPhotosRef.current = allPhotos.slice();
        setUploadedPhotos(allPhotos.slice());
        setIngestProgress({
          done: i + 1,
          total: chunks.length,
          survived: data.session_survived ?? allPhotos.length
        });
      }

      setIsPhotoUploadComplete(true);
      console.log(
        `[Phase 1 Ingestion] Session ${session_id}: ${allPhotos.length} photos survived ` +
        `across ${chunks.length} chunks.`
      );

      // 3. Launch background HD streaming for SURVIVORS ONLY.
      //
      //    Stage 1.3: previously every photo's original was queued, including
      //    the ~40% the filter engine rejected. Uploading an 8MB original for a
      //    photo that will never appear in the book is pure waste — at the load
      //    target it is the difference between ~160GB and ~40GB of disk.
      const survivorIds = new Set(allPhotos.map(p => p.id));
      const survivorOrigMap = {};
      for (const [pid, file] of Object.entries(origMap)) {
        if (survivorIds.has(pid)) survivorOrigMap[pid] = file;
      }
      const skipped = Object.keys(origMap).length - Object.keys(survivorOrigMap).length;
      if (skipped > 0) {
        console.log(`[Background Sync] Skipping ${skipped} rejected photos' originals.`);
      }
      originalsQueueRef.current = survivorOrigMap;
      streamOriginalsInBackground(survivorOrigMap, session_id);
    } catch (e) {
      console.error('[Phase 1 Ingestion] Upload failed:', e);
      alert(`Ingestion error: ${e.message}`);
      setStep('upload');
      setIsPhotoUploadComplete(false);
    }
  };

  const handleGenerateVariationsAsync = async (promptOverride) => {
    // Wait for in-flight Phase 1 ingestion upload to complete if photos were selected
    let photosToUse = uploadedPhotos.length > 0 ? uploadedPhotos : uploadedPhotosRef.current;
    if (photosToUse.length === 0 && uploadedCount > 0) {
      for (let i = 0; i < 40; i++) { // wait up to 8 seconds for ingestion
        if (uploadedPhotosRef.current.length > 0) {
          photosToUse = uploadedPhotosRef.current;
          break;
        }
        await new Promise(r => setTimeout(r, 200));
      }
    }

    const promptToUse = promptOverride || userPrompt;
    setIsLoading(true);
    setStep('generating');
    setJobProgress(10);
    setJobMessage("Submitting async photobook job...");

    try {
      const photoIds = photosToUse.map(p => p.id);
      console.log(`[Generate Async] Submitting ${photoIds.length} photo IDs for prompt: '${promptToUse}'`);
      const res = await fetch('/api/generate-async', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          photo_ids: photoIds,
          user_prompt: promptToUse,
          // Lets the backend load photos with one indexed query in capture-time
          // order, instead of chunking the id list into IN (...) clauses.
          session_id: sessionIdRef.current
        })
      });

      if (res.status === 202) {
        const job = await res.json();
        setCurrentJobId(job.job_id);
        pollJobStatus(job.job_id);
      } else {
        alert("Failed to submit job");
        setIsLoading(false);
        setStep('chat');
      }
    } catch (e) {
      console.error("Generation error:", e);
      setIsLoading(false);
      setStep('chat');
    }
  };

  const pollJobStatus = (jobId) => {
    if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`/api/jobs/${jobId}`);
        if (res.ok) {
          const job = await res.json();
          setJobProgress(job.progress || 0);
          setJobMessage(job.message || "Processing...");

          if (job.status === "completed" && job.result) {
            clearInterval(interval);
            const vars = job.result.variations || [];
            setVariations(vars);
            setActiveVarIdx(0);
            setIsLoading(false);
            setStep('preview');
            // Now that we know which photos are actually placed, push their HD
            // originals to the front of the upload queue so export unblocks
            // sooner (Stage 1.3 Task 4).
            if (vars.length > 0) prioritiseOriginalsForVariation(vars[0]);
          } else if (job.status === "failed") {
            clearInterval(interval);
            alert(`Generation failed: ${job.message}`);
            setIsLoading(false);
            setStep('chat');
          }
        }
      } catch (err) {
        console.error("Polling error:", err);
      }
    }, 500);
    pollIntervalRef.current = interval;
  };

  const handleSpreadUpdate = (spreadIdx, newSpread) => {
    setVariations(prevVars => {
      const updated = [...prevVars];
      const activeVar = { ...updated[activeVarIdx] };
      const updatedSpreads = [...activeVar.spreads];
      updatedSpreads[spreadIdx] = newSpread;
      activeVar.spreads = updatedSpreads;
      updated[activeVarIdx] = activeVar;
      return updated;
    });
  };

  const handleReshuffleVariations = async () => {
    if (!currentJobId) return;
    setIsReshufflingVars(true);
    const nextOffset = variationSeedOffset + 1;
    setVariationSeedOffset(nextOffset);

    try {
      const res = await fetch('/api/variations/reshuffle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_id: currentJobId,
          seed_offset: nextOffset,
          // Required since Stage 1.6: reshuffle reloads this session's photos
          // rather than reading the process-wide cache.
          session_id: sessionIdRef.current
        })
      });

      if (res.ok) {
        const result = await res.json();
        setVariations(result.variations || []);
      }
    } catch (err) {
      console.error("Variations reshuffle error:", err);
    } finally {
      setIsReshufflingVars(false);
    }
  };

  const handleExportPDF = async () => {
    const selectedVar = variations[activeVarIdx];
    if (!selectedVar) {
      alert("No photobook variation selected for PDF export.");
      return;
    }

    setIsExportingPDF(true);
    try {
      const res = await fetch('/api/export-pdf', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          variation: selectedVar,
          page_width_mm: 200,
          page_height_mm: 200,
          bleed_mm: 3,
          dpi: 300,
          session_id: sessionIdRef.current
        })
      });

      // Stage 1.3: originals upload on demand, so a print export can be
      // requested before every placed photo's HD file has arrived. The server
      // now says so explicitly instead of quietly embedding 512px thumbnails
      // into a 300 DPI PDF.
      if (res.status === 409) {
        const body = await res.json().catch(() => ({}));
        const info = body.detail || {};
        const pending = info.pending_count ?? '?';
        const totalPlaced = info.total_count ?? '?';
        prioritiseOriginalsForVariation(selectedVar);
        alert(
          `Print files are still uploading — ${totalPlaced - pending} of ${totalPlaced} ready.\n\n` +
          `They are now being prioritised. Try the export again in a moment, ` +
          `or use Preview Export for a low-resolution proof.`
        );
        return;
      }

      if (res.ok) {
        const data = await res.json();
        if (data.pdf_url) {
          const downloadUrl = data.pdf_url.startsWith('http') ? data.pdf_url : `${window.location.origin}${data.pdf_url}`;
          const link = document.createElement('a');
          link.href = downloadUrl;
          link.target = '_blank';
          link.download = data.filename || 'pixovo_print_300dpi.pdf';
          document.body.appendChild(link);
          link.click();
          document.body.removeChild(link);
        } else {
          alert("PDF compiled successfully!");
        }
      } else {
        const err = await res.json();
        alert(`PDF Export Error: ${err.detail || 'Failed to compile PDF'}`);
      }
    } catch (e) {
      console.error("PDF Export Error:", e);
      alert("PDF Export failed. Check backend log.");
    } finally {
      setIsExportingPDF(false);
    }
  };

  /**
   * Hard reset back to the upload screen.
   *
   * There is otherwise no way to start a second album without reloading the
   * tab: the session id is persisted in sessionStorage and rehydrated on
   * mount, so a plain refresh drops the user straight back into 'chat'.
   * Clearing the stored id, the queued originals and every derived piece of
   * state is what actually makes step === 'upload' reachable again.
   */
  const handleClearSession = async () => {
    const hasWork = uploadedCount > 0 || variations.length > 0;
    if (hasWork && !window.confirm('Clear this session and start a new album? Uploaded photos and generated layouts will be discarded.')) {
      return;
    }

    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }

    persistSessionId(null);
    await clearAllBlobs();
    // The direct-upload circuit breaker is per session, not per page load: a
    // bucket CORS policy fixed between sessions should take effect on the next
    // upload rather than requiring a refresh.
    resetTransport();

    uploadedPhotosRef.current = [];
    originalsQueueRef.current = {};
    syncedIdsRef.current = new Set();

    setUploadedPhotos([]);
    setUploadedCount(0);
    setIsPhotoUploadComplete(false);
    setIngestProgress({ done: 0, total: 0, survived: 0 });
    setSyncStatus({ synced: 0, total: 0 });
    setVariations([]);
    setActiveVarIdx(0);
    setVariationSeedOffset(1);
    setCurrentJobId(null);
    setJobProgress(0);
    setJobMessage('');
    setIsLoading(false);
    setIsExportingPDF(false);
    setIsReshufflingVars(false);
    setActiveMode('story');
    setStep('upload');

    console.log('[Session] Cleared; ready for a new upload.');
  };

  const scrollToSpreads = () => {
    if (spreadsRef.current) {
      spreadsRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  };

  return (
    <div className="app-container">
      <ToolbarHeader 
        activeMode={activeMode} 
        setActiveMode={setActiveMode}
        onExportPDF={step === 'preview' ? handleExportPDF : null}
        isExporting={isExportingPDF}
        syncStatus={syncStatus}
        onClearSession={handleClearSession}
        canClearSession={step !== 'upload' || uploadedCount > 0}
      />

      <main className="main-wrapper">
        {activeMode === 'inspector' && (
          <BoilerplateInspector />
        )}

        {activeMode === 'stats' && (
          <SystemStatsDashboard />
        )}

        {activeMode === 'story' && (
          <>
            {step === 'generating' && (
              <div className="step-card" style={{ textAlign: 'center', padding: '3rem' }}>
                <h3 style={{ marginBottom: '1rem', color: '#1F2937' }}>{jobMessage}</h3>
                <div style={{
                  width: '100%',
                  height: '10px',
                  background: '#E5E7EB',
                  borderRadius: '5px',
                  overflow: 'hidden',
                  marginTop: '1.5rem'
                }}>
                  <div style={{
                    width: `${jobProgress}%`,
                    height: '100%',
                    background: 'linear-gradient(90deg, #8B5CF6, #EC4899)',
                    transition: 'width 0.3s ease'
                  }} />
                </div>
                <p style={{ marginTop: '0.75rem', color: '#6B7280', fontSize: '0.9rem' }}>{jobProgress}% completed</p>
              </div>
            )}

            {step === 'upload' && (
              <PhotoUploader 
                onPhotosUploaded={handlePhotosUploaded} 
                isUploading={isLoading} 
              />
            )}

            {step === 'chat' && (
              <AIChatbotWidget
                userPrompt={userPrompt}
                setUserPrompt={setUserPrompt}
                onGenerate={handleGenerateVariationsAsync}
                isPhotoUploadComplete={isPhotoUploadComplete}
                uploadedCount={uploadedCount}
                isLoading={isLoading}
              />
            )}

            {step === 'preview' && (
              <div className="story-preview-container">
                <BookCarousel3D
                  variations={variations}
                  activeIdx={activeVarIdx}
                  setActiveIdx={setActiveVarIdx}
                  onScrollDown={scrollToSpreads}
                  onReshuffleVariations={handleReshuffleVariations}
                  isReshuffling={isReshufflingVars}
                />

                <SpreadViewer
                  selectedVariation={variations[activeVarIdx]}
                  targetRef={spreadsRef}
                  onSpreadUpdate={handleSpreadUpdate}
                />
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
