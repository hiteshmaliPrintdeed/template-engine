import React, { useState } from 'react';

/**
 * Stage 2.3 — PhotoFrame Component.
 * Reserves exact layout space via aspectRatio (or parent dimensions) and paints
 * a dominant-colour linear gradient placeholder before the image decodes,
 * eliminating Cumulative Layout Shift (CLS) across grids, covers, and spreads.
 */
export default function PhotoFrame({
  src,
  aspectRatio = 1,
  dominantColors,
  alt = '',
  className = '',
  style = {},
  imgStyle = {},
  children
}) {
  const [loaded, setLoaded] = useState(false);

  const bg =
    Array.isArray(dominantColors) && dominantColors.length > 0
      ? `linear-gradient(135deg, ${dominantColors[0]}, ${dominantColors[1] || dominantColors[0]})`
      : 'var(--px-border-subtle, #E4E4E7)';

  return (
    <div
      className={`px-photo-frame ${className}`.trim()}
      style={{
        position: 'relative',
        aspectRatio: aspectRatio ? String(aspectRatio) : undefined,
        background: bg,
        overflow: 'hidden',
        ...style
      }}
    >
      {src && (
        <img
          src={src}
          alt={alt}
          loading="lazy"
          decoding="async"
          onLoad={() => setLoaded(true)}
          className="px-photo-frame-img"
          style={{
            width: '100%',
            height: '100%',
            objectFit: 'cover',
            display: 'block',
            opacity: loaded ? 1 : 0,
            transition: 'opacity 220ms ease-out',
            ...imgStyle
          }}
        />
      )}
      {children}
    </div>
  );
}
