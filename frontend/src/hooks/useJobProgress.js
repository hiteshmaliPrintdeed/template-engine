import { useEffect, useRef, useState } from 'react';

const INITIAL_STATE = {
  progress: 0,
  message: '',
  phase: 'idle',
  status: 'idle',
  detail: null,
  themes: null,
  result: null,
};

/**
 * Stage 2.2 — Real-Time Job Progress Hook over Server-Sent Events (SSE).
 * Connects to GET /api/jobs/{jobId}/stream for push-based progress, early
 * theme skeletons (Stage 2.3), and per-spread layout telemetry.
 * Automatically falls back to gentle 2s polling if EventSource fails or is blocked,
 * and cleans up all connections and timers on unmount or job reset.
 */
export function useJobProgress(jobId, { onComplete, onError } = {}) {
  const [state, setState] = useState(INITIAL_STATE);
  const esRef = useRef(null);
  const pollRef = useRef(null);
  const callbacksRef = useRef({ onComplete, onError });
  callbacksRef.current = { onComplete, onError };

  useEffect(() => {
    if (!jobId) {
      setState(INITIAL_STATE);
      return undefined;
    }

    let cancelled = false;
    let finished = false;

    setState({
      progress: 10,
      message: 'Job queued for processing...',
      phase: 'queued',
      status: 'processing',
      detail: null,
      themes: null,
      result: null,
    });

    const cleanup = () => {
      if (esRef.current) {
        try { esRef.current.close(); } catch (_) {}
        esRef.current = null;
      }
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };

    const handleTerminalComplete = async (payload) => {
      if (cancelled || finished) return;
      finished = true;
      cleanup();

      let finalJob = payload;
      if (!finalJob?.result) {
        try {
          const res = await fetch(`/api/jobs/${jobId}`);
          if (res.ok) {
            finalJob = await res.json();
          }
        } catch (_) {}
      }
      if (!cancelled) {
        setState((prev) => ({
          ...prev,
          ...finalJob,
          progress: 100,
          status: 'completed',
          phase: 'completed',
        }));
        callbacksRef.current.onComplete?.(finalJob);
      }
    };

    const handleTerminalError = (payload) => {
      if (cancelled || finished) return;
      finished = true;
      cleanup();
      setState((prev) => ({
        ...prev,
        ...payload,
        status: 'failed',
        phase: 'failed',
      }));
      callbacksRef.current.onError?.(payload);
    };

    const startPolling = () => {
      if (cancelled || finished || pollRef.current) return;
      pollRef.current = setInterval(async () => {
        if (cancelled || finished) return;
        try {
          const res = await fetch(`/api/jobs/${jobId}`);
          if (!res.ok || cancelled || finished) return;
          const job = await res.json();
          setState((prev) => ({
            ...prev,
            ...job,
            progress: Math.max(prev.progress || 0, job.progress || 0),
          }));
          if (job.status === 'completed') {
            await handleTerminalComplete(job);
          } else if (job.status === 'failed') {
            handleTerminalError(job);
          }
        } catch (_) {
          /* transient network error — keep trying */
        }
      }, 2000);
    };

    if (typeof EventSource !== 'undefined') {
      try {
        const es = new EventSource(`/api/jobs/${jobId}/stream`);
        esRef.current = es;

        es.onmessage = (e) => {
          if (cancelled || finished) return;
          try {
            const data = JSON.parse(e.data);
            setState((prev) => ({
              ...prev,
              ...data,
              themes: data.themes || prev.themes,
              progress: Math.max(prev.progress || 0, data.progress || 0),
            }));
            if (data.status === 'completed') {
              handleTerminalComplete(data);
            } else if (data.status === 'failed') {
              handleTerminalError(data);
            }
          } catch (_) {}
        };

        es.onerror = () => {
          if (cancelled || finished) return;
          try { es.close(); } catch (_) {}
          esRef.current = null;
          startPolling();
        };
      } catch (_) {
        startPolling();
      }
    } else {
      startPolling();
    }

    return () => {
      cancelled = true;
      cleanup();
    };
  }, [jobId]);

  return state;
}

export default useJobProgress;
