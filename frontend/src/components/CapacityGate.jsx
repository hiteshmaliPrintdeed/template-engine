import React, { useEffect, useState } from 'react';
import { Clock, RefreshCw } from 'lucide-react';

/**
 * Stage 2.4 Task 3 — CapacityGate Queue Panel.
 * Rendered when POST /api/sessions returns 503 at_capacity.
 * Counts down retry_after_seconds and automatically invokes onRetry() when
 * the timer reaches 0 (up to maxAttempts before offering manual retry).
 */
export default function CapacityGate({
  position = 1,
  retryIn = 15,
  attempt = 1,
  maxAttempts = 5,
  onRetry,
  onCancel
}) {
  const [secondsLeft, setSecondsLeft] = useState(() => Math.max(1, Math.round(retryIn || 15)));

  useEffect(() => {
    setSecondsLeft(Math.max(1, Math.round(retryIn || 15)));
  }, [retryIn, attempt]);

  useEffect(() => {
    if (attempt > maxAttempts) return undefined;
    if (secondsLeft <= 0) {
      onRetry?.();
      return undefined;
    }

    const timer = setTimeout(() => {
      setSecondsLeft((prev) => prev - 1);
    }, 1000);

    return () => clearTimeout(timer);
  }, [secondsLeft, attempt, maxAttempts, onRetry]);

  const totalDots = 5;
  const filledDots = Math.max(1, Math.min(totalDots, totalDots - Math.min(totalDots - 1, position - 1)));

  return (
    <div className="step-card capacity-gate-card step-enter-active" role="region" aria-label="Upload queue status">
      <div className="capacity-gate-icon">
        <Clock size={24} strokeWidth={1.75} color="var(--px-brand-iris)" />
      </div>

      <span className="synthesis-eyebrow">Admission Queue</span>
      <h3 className="capacity-gate-title">Your album is next in line</h3>
      <p className="capacity-gate-copy">
        We&apos;re designing 20 albums right now.
        {attempt <= maxAttempts
          ? ` Yours starts in about ${secondsLeft} second${secondsLeft === 1 ? '' : 's'}.`
          : ' The studio is experiencing peak demand.'}
      </p>

      <div className="capacity-gate-pill" aria-live="polite">
        <div className="capacity-dots" aria-hidden="true">
          {Array.from({ length: totalDots }).map((_, i) => (
            <span
              key={i}
              className={`capacity-dot ${i < filledDots ? 'filled' : ''}`}
            />
          ))}
        </div>
        <span>Position {Math.max(1, position)}</span>
      </div>

      <div className="capacity-gate-actions">
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => onRetry?.()}
        >
          <RefreshCw size={15} strokeWidth={2} />
          <span>{attempt <= maxAttempts ? `Retrying in ${secondsLeft}s — Try Now` : 'Retry Now'}</span>
        </button>

        {onCancel && (
          <button
            type="button"
            className="btn btn-secondary"
            onClick={onCancel}
          >
            Cancel
          </button>
        )}
      </div>
    </div>
  );
}
