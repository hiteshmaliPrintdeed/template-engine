import React from 'react';
import { ChevronDown, Check, Shuffle } from 'lucide-react';

/**
 * Renders a variation's cover from the photo list the backend supplied.
 *
 * Stage 1.5: the style used to be picked here by `idx % 3`, and every <img>
 * pointed at the single `cover_image_url` — so the "4-photo collage" was one
 * photo repeated four times, and the split banner showed the same photo twice.
 * The backend now declares `cover_style` (only the producer knows how many
 * photos it supplied) and provides `cover_photos`.
 */
function CoverArt({ item }) {
  const photos = item.cover_photos || [];

  // Fall back to photo 0, then to the deprecated single URL, so a short list
  // degrades to a repeated photo rather than a broken image.
  const at = (i) => photos[i]?.url || photos[0]?.url || item.cover_image_url || '';

  // Decorative: the cover title carries the meaning, so alt="" is correct.
  const img = (i, className) => (
    <img src={at(i)} alt="" className={className} loading="lazy" decoding="async" />
  );

  switch (item.cover_style) {
    case 'HERO_BAND':
      return (
        <div className="cover-layout-sage" style={{ backgroundColor: item.base_color || '#8C9386' }}>
          <div className="cover-img-top-wrapper">{img(0, 'cover-img-full')}</div>
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
        <div className="cover-layout-collage">
          <div className="collage-2x2">
            {[0, 1, 2, 3].map((i) => (
              <img key={i} src={at(i)} alt="" loading="lazy" decoding="async" />
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
          {img(0, 'cover-img-half')}
          <div className="cover-banner-white">
            <h4 style={{ color: item.text_color || '#1F2937' }}>{item.cover_title}</h4>
          </div>
          {img(1, 'cover-img-half')}
        </div>
      );
  }
}

export default function BookCarousel3D({ variations, activeIdx, setActiveIdx, onScrollDown, onReshuffleVariations, isReshuffling }) {
  if (!variations || variations.length === 0) return null;

  return (
    <div style={{ width: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
      <h2 className="preview-title">Choose Your Album Variation (3 Saved Styles)</h2>

      {/* Reshuffle Variations Action Bar */}
      {onReshuffleVariations && (
        <button
          className="btn btn-secondary"
          onClick={onReshuffleVariations}
          disabled={isReshuffling}
          style={{ marginBottom: '1rem', padding: '0.5rem 1.25rem', borderRadius: '20px', fontWeight: 600 }}
        >
          <Shuffle size={16} color="var(--px-brand-iris)" strokeWidth={1.75} />
          <span>{isReshuffling ? "Reshuffling Variations..." : "Reshuffle Palettes & Layouts (3 Variations)"}</span>
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
              onClick={() => setActiveIdx(idx)}
              style={{
                borderColor: isHero ? item.accent_color : 'transparent'
              }}
            >
              {isHero && (
                <div className="hero-check-badge">
                  <Check size={18} />
                </div>
              )}

              <CoverArt item={item} />
            </div>
          );
        })}
      </div>

      <button className="scroll-indicator" onClick={onScrollDown} title="Scroll to double page spreads">
        <ChevronDown size={28} />
      </button>
    </div>
  );
}
