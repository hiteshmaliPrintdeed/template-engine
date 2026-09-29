import React from 'react';
import { BookOpen, Printer, RotateCcw, RefreshCw, Check } from 'lucide-react';

export default function ToolbarHeader({ onExportPDF, isExporting, syncStatus, onClearSession, canClearSession }) {
  const isSynced = syncStatus && syncStatus.total > 0 && syncStatus.synced === syncStatus.total;

  return (
    <header className="toolbar-header">
      <div className="brand-logo">
        <BookOpen size={22} color="var(--px-brand-iris)" strokeWidth={1.75} />
        <span>Pixovo</span>
        <span className="brand-badge">PTE Engine</span>
      </div>

      <div className="header-actions" style={{ display: 'flex', gap: '0.65rem', alignItems: 'center' }}>
        {syncStatus && syncStatus.total > 0 && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              fontSize: '0.78rem',
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
              <Check size={14} strokeWidth={2} />
            ) : (
              <RefreshCw size={14} strokeWidth={2} className="animate-spin" />
            )}
            <span>
              {isSynced ? '300 DPI Synced' : `Syncing HD: ${syncStatus.synced}/${syncStatus.total}`}
            </span>
          </div>
        )}

        {onClearSession && canClearSession && (
          <button
            className="btn btn-secondary"
            onClick={onClearSession}
            title="Discard this session and upload a new set of photos"
          >
            <RotateCcw size={15} strokeWidth={1.75} color="var(--px-text-secondary)" />
            <span>Clear Session</span>
          </button>
        )}

        {onExportPDF && (
          <button
            className="btn btn-primary"
            onClick={onExportPDF}
            disabled={isExporting}
            title="Compile & Download 300 DPI Print-Ready PDF/X"
          >
            <Printer size={16} strokeWidth={1.75} />
            <span>{isExporting ? 'Compiling PDF...' : 'Export 300 DPI Print PDF'}</span>
          </button>
        )}
      </div>
    </header>
  );
}
