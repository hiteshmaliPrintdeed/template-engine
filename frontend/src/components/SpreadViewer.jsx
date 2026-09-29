import React, { useState, useEffect, useRef } from 'react';
import { AlertTriangle } from 'lucide-react';

export default function SpreadViewer({ selectedVariation, targetRef, onSpreadUpdate, sessionId }) {
  const [reshufflingIdx, setReshufflingIdx] = useState(null);
  const [seedCounters, setSeedCounters] = useState({});
  const [scrollTop, setScrollTop] = useState(0);

  const containerRef = useRef(null);

  if (!selectedVariation || !selectedVariation.spreads) return null;

  // Windowing calculations (Estimated spread container height ~520px)
  const SPREAD_ESTIMATED_HEIGHT = 520;
  const BUFFER_COUNT = 2; // Render 2 spreads above and 2 spreads below viewport
  const totalSpreads = selectedVariation.spreads.length;

  useEffect(() => {
    const handleScroll = () => {
      setScrollTop(window.scrollY);
    };
    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  // Compute visible range based on scroll position
  let startIdx = 0;
  let endIdx = totalSpreads;
  let topSpacerHeight = 0;
  let bottomSpacerHeight = 0;

  // Only apply windowing virtualization if album has more than 8 spreads
  if (totalSpreads > 8) {
    const containerTop = containerRef.current ? containerRef.current.offsetTop : 300;
    const relativeScroll = Math.max(0, scrollTop - containerTop);
    const visibleCount = Math.ceil(window.innerHeight / SPREAD_ESTIMATED_HEIGHT);

    startIdx = Math.max(0, Math.floor(relativeScroll / SPREAD_ESTIMATED_HEIGHT) - BUFFER_COUNT);
    endIdx = Math.min(totalSpreads, startIdx + visibleCount + (BUFFER_COUNT * 2));

    topSpacerHeight = startIdx * SPREAD_ESTIMATED_HEIGHT;
    bottomSpacerHeight = Math.max(0, (totalSpreads - endIdx) * SPREAD_ESTIMATED_HEIGHT);
  }

  const visibleSpreads = selectedVariation.spreads.slice(startIdx, endIdx);

  const fontStyle = selectedVariation.theme_name === "Devotional / Temple" || selectedVariation.id === "var_2"
    ? "'Playfair Display', 'Lora', serif"
    : "'Outfit', 'Inter', sans-serif";

  const handleSpreadClick = async (spread, originalIdx) => {
    setReshufflingIdx(originalIdx);
    const nextSeed = (seedCounters[originalIdx] || 1) + 1;
    setSeedCounters(prev => ({ ...prev, [originalIdx]: nextSeed }));

    try {
      const res = await fetch('/api/spreads/reshuffle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          spread: spread,
          theme_name: selectedVariation.theme_name || "Warm",
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
      console.error("Spread reshuffle error:", err);
    } finally {
      setReshufflingIdx(null);
    }
  };

  return (
    <div
      className="spreads-list"
      ref={(el) => {
        containerRef.current = el;
        if (typeof targetRef === 'function') targetRef(el);
        else if (targetRef) targetRef.current = el;
      }}
    >
      {/* Top Virtual Spacer */}
      {topSpacerHeight > 0 && (
        <div style={{ height: `${topSpacerHeight}px`, width: '100%' }} />
      )}

      {visibleSpreads.map((spread, offset) => {
        const originalIdx = startIdx + offset;
        const left = spread.left_page;
        const right = spread.right_page;
        const allSlots = [...left.slots, ...right.slots];
        const isReshuffling = reshufflingIdx === originalIdx;

        return (
          <div key={originalIdx} className="spread-pair-container">
            {/* Clean Spread Heading */}
            <div style={{
              width: '100%',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginBottom: '0.5rem',
              padding: '0 0.5rem'
            }}>
              <span style={{ fontSize: '0.84rem', fontWeight: 600, color: 'var(--px-text-muted)', letterSpacing: '0.02em' }}>
                Spread {spread.spread_index} • Pages {left.page_number}–{right.page_number}
              </span>
            </div>

            {/* Interactive Double Spread Canvas */}
            <div
              className="spread-pair"
              onClick={() => handleSpreadClick(spread, originalIdx)}
              style={{
                cursor: 'pointer',
                transition: 'transform 0.2s ease, box-shadow 0.2s ease',
                opacity: isReshuffling ? 0.6 : 1
              }}
              title="Click to reshuffle layout"
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

              {/* Render Slots Positioned Directly on Spread (Zero Fake Card Boxes) */}
              {allSlots.map((slot, sIdx) => {
                if (slot.type === 'photo' && slot.photo_url) {
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
                      <img
                        src={slot.photo_url}
                        alt="Spread photo"
                        style={{
                          width: '100%',
                          height: '100%',
                          objectFit: 'cover',
                          boxShadow: '0 4px 14px rgba(0, 0, 0, 0.12)',
                          borderRadius: '2px'
                        }}
                      />
                      {/* Pre-Flight Print DPI Warning Badge */}
                      {slot.dpi_quality && slot.dpi_quality !== 'excellent' && (
                        <div
                          title={`Pre-Flight Check: ${slot.effective_dpi ? `${slot.effective_dpi} DPI` : 'Low Resolution'} - ${slot.dpi_quality === 'alert' ? 'Image may look pixelated when printed' : 'Acceptable quality, higher resolution recommended'}`}
                          style={{
                            position: 'absolute',
                            top: '4px',
                            right: '4px',
                            backgroundColor: slot.dpi_quality === 'alert' ? 'rgba(239, 68, 68, 0.92)' : 'rgba(245, 158, 11, 0.92)',
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
                          <span>{slot.effective_dpi ? `${Math.round(slot.effective_dpi)} DPI` : 'Low DPI'}</span>
                        </div>
                      )}
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
                        color: slot.x_pct < 0.50 ? (left.text_color || 'var(--px-text-primary)') : (right.text_color || 'var(--px-text-primary)'),
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

            {/* Footer Page Numbers */}
            <div className="page-footer-num" style={{ fontFamily: fontStyle }}>
              {originalIdx === 0 ? "Front Inside & Page 1" : `${left.page_number} & ${right.page_number}`}
            </div>
          </div>
        );
      })}

      {/* Bottom Virtual Spacer */}
      {bottomSpacerHeight > 0 && (
        <div style={{ height: `${bottomSpacerHeight}px`, width: '100%' }} />
      )}
    </div>
  );
}
