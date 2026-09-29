"""
Cost-Function Layout Solver & Photobook Generator for PTE
Calculates non-overlapping Double-Page Spread layouts using DSA Bounded Engine.
Applies 20 Canonical Themes with 5 Semantic Color Roles (background, surface, primary, accent, text).
Supports exact 3 persistent saved book variations & on-click spread reshuffling.
"""

from typing import List, Dict, Any, Set, Optional
from app.schemas.photobook import (
    PhotoMeta, TemplateSlot, SinglePage, SpreadPair, PhotobookVariation
)
from app.engine.dsa_solver import build_dsa_spread_pair, reshuffle_single_spread_engine, LAYOUT_FAMILIES, cluster_photos_2tier_engine
from app.engine.story_ai import partition_macro_chapters
from app.engine.story_content import StoryContext, chapter_signature, to_display
from app.engine.color_extractor import THEME_PALETTES, calculate_yiq_text_color
from app.engine.cover_selector import select_covers
from app.config import logger

# Stage 1.5: each variation gets a different PACING, so the three differ
# structurally rather than only by palette. Chapter boundaries are untouched —
# reordering them would destroy the chronological narrative that Stage 1.2's
# data-contract fix just restored. Only spread density changes.
VARIATION_STRATEGIES = [
    {"name": "CHRONOLOGICAL", "chunk_size": 3},  # story order, even spreads
    {"name": "HERO_FORWARD", "chunk_size": 2},   # tighter spreads, photos larger
    {"name": "EXPANSIVE", "chunk_size": 4},      # denser collages, more per spread
]


