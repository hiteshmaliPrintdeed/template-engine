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

    # Tier 1: Macro Temporal + GPS Story Chapters
    macro_chapters = partition_macro_chapters(photos)

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

        # Tier 2: Micro-Clustering (Shell & Core pHash Visual Similarity per Chapter)
        for ch in macro_chapters:
            ch_photos = ch.get("photos", [])
            ch_title = ch.get("chapter_title", "")
            # Stage 1.5: chunk size comes from the variation's pacing strategy.
            chunk_size = strategy["chunk_size"]
            if len(ch_photos) <= 4:
                chunk_size = max(2, chunk_size - 1)
            photo_chunks = cluster_photos_2tier_engine(ch_photos, chunk_size=chunk_size)

            for c_i, chunk in enumerate(photo_chunks):
                # Stage 3.2: Gate BOTH caption branches (chapter-title and rotation) on include_text
                if not include_text:
                    caption = ""
                elif c_i == 0 and ch_title and len(macro_chapters) > 1:
                    caption = ch_title.upper()
                else:
                    caption = captions[(spread_idx - 1) % len(captions)]

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
            cover_title=(custom_title.upper() if custom_title else var_info.get("cover_title")) or "YOUR PHOTOBOOK",
            cover_subtitle=subtitle or var_info.get("cover_subtitle") or "A COLLECTION OF MEMORIES",
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
