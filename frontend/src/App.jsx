import React, { useState, useEffect, useRef } from 'react';
import { Sparkles, Check, Clock, RefreshCw } from 'lucide-react';
import ToolbarHeader from './components/ToolbarHeader';
import PhotoUploader from './components/PhotoUploader';
import AIChatbotWidget from './components/AIChatbotWidget';
import BookCarousel3D from './components/BookCarousel3D';
import SpreadViewer from './components/SpreadViewer';
import PixovoClientDownsampler from './utils/client_downsampler';
import { saveOriginalBlob, getPendingBlobs, removeOriginalBlob, sweepStaleBlobs, clearAllBlobs } from './utils/indexedDB';
import { uploadOriginal, resetTransport, Outcome } from './utils/uploadTransport';
import './styles/storymode.css';

const SYNTHESIS_STAGES = [
  {
    id: 1,
    copy: 'Scanning visual balance, exposure & focal sharpness',
    minProgress: 0,
    completeAt: 20
  },
  {
    id: 2,
    copy: 'Curating 5-role semantic color harmonies',
    minProgress: 20,
    completeAt: 45
  },
  {
    id: 3,
    copy: 'DSA Solver computing golden-ratio double spread bounds',
    minProgress: 45,
    completeAt: 70
  },
  {
    id: 4,
    copy: 'Binding cover jacket & 300 DPI pre-flight quality check',
    minProgress: 70,
    completeAt: 100
  }
];

const MICRO_FACTS = [
  '2-Tier temporal & pHash clustering preserves chronological narrative order.',
  'DSA Layout Solver evaluates golden-ratio double-page partitions per spread.',
  '300 DPI pre-flight validation checks effective print resolution on every frame.',
  'Hero cover selector guarantees non-overlapping cover photography across all 3 editions.'
];