def generate_photobook_variations_engine(
    photos: List[PhotoMeta],
    ai_batch_result: Dict[str, Any],
    variant_seed_offset: int = 0,
    custom_title: Optional[str] = None,
    include_text: bool = True,
    subtitle: Optional[str] = None,
    story_context: Optional[StoryContext] = None,
) -> List[PhotobookVariation]:
    """
    Generates exactly 3 distinct persistent Photobook Variations applying
    2-Tier Intelligent Clustering (Macro Chapters + Micro pHash Spread Matching) and DSA Solver.

    Deterministic: no randomness anywhere in this path, so identical input always
    yields identical output. The golden tests depend on that.
    """
    variations_data = ai_batch_result.get("variations", [])
    result_variations: List[PhotobookVariation] = []

    default_themes = ["Warm", "Elegant", "Minimal"]

    # Tier 1: Macro Temporal + GPS Story Chapters. A story_context already holds
    # them -- the SAME partition the chapter captions were written for -- so
    # reuse it rather than partition twice.
    if story_context is not None:
        macro_chapters = story_context.raw_chapters
    else:
        macro_chapters = partition_macro_chapters(photos)

    # Per-segment chapter content, applied only to the photo set it was written
    # for. A signature mismatch means the photos changed since: lay out with
    # book-level captions rather than put one segment's text on another's photos.
    seg_map: Optional[List[int]] = None
    seg_content: Optional[List[Optional[Dict[str, Any]]]] = None
    chapter_info = ai_batch_result.get("chapters")
    if chapter_info:
        mapping = chapter_info.get("chapter_segment") or []
        if chapter_info.get("signature") != chapter_signature(macro_chapters) or len(mapping) != len(macro_chapters):
            logger.warning("[Solver] Chapter content does not match this photo set; using book-level captions")
        else:
            seg_map = mapping
            seg_content = chapter_info.get("segments") or []
    n_segments = len(seg_content) if seg_content else 0

    # Cover sets are chosen ONCE across all variations so no photo appears on
    # more than one cover. Choosing per-variation would hand every variation the
    # same top-ranked hero.
    cover_sets = select_covers(photos, variation_count=3)

    for var_idx in range(3):
        if var_idx < len(variations_data):
            var_info = variations_data[var_idx]
            theme_name = var_info.get("theme_name", default_themes[var_idx])
        else:
            var_info = {}
            theme_name = default_themes[var_idx]

        palette = THEME_PALETTES.get(theme_name, THEME_PALETTES["Warm"])

        captions = var_info.get("captions") or [
            "THE JOURNEY BEGINS AT FIRST LIGHT",
            "GOLDEN HORIZONS IN SOFT FOCUS",
            "TOGETHER IN THE SOFT AFTERNOON",
            "GENTLE SPIRITS IN STILLNESS",
            "A GLOWING END TO THE DAY"
        ]

        family_variant = LAYOUT_FAMILIES[(var_idx + variant_seed_offset) % len(LAYOUT_FAMILIES)]
        strategy = VARIATION_STRATEGIES[var_idx % len(VARIATION_STRATEGIES)]
        spreads: List[SpreadPair] = []
        spread_idx = 1
        seg_spread_count: Dict[int, int] = {}

        # Tier 2: Micro-Clustering (Shell & Core pHash Visual Similarity per Chapter)
        for ch_i, ch in enumerate(macro_chapters):
            ch_photos = ch.get("photos", [])
            ch_title = ch.get("chapter_title", "")
            seg_i = seg_map[ch_i] if seg_map is not None else None
            seg = seg_content[seg_i] if (seg_content is not None and seg_i is not None and seg_i < n_segments) else None
            starts_segment = seg_map is not None and (ch_i == 0 or seg_map[ch_i - 1] != seg_i)
            # Stage 1.5: chunk size comes from the variation's pacing strategy.
            chunk_size = strategy["chunk_size"]
            if len(ch_photos) <= 4:
                chunk_size = max(2, chunk_size - 1)
            photo_chunks = cluster_photos_2tier_engine(ch_photos, chunk_size=chunk_size)

            for c_i, chunk in enumerate(photo_chunks):
                # Caption priority. Rows 1, 3 and 5 are the original behaviour and
                # are all that runs without chapter content (always true offline).
                #   1. include_text off           -> no text at all (Stage 3.2)
                #   2. first spread of a segment  -> the segment's title
                #   3. first spread of a chapter  -> generic chapter label, only
                #      where there is no usable segment content
                #   4. inside a segment           -> the segment's caption pool,
                #      offset per variation so the three books differ
                #   5. otherwise                  -> the variation's caption pool
                if not include_text:
                    caption = ""
                elif seg and c_i == 0 and starts_segment and n_segments > 1:
                    caption = seg["title"]
                elif seg is None and c_i == 0 and ch_title and len(macro_chapters) > 1:
                    caption = ch_title.upper()
                elif seg:
                    k = seg_spread_count.get(seg_i, 0)
                    caption = seg["captions"][(k + var_idx) % len(seg["captions"])]
                    seg_spread_count[seg_i] = k + 1
                else:
                    caption = captions[(spread_idx - 1) % len(captions)]
                # The single display boundary: stored text is raw, the page is not.
                caption = to_display(caption)

                spread = build_dsa_spread_pair(
                    spread_idx=spread_idx,
                    photos=chunk,
                    caption=caption,
                    theme_name=theme_name,
                    family_variant=family_variant,
                    family_variant_seed=variant_seed_offset + spread_idx
                )
                spreads.append(spread)
                spread_idx += 1

        # Stage 1.5: hero-ranked, non-overlapping cover set for this variation.
        cover = cover_sets[var_idx] if var_idx < len(cover_sets) else {"cover_style": "SPLIT_BANNER", "cover_photos": []}
        cover_photos = cover["cover_photos"]

        variation = PhotobookVariation(
            id=f"var_{var_idx + 1}",
            variation_title=var_info.get("variation_title", f"{theme_name} Style {var_idx + 1}"),
            theme_name=theme_name,
            cover_title=to_display(custom_title or var_info.get("cover_title")) or "YOUR PHOTOBOOK",
            # A subtitle the user typed is kept exactly as typed -- it always has
            # been -- while generated subtitles follow the display rule.
            cover_subtitle=subtitle or to_display(var_info.get("cover_subtitle")) or "A COLLECTION OF MEMORIES",
            cover_style=cover["cover_style"],
            cover_photos=cover_photos,
            cover_image_url=cover_photos[0].url if cover_photos else "",
            base_color=palette["background"],
            accent_color=palette["accent"],
            text_color=palette["text"],
            spreads=spreads
        )
        result_variations.append(variation)

    signatures = [
        tuple(len(s.left_page.slots) + len(s.right_page.slots) for s in v.spreads)
        for v in result_variations
    ]
    logger.info(
        f"[Solver] Generated {len(result_variations)} variations | "
        f"spread counts {[len(v.spreads) for v in result_variations]} | "
        f"distinct structures {len(set(signatures))}/3"
    )
    if len(set(signatures)) == 1 and len(result_variations) > 1:
        logger.warning(
            "[Solver] All variations have identical spread structure — "
            "pacing strategies had no effect (too few photos per chapter?)."
        )

    return result_variations
