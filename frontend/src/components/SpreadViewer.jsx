import React, { useState, useEffect, useRef } from 'react';
import {
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  BookOpen,
  LayoutGrid,
  Shuffle,
  RefreshCw
} from 'lucide-react';
import PhotoFrame from './PhotoFrame';

export default function SpreadViewer({
  selectedVariation,
  targetRef,
  onSpreadUpdate,
  sessionId,
  photoLookup = {}
}) {
  const [viewMode, setViewMode] = useState('flip'); // 'flip' (Mixbook interactive book) | 'grid' (All spreads)
  const [activeSpreadIdx, setActiveSpreadIdx] = useState(0);
  const [reshufflingIdx, setReshufflingIdx] = useState(null);
  const [seedCounters, setSeedCounters] = useState({});
  const [scrollTop, setScrollTop] = useState(0);

  const containerRef = useRef(null);

  const spreads = selectedVariation?.spreads || [];
  const totalSpreads = spreads.length;

  // Reset activeSpreadIdx if variation changes and index is out of bounds
  useEffect(() => {
    if (activeSpreadIdx >= totalSpreads && totalSpreads > 0) {
      setActiveSpreadIdx(0);
    }
  }, [selectedVariation, totalSpreads, activeSpreadIdx]);

  // Stage 2.3 Task 5: Widen virtualization buffer from 2 to 3 spreads above and below viewport
  const SPREAD_ESTIMATED_HEIGHT = 520;
  const BUFFER_COUNT = 3;

  useEffect(() => {
    const handleScroll = () => {
      setScrollTop(window.scrollY);
    };
    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  // Keyboard left/right navigation in Interactive Book Flip mode
  useEffect(() => {
    if (viewMode !== 'flip' || totalSpreads === 0) return undefined;
    const handleKey = (e) => {
      if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) return;
      if (e.key === 'ArrowRight') {
        setActiveSpreadIdx((prev) => Math.min(totalSpreads - 1, prev + 1));
      } else if (e.key === 'ArrowLeft') {
        setActiveSpreadIdx((prev) => Math.max(0, prev - 1));
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [viewMode, totalSpreads]);

  // Compute visible range based on scroll position for 'grid' mode
  let startIdx = 0;
  let endIdx = totalSpreads;
  let topSpacerHeight = 0;
  let bottomSpacerHeight = 0;

  if (viewMode === 'grid' && totalSpreads > 8) {
    const containerTop = containerRef.current ? containerRef.current.offsetTop : 300;
    const relativeScroll = Math.max(0, scrollTop - containerTop);
    const visibleCount = Math.ceil(window.innerHeight / SPREAD_ESTIMATED_HEIGHT);

    startIdx = Math.max(0, Math.floor(relativeScroll / SPREAD_ESTIMATED_HEIGHT) - BUFFER_COUNT);
    endIdx = Math.min(totalSpreads, startIdx + visibleCount + BUFFER_COUNT * 2);

    topSpacerHeight = startIdx * SPREAD_ESTIMATED_HEIGHT;
    bottomSpacerHeight = Math.max(0, (totalSpreads - endIdx) * SPREAD_ESTIMATED_HEIGHT);
  }

  // Stage 2.3 Task 5: Prefetch upcoming spreads' images at low priority
  useEffect(() => {
    if (!totalSpreads) return;
    const startPrefetch = viewMode === 'flip' ? activeSpreadIdx + 1 : endIdx;
    if (startPrefetch >= totalSpreads) return;

    const upcomingSpreads = spreads.slice(startPrefetch, Math.min(totalSpreads, startPrefetch + 2));
    const urls = [];
    upcomingSpreads.forEach((sp) => {
      const slots = [...(sp.left_page?.slots || []), ...(sp.right_page?.slots || [])];
      slots.forEach((slot) => {
        if (slot.type === 'photo' && slot.photo_url) {
          urls.push(slot.photo_url);
        }
      });
    });

    urls.forEach((url) => {
      const img = new Image();
      img.fetchPriority = 'low';
      img.src = url;
    });
  }, [viewMode, activeSpreadIdx, endIdx, totalSpreads, spreads]);

  if (!selectedVariation || !selectedVariation.spreads || totalSpreads === 0) return null;

  const visibleSpreads = spreads.slice(startIdx, endIdx);

  const fontStyle =
    selectedVariation.theme_name === 'Devotional / Temple' || selectedVariation.id === 'var_2'
      ? "'Playfair Display', 'Lora', serif"
      : "'Plus Jakarta Sans', 'Outfit', sans-serif";

  const handleReshuffleSpread = async (spread, originalIdx) => {
    if (reshufflingIdx !== null) return;
    setReshufflingIdx(originalIdx);
    const nextSeed = (seedCounters[originalIdx] || 1) + 1;
    setSeedCounters((prev) => ({ ...prev, [originalIdx]: nextSeed }));

    try {
      const res = await fetch('/api/spreads/reshuffle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          spread: spread,
          theme_name: selectedVariation.theme_name || 'Warm',
          seed: nextSeed,
          session_id: sessionId || null
        })
      });

      if (res.ok) {
        const updatedSpread = await res.json();
        if (onSpreadUpdate) {
          onSpreadUpdate(originalIdx, updatedSpread);
        }
      }
    } catch (err) {
      console.error('Spread reshuffle error:', err);
    } finally {
      setReshufflingIdx(null);
    }
  };

  // Helper to render the inner double-page spread canvas
  const renderSpreadCanvas = (spread, originalIdx, isFlipBookMode = false) => {
    const left = spread.left_page;
    const right = spread.right_page;
    const allSlots = [...(left?.slots || []), ...(right?.slots || [])];
    const isReshuffling = reshufflingIdx === originalIdx;

    const handleCanvasClick = (e) => {
      if (!isFlipBookMode) {
        handleReshuffleSpread(spread, originalIdx);
        return;
      }
      // In Mixbook Interactive Flip mode: clicking left half goes prev, clicking right half goes next
      const rect = e.currentTarget.getBoundingClientRect();
      const clickX = e.clientX - rect.left;
      if (clickX < rect.width * 0.45 && activeSpreadIdx > 0) {
        setActiveSpreadIdx((prev) => Math.max(0, prev - 1));
      } else if (clickX >= rect.width * 0.45 && activeSpreadIdx < totalSpreads - 1) {
        setActiveSpreadIdx((prev) => Math.min(totalSpreads - 1, prev + 1));
      }
    };

    return (
      <div
        className="spread-pair"
        onClick={handleCanvasClick}
        style={{
          cursor: 'pointer',
          transition: 'transform 0.22s ease, box-shadow 0.22s ease, opacity 0.2s ease',
          opacity: isReshuffling ? 0.6 : 1
        }}
        title={isFlipBookMode ? 'Tap left or right page to flip spreads' : 'Click to shuffle this spread layout'}
      >
        {/* Left Page Background */}
        <div
          className="spread-half-bg left-half"
          style={{ backgroundColor: left.background_color || 'var(--px-canvas-warm)' }}
        />

        {/* Right Page Background */}
        <div
          className="spread-half-bg right-half"
          style={{ backgroundColor: right.background_color || 'var(--px-canvas-warm)' }}
        />

        {/* Central Spine Gutter Fold Shadow */}
        <div className="spine-gutter" />

        {/* Render Slots Positioned Directly on Spread using PhotoFrame */}
        {allSlots.map((slot, sIdx) => {
          if (slot.type === 'photo' && slot.photo_url) {
            const meta = slot.photo_id ? photoLookup[slot.photo_id] : null;
            const dominantColors = meta?.dominant_colors || [
              selectedVariation.base_color || '#E4E4E7',
              selectedVariation.accent_color || '#D4D4D8'
            ];

            return (
              <div
                key={sIdx}
                className="slot-photo-frame"
                style={{
                  left: `${slot.x_pct * 100}%`,
                  top: `${slot.y_pct * 100}%`,
                  width: `${slot.w_pct * 100}%`,
                  height: `${slot.h_pct * 100}%`,
                  background: 'transparent',
                  boxShadow: 'none',
                  border: 'none'
                }}
              >
                <PhotoFrame
                  src={slot.photo_url}
                  aspectRatio={null}
                  dominantColors={dominantColors}
                  alt="Spread photo"
                  style={{
                    width: '100%',
                    height: '100%',
                    boxShadow: '0 4px 14px rgba(0, 0, 0, 0.12)',
                    borderRadius: '2px'
                  }}
                  imgStyle={{
                    borderRadius: '2px'
                  }}
                >
                  {/* Pre-Flight Print DPI Warning Badge */}
                  {slot.dpi_quality && slot.dpi_quality !== 'excellent' && (
                    <div
                      title={`Pre-Flight Check: ${slot.effective_dpi ? `${slot.effective_dpi} DPI` : 'Low Resolution'} - ${
                        slot.dpi_quality === 'alert'
                          ? 'Image may look pixelated when printed'
                          : 'Acceptable quality, higher resolution recommended'
                      }`}
                      style={{
                        position: 'absolute',
                        top: '4px',
                        right: '4px',
                        backgroundColor:
                          slot.dpi_quality === 'alert'
                            ? 'rgba(239, 68, 68, 0.92)'
                            : 'rgba(245, 158, 11, 0.92)',
                        color: '#FFFFFF',
                        fontSize: '9px',
                        fontWeight: '600',
                        padding: '2px 5px',
                        borderRadius: '3px',
                        backdropFilter: 'blur(4px)',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '3px',
                        boxShadow: '0 2px 4px rgba(0,0,0,0.2)',
                        pointerEvents: 'auto',
                        zIndex: 10
                      }}
                    >
                      <AlertTriangle size={12} strokeWidth={2} />
                      <span>
                        {slot.effective_dpi ? `${Math.round(slot.effective_dpi)} DPI` : 'Low DPI'}
                      </span>
                    </div>
                  )}
                </PhotoFrame>
              </div>
            );
          }
          if (slot.type === 'text' && slot.text_content) {
            return (
              <div
                key={sIdx}
                className="slot-text-frame"
                style={{
                  left: `${slot.x_pct * 100}%`,
                  top: `${slot.y_pct * 100}%`,
                  width: `${slot.w_pct * 100}%`,
                  height: `${slot.h_pct * 100}%`,
                  color:
                    slot.x_pct < 0.5
                      ? left.text_color || 'var(--px-text-primary)'
                      : right.text_color || 'var(--px-text-primary)',
                  fontFamily: fontStyle,
                  pointerEvents: 'none'
                }}
              >
                {slot.text_content}
              </div>
            );
          }
          return null;
        })}
      </div>
    );
  };

  const currentFlipSpread = spreads[activeSpreadIdx] || spreads[0];
  const currentFlipLeft = currentFlipSpread?.left_page;
  const currentFlipRight = currentFlipSpread?.right_page;

  return (
    <div
      className="spreads-list"
      ref={(el) => {
        containerRef.current = el;
        if (typeof targetRef === 'function') targetRef(el);
        else if (targetRef) targetRef.current = el;
      }}
    >
      {/* Top Studio Bar: Book Info + Interactive Book Flip / All Spreads Toggle */}
      <div className="mx-studio-toolbar">
        <div>
          <div style={{ fontWeight: 800, fontSize: '1.05rem', color: 'var(--mx-deep-purple)', letterSpacing: '-0.02em' }}>
            {selectedVariation.cover_title || 'Your Story Book'} —{' '}
            <span style={{ color: 'var(--mx-brand-purple)' }}>
              {selectedVariation.variation_title || selectedVariation.theme_name}
            </span>
          </div>
          <div style={{ fontSize: '0.82rem', color: 'var(--px-text-secondary)' }}>
            {totalSpreads} Layflat Double Spreads ({totalSpreads * 2} Pages) • 200×200mm Square Hardcover
          </div>
        </div>

        <div className="mx-view-toggle">
          <button
            type="button"
            className={`mx-view-toggle-btn ${viewMode === 'flip' ? 'active' : ''}`}
            onClick={() => setViewMode('flip')}
          >
            <BookOpen size={15} style={{ marginRight: '6px', verticalAlign: '-2px' }} />
            Interactive Book Flip
          </button>
          <button
            type="button"
            className={`mx-view-toggle-btn ${viewMode === 'grid' ? 'active' : ''}`}
            onClick={() => setViewMode('grid')}
          >
            <LayoutGrid size={15} style={{ marginRight: '6px', verticalAlign: '-2px' }} />
            All Spreads ({totalSpreads})
          </button>
        </div>
      </div>

      {/* =================================================================
          MODE 1: MIXBOOK INTERACTIVE LAYFLAT BOOK FLIP VIEWER
          ================================================================= */}
      {viewMode === 'flip' && currentFlipSpread && (
        <div className="spread-pair-container" style={{ width: '100%' }}>
          <div className="mx-layflat-book-frame">
            {renderSpreadCanvas(currentFlipSpread, activeSpreadIdx, true)}
          </div>

          {/* Flip Controls + Tap to Flip Prompt + Reshuffle Current Spread */}
          <div className="mx-flip-controls-row">
            <button
              type="button"
              className="mx-flip-nav-btn"
              onClick={() => setActiveSpreadIdx((prev) => Math.max(0, prev - 1))}
              disabled={activeSpreadIdx === 0}
              aria-label="Previous spread"
              title="Previous spread"
            >
              <ChevronLeft size={20} strokeWidth={2.25} />
            </button>

            <div className="mx-flip-page-indicator">
              <div style={{ fontWeight: 700, color: 'var(--mx-deep-purple)' }}>
                Spread {activeSpreadIdx + 1} of {totalSpreads} • Pages {currentFlipLeft?.page_number}–
                {currentFlipRight?.page_number}
              </div>
              <div style={{ fontSize: '0.78rem', color: 'var(--px-text-muted)', marginTop: '2px' }}>
                Tap left or right page to flip • Use arrow keys
              </div>
            </div>

            <button
              type="button"
              className="mx-flip-nav-btn"
              onClick={() => setActiveSpreadIdx((prev) => Math.min(totalSpreads - 1, prev + 1))}
              disabled={activeSpreadIdx >= totalSpreads - 1}
              aria-label="Next spread"
              title="Next spread"
            >
              <ChevronRight size={20} strokeWidth={2.25} />
            </button>

            <button
              type="button"
              className="btn btn-secondary"
              style={{ marginLeft: '0.5rem', padding: '0.5rem 1rem', fontSize: '0.82rem' }}
              onClick={() => handleReshuffleSpread(currentFlipSpread, activeSpreadIdx)}
              disabled={reshufflingIdx === activeSpreadIdx}
              title="Shuffle photo arrangement on this spread"
            >
              {reshufflingIdx === activeSpreadIdx ? (
                <RefreshCw size={14} className="animate-spin" color="var(--mx-brand-purple)" />
              ) : (
                <Shuffle size={14} color="var(--mx-brand-purple)" />
              )}
              <span>
                {reshufflingIdx === activeSpreadIdx ? 'Shuffling...' : 'Shuffle Spread Layout'}
              </span>
            </button>
          </div>

          {/* Spread Scrubber Pills */}
          <div className="mx-spread-scrubber">
            {spreads.map((sp, idx) => (
              <button
                key={idx}
                type="button"
                className={`mx-scrubber-pill ${idx === activeSpreadIdx ? 'active' : ''}`}
                onClick={() => setActiveSpreadIdx(idx)}
              >
                {idx + 1}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* =================================================================
          MODE 2: ALL SPREADS VERTICAL STUDIO LIST
          ================================================================= */}
      {viewMode === 'grid' && (
        <>
          {topSpacerHeight > 0 && (
            <div style={{ height: `${topSpacerHeight}px`, width: '100%' }} />
          )}

          {visibleSpreads.map((spread, offset) => {
            const originalIdx = startIdx + offset;
            const left = spread.left_page;
            const right = spread.right_page;
            const isReshuffling = reshufflingIdx === originalIdx;

            return (
              <div key={originalIdx} className="spread-pair-container">
                <div
                  style={{
                    width: '100%',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    marginBottom: '0.55rem',
                    padding: '0 0.5rem'
                  }}
                >
                  <span
                    style={{
                      fontSize: '0.86rem',
                      fontWeight: 700,
                      color: 'var(--mx-deep-purple)',
                      letterSpacing: '-0.01em'
                    }}
                  >
                    Spread {spread.spread_index} • Pages {left.page_number}–{right.page_number}
                  </span>

                  <button
                    type="button"
                    className="mx-chip-btn"
                    style={{ padding: '0.3rem 0.75rem', fontSize: '0.76rem' }}
                    onClick={() => handleReshuffleSpread(spread, originalIdx)}
                    disabled={isReshuffling}
                  >
                    <Shuffle size={12} style={{ marginRight: '5px', verticalAlign: '-1px' }} />
                    {isReshuffling ? 'Shuffling...' : 'Shuffle Layout'}
                  </button>
                </div>

                <div className="mx-layflat-book-frame">
                  {renderSpreadCanvas(spread, originalIdx, false)}
                </div>

                <div className="page-footer-num" style={{ fontFamily: fontStyle }}>
                  {originalIdx === 0
                    ? 'Front Inside & Page 1'
                    : `Pages ${left.page_number} & ${right.page_number}`}
                </div>
              </div>
            );
          })}

          {bottomSpacerHeight > 0 && (
            <div style={{ height: `${bottomSpacerHeight}px`, width: '100%' }} />
          )}
        </>
      )}
    </div>
  );
}
