import React from 'react';
import { BookOpen, Printer, X, RefreshCw, Check, Sparkles } from 'lucide-react';

export default function ToolbarHeader({
  onExportPDF,
  isExporting,
  syncStatus,
  onClearSession,
  canClearSession
}) {
  const isSynced =
    syncStatus && syncStatus.total > 0 && syncStatus.synced === syncStatus.total;

  return (
    <header className="toolbar-header">
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        {onClearSession && canClearSession && (
          <button
            type="button"
            className="mx-header-close-btn"
            onClick={onClearSession}
            title="Start a new Story Mode session"
            aria-label="Start a new Story Mode session"
          >
            <X size={18} strokeWidth={2} />
          </button>
        )}

        <div className="brand-logo">
          <BookOpen size={21} color="var(--mx-brand-purple)" strokeWidth={2} />
          <span>pixovo</span>
          <span className="brand-badge">
            <Sparkles size={11} strokeWidth={2.25} style={{ marginRight: '4px', verticalAlign: '-1px' }} />
            Story Mode
          </span>
        </div>
      </div>

      <div className="header-actions" style={{ display: 'flex', gap: '0.65rem', alignItems: 'center' }}>
        {syncStatus && syncStatus.total > 0 && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              fontSize: '0.76rem',
              fontWeight: 600,
              padding: '5px 12px',
              borderRadius: '999px',
              backgroundColor: isSynced ? 'var(--px-status-success-bg)' : 'var(--px-status-warning-bg)',
              color: isSynced ? 'var(--px-status-success-text)' : 'var(--px-status-warning-text)',
              border: `1px solid ${isSynced ? 'var(--px-status-success-border)' : 'var(--px-status-warning-border)'}`
            }}
            title="Progressive upload of 300 DPI high-resolution original images in background"
          >
            {isSynced ? (
              <Check size={13} strokeWidth={2.25} />
            ) : (
              <RefreshCw size={13} strokeWidth={2} className="animate-spin" />
            )}
            <span>
              {isSynced ? '300 DPI Ready' : `HD Sync: ${syncStatus.synced}/${syncStatus.total}`}
            </span>
          </div>
        )}

        {onExportPDF && (
          <button
            type="button"
            className="mx-btn-story-mode"
            style={{ padding: '0.55rem 1.25rem', fontSize: '0.86rem' }}
            onClick={onExportPDF}
            disabled={isExporting}
            title="Compile & Download 300 DPI Print-Ready PDF/X"
          >
            <Printer size={15} strokeWidth={2} />
            <span>{isExporting ? 'Compiling Print PDF...' : 'Export 300 DPI Print PDF'}</span>
          </button>
        )}
      </div>
    </header>
  );
}
