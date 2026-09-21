import React from 'react';
import { BookOpen, ShoppingBag, LayoutGrid, Sparkles, Printer, Activity, RotateCcw } from 'lucide-react';

export default function ToolbarHeader({ activeMode, setActiveMode, onExportPDF, isExporting, syncStatus, onClearSession, canClearSession }) {
  return (
    <header className="toolbar-header">
      <div 
        className="brand-logo" 
        onClick={() => setActiveMode('story')} 
        style={{ cursor: 'pointer' }}
      >
        <BookOpen size={24} color="#8B5CF6" />
        <span>Pixovo</span>
        <span className="brand-badge">PTE Engine</span>
      </div>

      {/* Nav Tabs */}
      <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
        <button
          className={`btn ${activeMode === 'story' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setActiveMode('story')}
        >
          <Sparkles size={16} />
          <span>Story Mode</span>
        </button>

        <button
          className={`btn ${activeMode === 'inspector' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setActiveMode('inspector')}
        >
          <LayoutGrid size={16} />
          <span>Boilerplate Inspector</span>
        </button>

        <button
          className={`btn ${activeMode === 'stats' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setActiveMode('stats')}
        >
          <Activity size={16} />
          <span>System Stats</span>
        </button>

        {/* Live HD Sync Status Badge */}
        {syncStatus && syncStatus.total > 0 && (
          <div 
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              fontSize: '0.8rem',
              padding: '4px 10px',
              borderRadius: '20px',
              backgroundColor: syncStatus.synced === syncStatus.total ? '#ECFDF5' : '#FEF3C7',
              color: syncStatus.synced === syncStatus.total ? '#065F46' : '#92400E',
              border: `1px solid ${syncStatus.synced === syncStatus.total ? '#A7F3D0' : '#FDE68A'}`
            }}
            title="Progressive upload of 300 DPI high-resolution original images in background"
          >
            <span>{syncStatus.synced === syncStatus.total ? '⚡ 300 DPI Synced' : `⚡ Syncing HD: ${syncStatus.synced}/${syncStatus.total}`}</span>
          </div>
        )}
      </div>

      <div className="header-actions" style={{ display: 'flex', gap: '0.5rem' }}>
        {onExportPDF && (
          <button 
            className="btn btn-secondary"
            onClick={onExportPDF}
            disabled={isExporting}
            style={{ borderColor: '#8B5CF6', color: '#6D28D9' }}
            title="Compile & Download 300 DPI Print-Ready PDF/X"
          >
            <Printer size={16} color="#8B5CF6" />
            <span>{isExporting ? "Compiling PDF..." : "Export 300 DPI Print PDF"}</span>
          </button>
        )}

        {onClearSession && canClearSession && (
          <button
            className="btn btn-secondary"
            onClick={onClearSession}
            style={{ borderColor: '#FCA5A5', color: '#B91C1C' }}
            title="Discard this session and upload a new set of photos"
          >
            <RotateCcw size={16} color="#EF4444" />
            <span>Clear Session</span>
          </button>
        )}

        <button className="btn btn-secondary">
          <ShoppingBag size={16} />
          <span>Order this book</span>
        </button>
      </div>
    </header>
  );
}
