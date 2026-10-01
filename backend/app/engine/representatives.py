"""
Representative photos for a story segment: which few photos Gemini is shown.

Local processing decides WHICH photos represent a segment; Gemini only
describes what they show. Everything here uses metrics computed at ingest
(hero_score, blur_score, pHashes, capture time) -- no new per-photo analysis --
and makes no network calls.

Selection is deterministic: the same photos always give the same picks, so the
representative ids are a stable part of the vision cache key.
"""

from __future__ import annotations

import io
from typing import Any, Callable, List, Optional, Sequence

from app.config import STORAGE, logger
from app.engine.dsa_solver import compute_phash_distance

REPRESENTATIVES_PER_SEGMENT = 3

# pHash distances run 0-64 for 64-bit hashes. Below this, two thumbnails are
# near-duplicates (a burst of the same moment) and showing Gemini both wastes an
# image slot on information it already has.
NEAR_DUPLICATE_DISTANCE = 10
_MAX_DISTANCE = 64

# Gemini bills an image no larger than 384 px on both sides as a single tile.
# Thumbnails are 512 px; sending them as-is costs more and adds nothing a
# caption needs.
VISION_MAX_SIDE_PX = 384
VISION_JPEG_QUALITY = 80

ImageLoader = Callable[[Any], Optional[bytes]]


def _distance(a: Any, b: Any) -> int:
    """Visual distance between two photos, the smaller of their two pHash views.

    compute_phash_distance returns 99 for a missing hash; clamped to the maximum
    so a photo without hashes reads as 'unlike anything', not as penalised.
    """
    d = min(
        compute_phash_distance(getattr(a, "shell_phash", "") or "", getattr(b, "shell_phash", "") or ""),
        compute_phash_distance(getattr(a, "core_phash", "") or "", getattr(b, "core_phash", "") or ""),
    )
    return min(d, _MAX_DISTANCE)


def _hero(photo: Any) -> float:
    return float(getattr(photo, "hero_score", 0.0) or 0.0)


def _time_third(photo: Any, start: float, span: float) -> Optional[int]:
    t = float(getattr(photo, "timestamp_epoch", 0) or 0)
    if t <= 0 or span <= 0:
        return None
    return min(2, int((t - start) / span * 3))


def thumbnail_storage_key(photo: Any) -> Optional[str]:
    """
    The photo's thumbnail storage key. Photos ingested before thumbnail_key was
    recorded carry only a URL; every media URL is "/uploads/" + the storage key
    (the /uploads route serves keys directly, in local and S3 mode alike), so the
    key is recovered from it -- and validated like any other key, so a URL can
    never become a path outside storage.
    """
    key = getattr(photo, "thumbnail_key", None)
    if key:
        return key
    for attr in ("thumbnail_url", "url"):
        url = getattr(photo, attr, None) or ""
        if url.startswith("/uploads/thumbnails/"):
            candidate = url[len("/uploads/"):]
            try:
                from app.storage.keys import validate_key

                validate_key(candidate)
            except ValueError:
                return None
            return candidate
    return None


def _candidates(photos: Sequence[Any], k: int) -> List[Any]:
    """Photos with a thumbnail, minus the blurriest third when enough remain.

    blur_score is a Laplacian variance: higher is sharper. The filter engine has
    already rejected outright blurry photos; this only keeps Gemini from being
    shown the weakest of the survivors.
    """
    usable = [p for p in photos if thumbnail_storage_key(p)]
    scored = [p for p in usable if getattr(p, "blur_score", None) is not None]
    if len(scored) >= 3 * k:
        cutoff = sorted(float(p.blur_score) for p in scored)[len(scored) // 3]
        sharp = [p for p in usable if getattr(p, "blur_score", None) is None or float(p.blur_score) >= cutoff]
        if len(sharp) >= k:
            usable = sharp
    # Stable order, so ties resolve identically on every run.
    return sorted(usable, key=lambda p: (-_hero(p), str(getattr(p, "id", ""))))


def select_representatives(
    photos: Sequence[Any],
    k: int = REPRESENTATIVES_PER_SEGMENT,
    loader: Optional[ImageLoader] = None,
) -> List[tuple]:
    """
    Up to k (photo, image_bytes) pairs that best represent a segment.

    First pick: the highest hero_score. Each next pick maximises
        0.6 * (distance to the nearest photo already picked) / 64
      + 0.4 * hero_score / 100
    so the set stays visually different -- different scene, composition,
    colour -- without trading away quality entirely. Near-duplicates of a pick
    are excluded while any alternative remains, and among equal scores a photo
    from an unrepresented third of the segment's time range wins, so the picks
    span the segment instead of one burst.

    A photo whose thumbnail cannot be read is skipped and the next-best taken,
    so a missing file costs a candidate, not the segment.
    """
    loader = loader or representative_image_bytes
    pool = _candidates(photos, k)
    if not pool:
        return []

    times = [float(getattr(p, "timestamp_epoch", 0) or 0) for p in pool]
    timed = [t for t in times if t > 0]
    start = min(timed) if timed else 0.0
    span = (max(timed) - start) if timed else 0.0

    picked: List[tuple] = []
    remaining = list(pool)
    while remaining and len(picked) < k:
        if not picked:
            choice = remaining[0]
        else:
            chosen = [p for p, _ in picked]
            covered = {_time_third(p, start, span) for p in chosen}

            def nearest(p):
                return min(_distance(p, c) for c in chosen)

            distinct = [p for p in remaining if nearest(p) >= NEAR_DUPLICATE_DISTANCE]
            field = distinct or remaining
            choice = min(
                field,
                key=lambda p: (
                    -round(0.6 * nearest(p) / _MAX_DISTANCE + 0.4 * _hero(p) / 100.0, 6),
                    _time_third(p, start, span) in covered,   # False (new third) first
                    -_hero(p),
                    str(getattr(p, "id", "")),                # lowest id wins last ties
                ),
            )
        remaining.remove(choice)
        data = loader(choice)
        if data:
            picked.append((choice, data))
    return picked


def representative_image_bytes(photo: Any) -> Optional[bytes]:
    """The photo's thumbnail as a <=384 px JPEG, or None if it cannot be read."""
    key = thumbnail_storage_key(photo)
    if not key:
        return None
    try:
        from PIL import Image

        with STORAGE.open_local(key) as path:
            if not path:
                return None
            with Image.open(path) as img:
                img = img.convert("RGB")
                img.thumbnail((VISION_MAX_SIDE_PX, VISION_MAX_SIDE_PX))
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=VISION_JPEG_QUALITY)
                return buf.getvalue()
    except Exception as exc:  # unreadable, missing, or storage error: skip it
        logger.warning(f"[Representatives] Cannot read thumbnail {key!r} for {getattr(photo, 'id', '?')}: {exc}")
        return None
