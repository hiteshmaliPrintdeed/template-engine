import React from 'react';
import { ChevronDown, Check, Shuffle } from 'lucide-react';
import PhotoFrame from './PhotoFrame';

/**
 * Renders a variation's cover from the photo list the backend supplied, or as a
 * themed skeleton cover (Stage 2.3 Task 4) before layout photos arrive.
 *
 * Uses PhotoFrame so every cover slot reserves exact dimensions and paints
 * a dominant-colour or theme-palette gradient with zero layout shift.
 */
export function CoverArt({ item }) {
  const photos = item.cover_photos || [];
  const defaultGradient = [
    item.base_color || '#FAF9F6',
    item.accent_color || item.base_color || '#E4E4E7'
  ];

  const at = (i) => photos[i]?.url || photos[0]?.url || item.cover_image_url || '';
  const colorsAt = (i) =>
    photos[i]?.dominant_colors || photos[0]?.dominant_colors || defaultGradient;

  const frame = (i, className, aspectRatio) => (
    <PhotoFrame
      src={at(i)}
      dominantColors={colorsAt(i)}
      aspectRatio={aspectRatio}
      alt=""
      className={className}
      style={{ width: '100%', height: '100%' }}
    />
  );

  switch (item.cover_style) {
    case 'HERO_BAND':
      return (
        <div className="cover-layout-sage" style={{ backgroundColor: item.base_color || '#8C9386' }}>
          <div className="cover-img-top-wrapper">{frame(0, 'cover-img-full', null)}</div>
          <div className="cover-sage-band" style={{ backgroundColor: item.accent_color || '#8C9386' }}>
            <span className="cover-year-italic">{item.cover_subtitle}</span>
            <h4 className="serif-title" style={{ color: item.text_color || '#FFFFFF' }}>
              {item.cover_title}
            </h4>
          </div>
        </div>
      );

    case 'COLLAGE_2X2':
      return (
        <div className="cover-layout-collage" style={{ backgroundColor: item.base_color || '#FAF9F6' }}>
          <div className="collage-2x2">
            {[0, 1, 2, 3].map((i) => (
              <PhotoFrame
                key={i}
                src={at(i)}
                dominantColors={colorsAt(i)}
                aspectRatio={1}
                alt=""
                style={{ width: '100%', height: '100%' }}
              />
            ))}
          </div>
          <div className="cover-glass-overlay">
            <h4 className="bold-serif-title" style={{ color: item.text_color || '#1F2937' }}>
              {item.cover_title}
            </h4>
          </div>
        </div>
      );

    case 'SPLIT_BANNER':
    default:
      return (
        <div className="cover-layout-split" style={{ backgroundColor: item.base_color || '#FAF9F6' }}>
          {frame(0, 'cover-img-half', null)}
          <div className="cover-banner-white">
            <h4 style={{ color: item.text_color || '#1F2937' }}>{item.cover_title}</h4>
          </div>
          {frame(1, 'cover-img-half', null)}
        </div>
      );
  }
}

export default function BookCarousel3D({
  variations,
  activeIdx,
  setActiveIdx,
  onScrollDown,
  onReshuffleVariations,
  isReshuffling,
  isSkeleton = false
}) {
  if (!variations || variations.length === 0) return null;

  return (
    <div style={{ width: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
      {!isSkeleton && (
        <h2 className="preview-title">Choose Your Album Variation (3 Saved Styles)</h2>
      )}

      {/* Reshuffle Variations Action Bar */}
      {!isSkeleton && onReshuffleVariations && (
        <button
          className="btn btn-secondary"
          onClick={onReshuffleVariations}
          disabled={isReshuffling}
          style={{ marginBottom: '1rem', padding: '0.5rem 1.25rem', borderRadius: '20px', fontWeight: 600 }}
        >
          <Shuffle size={16} color="var(--px-brand-iris)" strokeWidth={1.75} />
          <span>{isReshuffling ? 'Reshuffling Variations...' : 'Reshuffle Palettes & Layouts (3 Variations)'}</span>
        </button>
      )}

      {/* 3D Book Carousel Stage */}
      <div className="carousel-stage">
        {variations.map((item, idx) => {
          const isHero = idx === activeIdx;

          return (
            <div
              key={item.id || idx}
              className={`carousel-card ${isHero ? 'hero' : ''}`}
              onClick={() => setActiveIdx && setActiveIdx(idx)}
              style={{
                borderColor: isHero ? item.accent_color : 'transparent'
              }}
            >
              {isHero && !isSkeleton && (
                <div className="hero-check-badge">
                  <Check size={18} />
                </div>
              )}

              <CoverArt item={item} />
            </div>
          );
        })}
      </div>

      {!isSkeleton && onScrollDown && (
        <button className="scroll-indicator" onClick={onScrollDown} title="Scroll to double page spreads">
          <ChevronDown size={28} />
        </button>
      )}
    </div>
  );
}