export default function App() {
  const [step, setStep] = useState('upload'); // 'upload' -> 'chat' -> 'generating' -> 'preview'
  const [uploadedPhotos, setUploadedPhotos] = useState([]);
  const [isPhotoUploadComplete, setIsPhotoUploadComplete] = useState(false);
  const [uploadedCount, setUploadedCount] = useState(0);
  const [userPrompt, setUserPrompt] = useState('');
  const [studioPrefs, setStudioPrefs] = useState({
    custom_title: null,
    include_text: true,
    subtitle: null,
    use_photo_vision: false
  });
  const [currentJobId, setCurrentJobId] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isReshufflingVars, setIsReshufflingVars] = useState(false);
  const [jobProgress, setJobProgress] = useState(0);
  const [jobStatus, setJobStatus] = useState('idle');
  const [jobMessage, setJobMessage] = useState('');
  const [displayProgress, setDisplayProgress] = useState(0);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [factIndex, setFactIndex] = useState(0);
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

  // Smooth stage-bounded visual progress interpolation + live elapsed timer + micro-facts ticker
  useEffect(() => {
    if (step !== 'generating') {
      setElapsedSeconds(0);
      return;
    }

    const startTs = performance.now();
    const timerInterval = setInterval(() => {
      setElapsedSeconds(((performance.now() - startTs) / 1000).toFixed(1));
    }, 100);

    const factInterval = setInterval(() => {
      setFactIndex((prev) => (prev + 1) % MICRO_FACTS.length);
    }, 2800);

    return () => {
      clearInterval(timerInterval);
      clearInterval(factInterval);
    };
  }, [step]);

  // Interpolate displayProgress smoothly (min 250ms per visual tick) within the
  // current stage's range without ever crossing the stage's upper checkpoint
  // until real jobProgress has reached it.
  useEffect(() => {
    if (step !== 'generating') return;

    const getCeilingForRealProgress = (realProg, status) => {
      if (status === 'completed' && realProg >= 100) return 100;
      if (realProg < 20) return 19;
      if (realProg < 45) return 44;
      if (realProg < 70) return 69;
      return 98;
    };

    const tick = setInterval(() => {
      setDisplayProgress((prev) => {
        const ceiling = getCeilingForRealProgress(jobProgress, jobStatus);
        if (prev < jobProgress) {
          return Math.min(ceiling, Math.max(jobProgress, prev + 4));
        }
        if (prev < ceiling) {
          return prev + 1;
        }
        return prev;
      });
    }, 260);

    return () => clearInterval(tick);
  }, [step, jobProgress, jobStatus]);

  // Rehydrate a session that survived a page refresh, so the IndexedDB
  // auto-resume below has a session to resume *into*.
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
      await sweepStaleBlobs();
      const pending = await getPendingBlobs();
      if (!pending || pending.length === 0) return;

      console.log(`[IndexedDB Auto-Resume] Found ${pending.length} unsynced HD blobs. Resuming background upload...`);
      setSyncStatus({ synced: 0, total: pending.length });
      let count = 0;

      for (const item of pending) {
        const itemSession = item.sessionId || sessionIdRef.current;
        if (!itemSession) {
          console.warn(`[IndexedDB Auto-Resume] No session for ${item.photoId}; discarding orphaned blob.`);
          await removeOriginalBlob(item.photoId);
          continue;
        }

        try {
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
            console.warn(`[IndexedDB Auto-Resume] Discarding ${item.photoId}; server will never accept it.`);
            await removeOriginalBlob(item.photoId);
          }
        } catch (err) {
          console.warn(`[IndexedDB Auto-Resume] Network offline, will retry later for ${item.photoId}:`, err);
        }
      }
    }

    resumePendingSync();
    window.addEventListener('online', resumePendingSync);
    return () => window.removeEventListener('online', resumePendingSync);
  }, []);

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

    const concurrency = 3;
    for (let i = 0; i < photoIds.length; i += concurrency) {
      const chunk = photoIds.slice(i, i + concurrency);
      await Promise.all(chunk.map(async (photoId) => {
        const file = originalFilesMap[photoId];
        if (!file) return;

        await saveOriginalBlob(photoId, file, uploadSessionId);

        try {
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
            console.warn(`[Background Sync] Discarding ${photoId}; server will never accept it.`);
            await removeOriginalBlob(photoId);
            syncedIdsRef.current.add(photoId);
          }
        } catch (err) {
          console.warn(`[Background Sync] Will retry later for ${photoId}:`, err);
        }
      }));
    }
  };

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
      const backoffMs = 2 ** attempt * 1000;
      console.warn(`[Ingest] Chunk failed (${err.message}); retrying in ${backoffMs}ms`);
      await new Promise(r => setTimeout(r, backoffMs));
      return uploadChunkWithRetry(payload, attempt + 1);
    }
  };

  const handlePhotosUploaded = async (uploadPackage) => {
    const { processedCount, processedPhotos, downsampler, downsampleTimeMs } = uploadPackage;
    setUploadedCount(processedCount);
    setIsPhotoUploadComplete(false);
    setStep('chat');

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

    const origMap = {};
    if (processedPhotos) {
      processedPhotos.forEach(p => {
        if (p.photo_id && p.original_file) {
          origMap[p.photo_id] = p.original_file;
        }
      });
    }

    try {
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

      const chunks = PixovoClientDownsampler.chunk(processedPhotos, chunk_size || 40);
      setIngestProgress({ done: 0, total: chunks.length, survived: 0 });

      const allPhotos = [];
      for (let i = 0; i < chunks.length; i++) {
        const payload = downsampler.buildChunkPayload(chunks[i], session_id, i, chunks.length);
        const data = await uploadChunkWithRetry(payload);

        allPhotos.push(...(data.photos || []));
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

  const handleGenerateVariationsAsync = async (promptOverride, options = {}) => {
    let photosToUse = uploadedPhotos.length > 0 ? uploadedPhotos : uploadedPhotosRef.current;
    if (photosToUse.length === 0 && uploadedCount > 0) {
      for (let i = 0; i < 40; i++) {
        if (uploadedPhotosRef.current.length > 0) {
          photosToUse = uploadedPhotosRef.current;
          break;
        }
        await new Promise(r => setTimeout(r, 200));
      }
    }

    const promptToUse = promptOverride !== undefined ? promptOverride : userPrompt;
    const nextPrefs = {
      custom_title: options.custom_title !== undefined ? options.custom_title : studioPrefs.custom_title,
      include_text: options.include_text !== undefined ? options.include_text : studioPrefs.include_text,
      subtitle: options.subtitle !== undefined ? options.subtitle : studioPrefs.subtitle,
      use_photo_vision: options.use_photo_vision !== undefined ? options.use_photo_vision : studioPrefs.use_photo_vision
    };
    setStudioPrefs(nextPrefs);

    setIsLoading(true);
    setStep('generating');
    setJobStatus('processing');
    setJobProgress(10);
    setDisplayProgress(8);
    setJobMessage('Submitting async photobook job...');

    try {
      const photoIds = photosToUse.map(p => p.id);
      console.log(`[Generate Async] Submitting ${photoIds.length} photo IDs for prompt: '${promptToUse}'`);
      const res = await fetch('/api/generate-async', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          photo_ids: photoIds,
          user_prompt: promptToUse,
          session_id: sessionIdRef.current,
          custom_title: nextPrefs.custom_title,
          include_text: nextPrefs.include_text,
          subtitle: nextPrefs.subtitle,
          use_photo_vision: nextPrefs.use_photo_vision
        })
      });

      if (res.status === 202) {
        const job = await res.json();
        setCurrentJobId(job.job_id);
        pollJobStatus(job.job_id);
      } else {
        alert('Failed to submit job');
        setIsLoading(false);
        setJobStatus('failed');
        setStep('chat');
      }
    } catch (e) {
      console.error('Generation error:', e);
      setIsLoading(false);
      setJobStatus('failed');
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
          setJobStatus(job.status || 'processing');
          setJobMessage(job.message || 'Processing...');

          if (job.status === 'completed' && job.result) {
            clearInterval(interval);
            setDisplayProgress(100);
            const vars = job.result.variations || [];
            setVariations(vars);
            setActiveVarIdx(0);
            setIsLoading(false);
            setStep('preview');
            if (vars.length > 0) prioritiseOriginalsForVariation(vars[0]);
          } else if (job.status === 'failed') {
            clearInterval(interval);
            alert(`Generation failed: ${job.message}`);
            setIsLoading(false);
            setStep('chat');
          }
        }
      } catch (err) {
        console.error('Polling error:', err);
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
          session_id: sessionIdRef.current
        })
      });

      if (res.ok) {
        const result = await res.json();
        setVariations(result.variations || []);
      }
    } catch (err) {
      console.error('Variations reshuffle error:', err);
    } finally {
      setIsReshufflingVars(false);
    }
  };

  const handleExportPDF = async () => {
    const selectedVar = variations[activeVarIdx];
    if (!selectedVar) {
      alert('No photobook variation selected for PDF export.');
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
          alert('PDF compiled successfully!');
        }
      } else {
        const err = await res.json();
        alert(`PDF Export Error: ${err.detail || 'Failed to compile PDF'}`);
      }
    } catch (e) {
      console.error('PDF Export Error:', e);
      alert('PDF Export failed. Check backend log.');
    } finally {
      setIsExportingPDF(false);
    }
  };

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
    setDisplayProgress(0);
    setJobStatus('idle');
    setJobMessage('');
    setUserPrompt('');
    setStudioPrefs({ custom_title: null, include_text: true, subtitle: null, use_photo_vision: false });
    setIsLoading(false);
    setIsExportingPDF(false);
    setIsReshufflingVars(false);
    setStep('upload');

    console.log('[Session] Cleared; ready for a new upload.');
  };

  const scrollToSpreads = () => {
    if (spreadsRef.current) {
      spreadsRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  };

  // Determine each synthesis stage's state strictly from real jobProgress / jobStatus
  const getSynthesisStageState = (stage) => {
    if (stage.id === 4) {
      if (jobStatus === 'completed' && jobProgress >= 100) return 'complete';
      if (jobProgress >= 70) return 'active';
      return 'pending';
    }
    if (jobProgress >= stage.completeAt) return 'complete';
    if (jobProgress >= stage.minProgress) return 'active';
    return 'pending';
  };

  return (
    <div className="app-container">
      <ToolbarHeader
        onExportPDF={step === 'preview' ? handleExportPDF : null}
        isExporting={isExportingPDF}
        syncStatus={syncStatus}
        onClearSession={handleClearSession}
        canClearSession={step !== 'upload' || uploadedCount > 0}
      />

      <main className="main-wrapper">
        {step === 'generating' && (
          <div className="step-card synthesis-loader-card">
            <div className="synthesis-top-row">
              <div className="synthesis-orb-wrapper">
                <div className="synthesis-pulse-ring" />
                <div className="synthesis-rotate-ring" />
                <div className="synthesis-orb-core">
                  <Sparkles size={20} strokeWidth={1.75} color="var(--px-brand-iris)" />
                </div>
              </div>

              <div className="synthesis-title-group">
                <span className="synthesis-eyebrow">Pixovo Editorial Engine</span>
                <h3>Synthesizing Your Photobook Editions</h3>
                <p>{jobMessage || 'Processing layout intelligence...'}</p>
              </div>

              <div className="synthesis-timer-pill">
                <Clock size={14} strokeWidth={1.75} />
                <span>{elapsedSeconds}s</span>
              </div>
            </div>

            {/* Smoothly Interpolated Progress Track Bound to Real Checkpoints */}
            <div className="synthesis-progress-track">
              <div
                className="synthesis-progress-fill"
                style={{ width: `${displayProgress}%` }}
              />
            </div>
            <div className="synthesis-progress-meta">
              <span>Checkpoint Progress</span>
              <span>{displayProgress}%</span>
            </div>

            {/* 4-Stage Milestone List Strictly Gated by Real Backend Progress */}
            <div className="synthesis-stage-list">
              {SYNTHESIS_STAGES.map((stage) => {
                const state = getSynthesisStageState(stage);
                return (
                  <div key={stage.id} className={`synthesis-stage-item ${state}`}>
                    <div className="synthesis-stage-icon">
                      {state === 'complete' ? (
                        <Check size={14} strokeWidth={2.5} />
                      ) : state === 'active' ? (
                        <RefreshCw size={14} strokeWidth={2} className="animate-spin" />
                      ) : (
                        <span>0{stage.id}</span>
                      )}
                    </div>
                    <div className="synthesis-stage-copy">{stage.copy}</div>
                    <div className="synthesis-stage-badge">
                      {state === 'complete'
                        ? 'Verified'
                        : state === 'active'
                        ? 'In Progress'
                        : 'Queued'}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Rotating Micro-Facts Ticker */}
            <div className="synthesis-fact-ticker" key={factIndex}>
              <span>{MICRO_FACTS[factIndex]}</span>
            </div>
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
            sessionId={sessionId}
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
              sessionId={sessionId}
            />
          </div>
        )}
      </main>
    </div>
  );
}
