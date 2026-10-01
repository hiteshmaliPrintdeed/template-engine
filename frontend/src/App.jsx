import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Sparkles, Check, Clock, RefreshCw } from 'lucide-react';
import ToolbarHeader from './components/ToolbarHeader';
import PhotoUploader from './components/PhotoUploader';
import AIChatbotWidget from './components/AIChatbotWidget';
import BookCarousel3D from './components/BookCarousel3D';
import SpreadViewer from './components/SpreadViewer';
import PhotoFrame from './components/PhotoFrame';
import CapacityGate from './components/CapacityGate';
import { ToastProvider, useToast } from './components/Toast';
import PixovoClientDownsampler from './utils/client_downsampler';
import useJobProgress from './hooks/useJobProgress';
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

const MAX_CURATION_STRIP_TILES = 48;

function AppContent() {
  const toast = useToast();
  const [step, setStep] = useState('upload'); // 'upload' -> 'chat' -> 'generating' -> 'preview'
  const [uploadedPhotos, setUploadedPhotos] = useState([]);
  const [localPreviews, setLocalPreviews] = useState([]);
  const [serverPhotos, setServerPhotos] = useState({});
  const [isPhotoUploadComplete, setIsPhotoUploadComplete] = useState(false);
  const [uploadedCount, setUploadedCount] = useState(0);
  const [capacityState, setCapacityState] = useState(null); // { position, retryIn, attempt, uploadPackage }
  const [userPrompt, setUserPrompt] = useState('');
  const [studioPrefs, setStudioPrefs] = useState({
    custom_title: null,
    include_text: true,
    subtitle: null,
    use_photo_vision: false
  });
  const [currentJobId, setCurrentJobId] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isWaitingForIngest, setIsWaitingForIngest] = useState(false);
  const [isReshufflingVars, setIsReshufflingVars] = useState(false);
  const [jobProgress, setJobProgress] = useState(0);
  const [jobStatus, setJobStatus] = useState('idle');
  const [jobMessage, setJobMessage] = useState('');
  const [skeletonThemes, setSkeletonThemes] = useState(null);
  const [displayProgress, setDisplayProgress] = useState(0);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [factIndex, setFactIndex] = useState(0);
  const [variations, setVariations] = useState([]);
  const [activeVarIdx, setActiveVarIdx] = useState(0);
  const [variationSeedOffset, setVariationSeedOffset] = useState(1);
  const [isExportingPDF, setIsExportingPDF] = useState(false);
  const [syncStatus, setSyncStatus] = useState({ synced: 0, total: 0 });
  const [storySessionKey, setStorySessionKey] = useState(0);

  const [sessionId, setSessionId] = useState(() => {
    try {
      return sessionStorage.getItem('pixovo_session_id');
    } catch (_) {
      return null;
    }
  });
  const [ingestProgress, setIngestProgress] = useState({
    done: 0,
    total: 0,
    received: 0,
    survived: 0
  });

  const spreadsRef = useRef(null);
  const uploadedPhotosRef = useRef([]);
  const isIngestingRef = useRef(false);
  const localPreviewsRef = useRef([]);
  const sessionIdRef = useRef(sessionId);
  const originalsQueueRef = useRef({});
  const syncedIdsRef = useRef(new Set());

  const persistSessionId = (id) => {
    sessionIdRef.current = id;
    setSessionId(id);
    try {
      if (id) sessionStorage.setItem('pixovo_session_id', id);
      else sessionStorage.removeItem('pixovo_session_id');
    } catch (_) {}
  };

  // Stage 2.4 Task 7: Reflect live progress in document.title for backgrounded tabs
  useEffect(() => {
    if (step === 'generating') {
      document.title = `Designing… ${displayProgress}% · Pixovo`;
    } else if (step === 'chat' && !isPhotoUploadComplete && uploadedCount > 0) {
      document.title = `Curating… ${ingestProgress.received}/${uploadedCount} · Pixovo`;
    } else if (step === 'preview' && variations[activeVarIdx]) {
      document.title = `${variations[activeVarIdx].cover_title || 'Album Preview'} · Pixovo`;
    } else {
      document.title = 'Pixovo — Editorial Photobook Studio';
    }
  }, [step, displayProgress, isPhotoUploadComplete, uploadedCount, ingestProgress.received, variations, activeVarIdx]);

  // Stage 2.3 Task 1: Reconcile optimistic local blob URLs with server PhotoMeta
  const reconciledPhotos = useMemo(() => {
    if (localPreviews.length > 0) {
      return localPreviews.map((lp) => {
        const server = serverPhotos[lp.photo_id];
        return {
          ...lp,
          url: server?.url || lp.previewUrl,
          status: server ? (server.rejected ? 'rejected' : 'kept') : 'pending',
          reject_reason: server?.reject_reason || null,
          dominant_colors: server?.dominant_colors || null,
        };
      });
    }
    return uploadedPhotos.map((sp) => ({
      photo_id: sp.id,
      filename: sp.filename,
      aspect_ratio: sp.aspect_ratio || 1,
      url: sp.url || sp.preview_url,
      status: 'kept',
      reject_reason: null,
      dominant_colors: sp.dominant_colors || null,
    }));
  }, [localPreviews, serverPhotos, uploadedPhotos]);

  // Stage 2.3 Task 1: Free each local blob URL only once its server URL is in use
  useEffect(() => {
    const knownIds = Object.keys(serverPhotos);
    if (knownIds.length === 0 || localPreviewsRef.current.length === 0) return;

    let changed = false;
    const nextPreviews = localPreviewsRef.current.map((lp) => {
      const server = serverPhotos[lp.photo_id];
      if (server?.url && lp.previewUrl) {
        URL.revokeObjectURL(lp.previewUrl);
        changed = true;
        return { ...lp, previewUrl: null };
      }
      return lp;
    });

    if (changed) {
      localPreviewsRef.current = nextPreviews;
      setLocalPreviews(nextPreviews);
    }
  }, [serverPhotos]);

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
    const pending = Object.keys(queue).filter((pid) => !syncedIdsRef.current.has(pid));
    if (pending.length === 0) return;

    const ordered = pending.sort((a, b) => {
      const aPlaced = placed.has(a) ? 0 : 1;
      const bPlaced = placed.has(b) ? 0 : 1;
      return aPlaced - bPlaced;
    });

    const reordered = {};
    for (const pid of ordered) reordered[pid] = queue[pid];
    streamOriginalsInBackground(reordered, sid);
  };

  // Stage 2.2 Task 4: Subscribe to real-time SSE job progress via useJobProgress hook
  const sseState = useJobProgress(currentJobId, {
    onComplete: (job) => {
      setDisplayProgress(100);
      setJobProgress(100);
      setJobStatus('completed');
      const vars = job?.result?.variations || [];
      setVariations(vars);
      setActiveVarIdx(0);
      setIsLoading(false);
      setStep('preview');
      if (vars.length > 0) prioritiseOriginalsForVariation(vars[0]);
    },
    onError: (job) => {
      toast.show({
        title: 'We couldn\'t complete your album',
        message: job?.message || 'An unexpected layout error occurred.',
        tone: 'error',
        action: {
          label: 'Upload Again',
          onClick: () => setStep('upload')
        }
      });
      setIsLoading(false);
      setJobStatus('failed');
      setStep('chat');
    },
  });

  useEffect(() => {
    if (!currentJobId) return;
    if (sseState.progress) setJobProgress(sseState.progress);
    if (sseState.status) setJobStatus(sseState.status);
    if (sseState.message) setJobMessage(sseState.message);
    if (sseState.themes) setSkeletonThemes(sseState.themes);
  }, [currentJobId, sseState]);

  // Elapsed timer + micro-facts ticker using setTimeout chains
  useEffect(() => {
    if (step !== 'generating') {
      setElapsedSeconds(0);
      return undefined;
    }

    let active = true;
    const startTs = performance.now();
    let timerId = null;
    let factId = null;

    const tickTimer = () => {
      if (!active) return;
      setElapsedSeconds(((performance.now() - startTs) / 1000).toFixed(1));
      timerId = setTimeout(tickTimer, 100);
    };

    const tickFact = () => {
      if (!active) return;
      setFactIndex((prev) => (prev + 1) % MICRO_FACTS.length);
      factId = setTimeout(tickFact, 2800);
    };

    timerId = setTimeout(tickTimer, 100);
    factId = setTimeout(tickFact, 2800);

    return () => {
      active = false;
      if (timerId) clearTimeout(timerId);
      if (factId) clearTimeout(factId);
    };
  }, [step]);

  // Smoothly interpolate displayProgress within the current checkpoint range
  useEffect(() => {
    if (step !== 'generating') return undefined;

    let active = true;
    let tickId = null;

    const getCeilingForRealProgress = (realProg, status) => {
      if (status === 'completed' && realProg >= 100) return 100;
      if (realProg < 20) return 19;
      if (realProg < 45) return 44;
      if (realProg < 70) return 69;
      return 98;
    };

    const stepDisplay = () => {
      if (!active) return;
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
      tickId = setTimeout(stepDisplay, 260);
    };

    tickId = setTimeout(stepDisplay, 260);
    return () => {
      active = false;
      if (tickId) clearTimeout(tickId);
    };
  }, [step, jobProgress, jobStatus]);

  // Rehydrate a session that survived a page refresh
  useEffect(() => {
    const stored = sessionIdRef.current;
    if (!stored) return;

    (async () => {
      try {
        const res = await fetch(`/api/sessions/${stored}`);
        if (res.status === 404 || res.status === 410) {
          persistSessionId(null);
          return;
        }
        if (!res.ok) return;

        const data = await res.json();
        const photos = data.photos || [];
        if (photos.length > 0) {
          uploadedPhotosRef.current = photos;
          setUploadedPhotos(photos);
          const photoMap = {};
          photos.forEach((p) => {
            photoMap[p.id] = p;
          });
          setServerPhotos(photoMap);
          setUploadedCount(data.received_photo_count || photos.length);
          setIngestProgress({
            done: 1,
            total: 1,
            received: data.received_photo_count || photos.length,
            survived: data.survived_photo_count || photos.length
          });
          setIsPhotoUploadComplete(data.status === 'ready');
          setStep('chat');
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

      setSyncStatus({ synced: 0, total: pending.length });
      let count = 0;

      for (const item of pending) {
        const itemSession = item.sessionId || sessionIdRef.current;
        if (!itemSession) {
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
            await removeOriginalBlob(item.photoId);
          }
        } catch (err) {
          console.warn(`[IndexedDB Auto-Resume] Retry later for ${item.photoId}:`, err);
        }
      }
    }

    resumePendingSync();
    window.addEventListener('online', resumePendingSync);
    return () => window.removeEventListener('online', resumePendingSync);
  }, []);

  const streamOriginalsInBackground = async (originalFilesMap, uploadSessionId) => {
    const photoIds = Object.keys(originalFilesMap).filter(
      (pid) => !syncedIdsRef.current.has(pid)
    );
    const total = photoIds.length;
    if (total === 0 || !uploadSessionId) return;

    setSyncStatus({ synced: 0, total });
    let syncedCount = 0;

    const concurrency = 3;
    for (let i = 0; i < photoIds.length; i += concurrency) {
      const chunk = photoIds.slice(i, i + concurrency);
      await Promise.all(
        chunk.map(async (photoId) => {
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
              await removeOriginalBlob(photoId);
              syncedIdsRef.current.add(photoId);
            }
          } catch (err) {
            console.warn(`[Background Sync] Will retry later for ${photoId}:`, err);
          }
        })
      );
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
      await new Promise((r) => setTimeout(r, backoffMs));
      return uploadChunkWithRetry(payload, attempt + 1);
    }
  };

  const normalizeRejectReason = (item) => {
    const raw = (item?.reject_reason || item?.reason || item?.status || 'rejected').toLowerCase();
    if (raw.includes('blur')) return 'blurry';
    if (raw.includes('dup')) return 'duplicate';
    if (raw.includes('exposure') || raw.includes('dark') || raw.includes('bright') || raw.includes('contrast')) return 'exposure';
    if (raw.includes('qr') || raw.includes('doc') || raw.includes('screen') || raw.includes('text')) return 'junk';
    return 'filtered';
  };

  const summarizeRejections = (reasonsList) => {
    if (!reasonsList || reasonsList.length === 0) return 'quality thresholds not met';
    const counts = {};
    reasonsList.forEach((r) => {
      counts[r] = (counts[r] || 0) + 1;
    });
    return Object.entries(counts)
      .map(([reason, count]) => `${count} ${reason}`)
      .join(', ');
  };

  const handlePhotosUploaded = async (uploadPackage, attemptNumber = 1) => {
    const { processedCount, processedPhotos, previewItems = [], downsampler, downsampleTimeMs } = uploadPackage;
    setUploadedCount(processedCount);
    setIsPhotoUploadComplete(false);
    setCapacityState(null);

    if (attemptNumber === 1) {
      localPreviewsRef.current = previewItems;
      setLocalPreviews(previewItems);
      setServerPhotos({});
    }

    if (downsampleTimeMs && attemptNumber === 1) {
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
      processedPhotos.forEach((p) => {
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

      // Stage 2.4 Task 3: Render calm CapacityGate queue panel on 503 with auto-retry
      if (sessionRes.status === 503) {
        const body = await sessionRes.json().catch(() => ({}));
        const detailObj = typeof body.detail === 'object' && body.detail !== null ? body.detail : body;
        const queuePosition = detailObj.queue_position || 1;
        const retryAfter = (detailObj.retry_after_seconds || 15) + Math.floor(Math.random() * 3);
        setCapacityState({
          position: queuePosition,
          retryIn: retryAfter,
          attempt: attemptNumber,
          uploadPackage,
        });
        return;
      }

      if (!sessionRes.ok) {
        const body = await sessionRes.json().catch(() => ({}));
        throw new Error(body.detail || `Could not open upload session (${sessionRes.status})`);
      }

      const { session_id, chunk_size } = await sessionRes.json();
      persistSessionId(session_id);
      setStep('chat');

      const chunks = PixovoClientDownsampler.chunk(processedPhotos, chunk_size || 40);
      setIngestProgress({ done: 0, total: chunks.length, received: 0, survived: 0 });
      isIngestingRef.current = true;

      const allPhotos = [];
      const allRejectReasons = [];

      for (let i = 0; i < chunks.length; i++) {
        try {
          const payload = downsampler.buildChunkPayload(chunks[i], session_id, i, chunks.length);
          const data = await uploadChunkWithRetry(payload);

          const chunkSurvived = data.photos || [];
          const chunkRejected = data.rejected_photos || [];

          allPhotos.push(...chunkSurvived);
          uploadedPhotosRef.current = allPhotos.slice();
          setUploadedPhotos(allPhotos.slice());

          setServerPhotos((prev) => {
            const next = { ...prev };
            chunkSurvived.forEach((p) => {
              next[p.id] = { ...p, rejected: false };
            });
            chunkRejected.forEach((r) => {
              const reason = normalizeRejectReason(r);
              allRejectReasons.push(reason);
              const rid = r.photo_id || (r.filename ? r.filename.replace(/_thumb\.\w+$/, '') : null);
              if (rid) {
                next[rid] = {
                  id: rid,
                  rejected: true,
                  reject_reason: reason,
                };
              }
            });
            return next;
          });

          setIngestProgress({
            done: i + 1,
            total: chunks.length,
            received: data.session_received ?? Math.min(processedCount, (i + 1) * (chunk_size || 40)),
            survived: data.session_survived ?? allPhotos.length
          });
        } catch (chunkErr) {
          // Stage 2.4 Task 1 & 4: Non-blocking toast during chunked upload so remaining chunks continue
          console.error(`[Ingest] Chunk ${i + 1}/${chunks.length} failed:`, chunkErr);
          toast.show({
            title: 'Connection interrupted',
            message: `Batch ${i + 1} of ${chunks.length} could not be uploaded (${chunkErr.message}). Uploaded photos are safe.`,
            tone: 'warning',
          });
        }
      }

      isIngestingRef.current = false;

      // Stage 2.4 Task 4: Actionable error when all photos were filtered out
      if (allPhotos.length === 0) {
        const summaryText = summarizeRejections(allRejectReasons);
        toast.show({
          title: 'All photos were filtered out',
          message: `All ${processedCount} photos were rejected (${summaryText}). Review the dimmed tiles above or upload different photos.`,
          tone: 'error',
          action: {
            label: 'Upload Different Photos',
            onClick: () => setStep('upload')
          }
        });
        setIsPhotoUploadComplete(false);
        return;
      }

      setIsPhotoUploadComplete(true);

      const survivorIds = new Set(allPhotos.map((p) => p.id));
      const survivorOrigMap = {};
      for (const [pid, file] of Object.entries(origMap)) {
        if (survivorIds.has(pid)) survivorOrigMap[pid] = file;
      }
      originalsQueueRef.current = survivorOrigMap;
      streamOriginalsInBackground(survivorOrigMap, session_id);
    } catch (e) {
      isIngestingRef.current = false;
      console.error('[Phase 1 Ingestion] Upload failed:', e);
      toast.show({
        title: 'Upload session could not start',
        message: e.message || 'Check your connection and try again.',
        tone: 'error',
        action: {
          label: 'Retry Upload',
          onClick: () => handlePhotosUploaded(uploadPackage, attemptNumber + 1)
        }
      });
      setStep('upload');
      setIsPhotoUploadComplete(false);
    }
  };

  const handleGenerateVariationsAsync = async (promptOverride, options = {}) => {
    if (isLoading || isWaitingForIngest) return; // Prevent double-submit

    let photosToUse = uploadedPhotos.length > 0 ? uploadedPhotos : uploadedPhotosRef.current;
    if (isIngestingRef.current || (photosToUse.length === 0 && !isPhotoUploadComplete && uploadedCount > 0)) {
      setIsWaitingForIngest(true);
      toast.show({
        title: 'Finishing photo curation...',
        message: 'Generation will start automatically as soon as your photos finish uploading.',
        tone: 'info',
      });
      // Wait up to 150 seconds for mobile/ngrok thumbnail ingestion to complete
      for (let i = 0; i < 600; i++) {
        if (!isIngestingRef.current) {
          photosToUse = uploadedPhotosRef.current;
          break;
        }
        await new Promise((r) => setTimeout(r, 250));
      }
      photosToUse = uploadedPhotosRef.current;
      setIsWaitingForIngest(false);
    }

    if (photosToUse.length === 0) {
      toast.show({
        title: 'We couldn\'t find your photos',
        message: 'No curated photos are available in this session.',
        tone: 'error',
        action: {
          label: 'Upload Again',
          onClick: () => setStep('upload')
        }
      });
      return;
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
    setSkeletonThemes(null);
    setJobMessage('Submitting async photobook job...');

    try {
      const photoIds = photosToUse.map((p) => p.id);
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
      } else {
        const errBody = await res.json().catch(() => ({}));
        toast.show({
          title: 'Could not start album generation',
          message: errBody.detail || `Server returned status ${res.status}.`,
          tone: 'error',
          action: {
            label: 'Try Again',
            onClick: () => handleGenerateVariationsAsync(promptToUse, nextPrefs)
          }
        });
        setIsLoading(false);
        setJobStatus('failed');
        setStep('chat');
      }
    } catch (e) {
      console.error('Generation error:', e);
      toast.show({
        title: 'Connection lost',
        message: 'Could not reach the layout engine. Your uploaded photos are safe.',
        tone: 'error',
        action: {
          label: 'Retry',
          onClick: () => handleGenerateVariationsAsync(promptToUse, nextPrefs)
        }
      });
      setIsLoading(false);
      setJobStatus('failed');
      setStep('chat');
    }
  };

  const handleSpreadUpdate = (spreadIdx, newSpread) => {
    setVariations((prevVars) => {
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
    if (!currentJobId || isReshufflingVars) return;
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
        toast.show({
          title: 'Three new styles ready',
          message: 'Palettes and spread layouts have been refreshed.',
          tone: 'success',
          duration: 3500
        });
      } else {
        toast.show({
          title: 'Could not reshuffle styles',
          message: 'Please try again in a moment.',
          tone: 'warning'
        });
      }
    } catch (err) {
      console.error('Variations reshuffle error:', err);
      toast.show({
        title: 'Connection lost',
        message: 'Could not reshuffle variations right now.',
        tone: 'warning'
      });
    } finally {
      setIsReshufflingVars(false);
    }
  };

  const handleExportPDF = async (forcePreview = false) => {
    if (isExportingPDF) return;
    const selectedVar = variations[activeVarIdx];
    if (!selectedVar) {
      toast.show({
        title: 'No variation selected',
        message: 'Choose one of the three album styles before exporting.',
        tone: 'warning'
      });
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
          session_id: sessionIdRef.current,
          force_preview: Boolean(forcePreview)
        })
      });

      if (res.status === 409) {
        const body = await res.json().catch(() => ({}));
        const info = body.detail || {};
        const pending = info.pending_count ?? 0;
        const totalPlaced = info.total_count ?? 0;
        const readyCount = Math.max(0, totalPlaced - pending);
        prioritiseOriginalsForVariation(selectedVar);
        toast.show({
          title: 'Print files still uploading',
          message: `${readyCount} of ${totalPlaced} high-resolution files ready. Prioritising your chosen album now.`,
          tone: 'warning',
          action: {
            label: 'Export Low-Res Proof',
            onClick: () => handleExportPDF(true)
          }
        });
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
        }
        toast.show({
          title: 'Download ready',
          message: `${data.filename || 'pixovo_print_300dpi.pdf'} compiled for print.`,
          tone: 'success'
        });
      } else {
        const err = await res.json().catch(() => ({}));
        toast.show({
          title: 'PDF export could not complete',
          message: err.detail || 'Failed to compile print PDF.',
          tone: 'error',
          action: {
            label: 'Retry Export',
            onClick: () => handleExportPDF(forcePreview)
          }
        });
      }
    } catch (e) {
      console.error('PDF Export Error:', e);
      toast.show({
        title: 'Connection lost during export',
        message: 'Could not download the PDF. Please try again.',
        tone: 'error',
        action: {
          label: 'Retry Export',
          onClick: () => handleExportPDF(forcePreview)
        }
      });
    } finally {
      setIsExportingPDF(false);
    }
  };

  const handleClearSession = async () => {
    const hasWork = uploadedCount > 0 || variations.length > 0;
    if (hasWork && !window.confirm('Clear this session and start a new album? Uploaded photos and generated layouts will be discarded.')) {
      return;
    }

    localPreviewsRef.current.forEach((lp) => {
      if (lp.previewUrl) URL.revokeObjectURL(lp.previewUrl);
    });
    localPreviewsRef.current = [];

    persistSessionId(null);
    await clearAllBlobs();
    resetTransport();

    uploadedPhotosRef.current = [];
    originalsQueueRef.current = {};
    syncedIdsRef.current = new Set();

    setUploadedPhotos([]);
    setLocalPreviews([]);
    setServerPhotos({});
    setCapacityState(null);
    setUploadedCount(0);
    setIsPhotoUploadComplete(false);
    setIngestProgress({ done: 0, total: 0, received: 0, survived: 0 });
    setSyncStatus({ synced: 0, total: 0 });
    setVariations([]);
    setSkeletonThemes(null);
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
    setStorySessionKey((k) => k + 1);
    setStep('upload');
  };

  const scrollToSpreads = () => {
    if (spreadsRef.current) {
      spreadsRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  };

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

  const isStoryConversationalStep = !capacityState && (step === 'upload' || step === 'chat');

  return (
    <div className="app-container">
      <ToolbarHeader
        onExportPDF={step === 'preview' ? () => handleExportPDF(false) : null}
        isExporting={isExportingPDF}
        syncStatus={syncStatus}
        onClearSession={handleClearSession}
        canClearSession={step !== 'upload' || uploadedCount > 0 || Boolean(userPrompt.trim())}
      />

      <main className={`main-wrapper ${isStoryConversationalStep ? 'main-wrapper--story' : ''}`.trim()}>
        {capacityState && (
          <CapacityGate
            position={capacityState.position}
            retryIn={capacityState.retryIn}
            attempt={capacityState.attempt}
            onRetry={() => handlePhotosUploaded(capacityState.uploadPackage, capacityState.attempt + 1)}
            onCancel={() => {
              setCapacityState(null);
              setStep('upload');
            }}
          />
        )}

        {!capacityState && step === 'generating' && (
          <div key="step-generating" className="step-enter-active" style={{ width: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '2rem' }}>
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

              <div className="synthesis-fact-ticker" key={factIndex}>
                <span>{MICRO_FACTS[factIndex]}</span>
              </div>
            </div>

            {skeletonThemes && skeletonThemes.length > 0 && (
              <div className="step-enter-active" style={{ width: '100%' }}>
                <BookCarousel3D
                  variations={skeletonThemes}
                  activeIdx={0}
                  isSkeleton={true}
                />
              </div>
            )}
          </div>
        )}

        {isStoryConversationalStep && (
          <div key={`story-mode-${storySessionKey}`} className="step-enter-active" style={{ width: '100%' }}>
            <AIChatbotWidget
              userPrompt={userPrompt}
              setUserPrompt={setUserPrompt}
              onGenerate={handleGenerateVariationsAsync}
              onPhotosUploaded={handlePhotosUploaded}
              reconciledPhotos={reconciledPhotos}
              ingestProgress={ingestProgress}
              isPhotoUploadComplete={isPhotoUploadComplete}
              uploadedCount={uploadedCount}
              isLoading={isLoading}
              isWaitingForIngest={isWaitingForIngest}
              sessionId={sessionId}
            />
          </div>
        )}

        {!capacityState && step === 'preview' && (
          <div key="step-preview" className="story-preview-container step-enter-active">
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
              photoLookup={serverPhotos}
            />
          </div>
        )}
      </main>
    </div>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <AppContent />
    </ToastProvider>
  );
}
