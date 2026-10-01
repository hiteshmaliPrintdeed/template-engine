"""
The spread plan: how each variation groups a chapter's photos into spreads.

Shared by the solver (which lays the spreads out) and the story layer (which
must know, BEFORE asking Gemini, how many captions each part of the book needs).
Both call chapter_chunks(), so the number of captions requested and the number
of spreads laid out can never drift apart.

Clustering is deterministic and O(n) with an 8-photo lookahead, so planning all
three variations up front costs milliseconds and no network.
"""

from typing import Any, Dict, List, Sequence

from app.engine.dsa_solver import cluster_photos_2tier_engine

# Stage 1.5: each variation gets a different PACING, so the three differ
# structurally rather than only by palette. Chapter boundaries are untouched —
# reordering them would destroy the chronological narrative that Stage 1.2's
# data-contract fix just restored. Only spread density changes.
VARIATION_STRATEGIES = [
    {"name": "CHRONOLOGICAL", "chunk_size": 3},  # story order, even spreads
    {"name": "HERO_FORWARD", "chunk_size": 2},   # tighter spreads, photos larger
    {"name": "EXPANSIVE", "chunk_size": 4},      # denser collages, more per spread
]
VARIATION_COUNT = len(VARIATION_STRATEGIES)


def chapter_chunks(ch_photos: Sequence[Any], var_idx: int) -> List[List[Any]]:
    """The spreads (photo groups) variation var_idx makes from one chapter."""
    strategy = VARIATION_STRATEGIES[var_idx % len(VARIATION_STRATEGIES)]
    chunk_size = strategy["chunk_size"]
    if len(ch_photos) <= 4:
        chunk_size = max(2, chunk_size - 1)
    return cluster_photos_2tier_engine(list(ch_photos), chunk_size=chunk_size)


def spread_has_people(chunk: Sequence[Any]) -> bool:
    """Whether local face detection found anyone in this spread's photos."""
    return any(int(getattr(p, "face_count", 0) or 0) > 0 for p in chunk)


def caption_demand(
    raw_chapters: Sequence[Dict[str, Any]],
    chapter_segment: Sequence[int],
    segment_count: int,
) -> List[Dict[str, int]]:
    """
    Captions each segment needs so that NO spread in any variation repeats one:
    per segment, the most spreads any single variation gives it, split by
    whether the spread shows people (people lines) or not (neutral lines).

    Variations draw from the same segment pool at different offsets, so the
    pool must cover the densest variation; the others use a subset. Taking the
    maximum of each kind separately can ask for a few more lines than any one
    variation uses -- a handful of output tokens, never a repeat.
    """
    demand = [{"people": 0, "neutral": 0} for _ in range(max(segment_count, 1))]
    for var_idx in range(VARIATION_COUNT):
        counts = [{"people": 0, "neutral": 0} for _ in range(max(segment_count, 1))]
        for ch_i, ch in enumerate(raw_chapters):
            seg = chapter_segment[ch_i] if ch_i < len(chapter_segment) else 0
            for chunk in chapter_chunks(ch.get("photos", []), var_idx):
                counts[seg]["people" if spread_has_people(chunk) else "neutral"] += 1
        for seg, c in enumerate(counts):
            for kind in ("people", "neutral"):
                demand[seg][kind] = max(demand[seg][kind], c[kind])
    return demand
