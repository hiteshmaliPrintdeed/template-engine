"""
Photo Album Layout Problem (Pure Dynamic Page Packing Solver)
Calculates exact shrink-wrapped (x, y, w, h) photo bounds directly on the page level.
Includes rich Loguru metrics & mini-step diagnostics for every layout computation step.
"""

import math
import time
import itertools
from typing import List, Dict, Any, Tuple
from app.schemas.photobook import PhotoMeta, TemplateSlot, SinglePage, SpreadPair
from app.engine.color_extractor import THEME_PALETTES, get_best_background_color
from app.config import logger

MARGIN_TOP = 0.05
MARGIN_BOTTOM = 0.06
MARGIN_OUTER = 0.025
MARGIN_GUTTER = 0.039  # Gutter around spine x=0.50
MIN_GAP = 0.018        # Standard 10-12mm gap

LAYOUT_FAMILIES = ["BALANCED", "DOMINANT", "ALTERNATING"]

def get_page_safe_bounds(is_left: bool, has_text: bool) -> Tuple[float, float, float, float]:
    """Returns (x_min, y_min, avail_w, avail_h) for Left or Right page with loguru metrics."""
    y_min = MARGIN_TOP
    avail_h = 1.0 - MARGIN_TOP - MARGIN_BOTTOM - (0.08 if has_text else 0.0)

    if is_left:
        x_min = MARGIN_OUTER
        avail_w = 0.50 - MARGIN_OUTER - MARGIN_GUTTER
    else:
        x_min = 0.50 + MARGIN_GUTTER
        avail_w = 0.50 - MARGIN_OUTER - MARGIN_GUTTER

    logger.debug(f"[DSA Solver] SafeBounds computed | Half: {'Left' if is_left else 'Right'} | HasText: {has_text} | Bounds: x_min={x_min:.4f}, y_min={y_min:.4f}, avail_w={avail_w:.4f}, avail_h={avail_h:.4f}")
    return x_min, y_min, avail_w, avail_h

def fit_photo_in_box(
    ar: float,
    x_min: float,
    y_min: float,
    avail_w: float,
    avail_h: float
) -> Tuple[float, float, float, float]:
    """
    Fits a photo with native aspect ratio `ar` (width/height) into a normalized spread 
    bounding box [x_min, y_min, avail_w, avail_h] while preserving `ar` and centering it.
    
    Spread canvas aspect ratio is 2:1 (width = 2.0 * height).
    Box aspect ratio in real physical units = (avail_w * 2.0) / avail_h.
    """
    if not ar or ar <= 0.05 or math.isnan(ar):
        ar = 1.33

    box_ar = (avail_w * 2.0) / avail_h
    if box_ar > ar:
        # Height is the constraint
        h = avail_h
        w = (h * ar) / 2.0
    else:
        # Width is the constraint
        w = avail_w
        h = (w * 2.0) / ar

    x = x_min + (avail_w - w) / 2.0
    y = y_min + (avail_h - h) / 2.0

    return round(x, 4), round(y, 4), round(w, 4), round(h, 4)

def solve_page_photos_dynamic(
    photo_count: int,
    is_left: bool,
    family_type: str,
    aspect_ratios: List[float],
    has_text: bool
) -> List[Dict[str, Any]]:
    """Dynamically packs 1, 2, or 3 photos into page safe area with detailed mini-step logging."""
    start_time = time.perf_counter()
    x_min, y_min, avail_w, avail_h = get_page_safe_bounds(is_left, has_text)
    slots = []

    logger.debug(f"[DSA Solver Mini-Step] Packing {photo_count} photos | Side: {'Left' if is_left else 'Right'} | Family: {family_type} | ARs: {aspect_ratios}")

    if photo_count == 1:
        ar = aspect_ratios[0] if aspect_ratios else 1.33
        x, y, w, h = fit_photo_in_box(ar, x_min, y_min, avail_w, avail_h)

        slots.append({
            "id": f"photo_{'L' if is_left else 'R'}_1",
            "type": "photo",
            "x_pct": x,
            "y_pct": y,
            "w_pct": w,
            "h_pct": h,
            "target_aspect": round(ar, 4),
            "render_mode": "cover",
            "role": "hero_single"
        })

    elif photo_count == 2:
        ar1 = aspect_ratios[0] if len(aspect_ratios) > 0 else 1.33
        ar2 = aspect_ratios[1] if len(aspect_ratios) > 1 else 1.33

        # Rule 1 & 2: If any photo is Portrait (AR < 1.05), OR if aspect ratios are mixed,
        # FORCE side-by-side columns to prevent squishing portrait photos under landscape photos!
        has_portrait = (ar1 < 1.05 or ar2 < 1.05)
        both_landscape = (ar1 >= 1.1 and ar2 >= 1.1)

        # Option A: Vertical Stack (Top-Bottom) - Only ideal for 2 Landscape photos
        if family_type == "DOMINANT":
            h1_max = (avail_h - MIN_GAP) * 0.60
            h2_max = avail_h - h1_max - MIN_GAP
        else:
            h1_max = (avail_h - MIN_GAP) / 2.0
            h2_max = (avail_h - MIN_GAP) / 2.0

        x1_a, y1_a, w1_a, h1_a = fit_photo_in_box(ar1, x_min, y_min, avail_w, h1_max)
        x2_a, y2_a, w2_a, h2_a = fit_photo_in_box(ar2, x_min, y_min + h1_max + MIN_GAP, avail_w, h2_max)
        area_stack = (w1_a * h1_a) + (w2_a * h2_a)

        # Option B: Proportional Aspect-Ratio Side-by-Side (Left-Right)
        # Calculates exact proportional column widths so both photos align with 100% EQUAL HEIGHT!
        tot_ar = max(0.1, ar1 + ar2)
        avail_w_net = max(0.05, avail_w - MIN_GAP)
        
        w1_sub = avail_w_net * (ar1 / tot_ar)
        # Clamp column width bounds between 25% and 75% for aesthetic balance
        w1_sub = max(avail_w_net * 0.25, min(avail_w_net * 0.75, w1_sub))
        w2_sub = avail_w_net - w1_sub

        x1_b, y1_b, w1_b, h1_b = fit_photo_in_box(ar1, x_min, y_min, w1_sub, avail_h)
        x2_b, y2_b, w2_b, h2_b = fit_photo_in_box(ar2, x_min + w1_sub + MIN_GAP, y_min, w2_sub, avail_h)
        
        # Align vertical top Y coordinates so both photos share the exact same baseline
        common_y = min(y1_b, y2_b)
        y1_b = common_y
        y2_b = common_y

        area_side = (w1_b * h1_b) + (w2_b * h2_b)

        # STRICT RULE: Side-by-Side if any photo is portrait; Vertical stack ONLY if both are landscape
        use_side_by_side = has_portrait or (not both_landscape) or (area_side > area_stack * 0.95)

        if use_side_by_side:
            slots.extend([
                {"id": "photo_1", "type": "photo", "x_pct": x1_b, "y_pct": y1_b, "w_pct": w1_b, "h_pct": h1_b, "target_aspect": round(ar1, 4), "render_mode": "cover", "role": "side_left"},
                {"id": "photo_2", "type": "photo", "x_pct": x2_b, "y_pct": y2_b, "w_pct": w2_b, "h_pct": h2_b, "target_aspect": round(ar2, 4), "render_mode": "cover", "role": "side_right"}
            ])
        else:
            # Re-center vertical stack for 2 landscape photos
            total_h = h1_a + MIN_GAP + h2_a
            start_y = y_min + (avail_h - total_h) / 2.0
            y1_final = start_y
            y2_final = y1_final + h1_a + MIN_GAP

            slots.extend([
                {"id": "photo_1", "type": "photo", "x_pct": x1_a, "y_pct": round(y1_final, 4), "w_pct": w1_a, "h_pct": h1_a, "target_aspect": round(ar1, 4), "render_mode": "cover", "role": "top"},
                {"id": "photo_2", "type": "photo", "x_pct": x2_a, "y_pct": round(y2_final, 4), "w_pct": w2_a, "h_pct": h2_a, "target_aspect": round(ar2, 4), "render_mode": "cover", "role": "bot"}
            ])

    elif photo_count >= 3:
        ar1 = aspect_ratios[0] if len(aspect_ratios) > 0 else 1.33
        ar2 = aspect_ratios[1] if len(aspect_ratios) > 1 else 1.33
        ar3 = aspect_ratios[2] if len(aspect_ratios) > 2 else 1.33

        has_any_portrait = (ar1 < 1.05 or ar2 < 1.05 or ar3 < 1.05)

        if has_any_portrait:
            # Proportional 3-Column Width allocation so all 3 photos align with equal height
            tot_ar = max(0.1, ar1 + ar2 + ar3)
            avail_w_net = max(0.05, avail_w - (2 * MIN_GAP))
            w1_sub = avail_w_net * (ar1 / tot_ar)
            w2_sub = avail_w_net * (ar2 / tot_ar)
            w3_sub = avail_w_net - w1_sub - w2_sub

            x1, y1, w1, h1 = fit_photo_in_box(ar1, x_min, y_min, w1_sub, avail_h)
            x2, y2, w2, h2 = fit_photo_in_box(ar2, x_min + w1_sub + MIN_GAP, y_min, w2_sub, avail_h)
            x3, y3, w3, h3 = fit_photo_in_box(ar3, x_min + w1_sub + w2_sub + (2 * MIN_GAP), y_min, w3_sub, avail_h)

            common_y = min(y1, y2, y3)
            y1 = y2 = y3 = common_y

            slots.extend([
                {"id": "photo_1", "type": "photo", "x_pct": x1, "y_pct": y1, "w_pct": w1, "h_pct": h1, "target_aspect": round(ar1, 4), "render_mode": "cover", "role": "side_1"},
                {"id": "photo_2", "type": "photo", "x_pct": x2, "y_pct": y2, "w_pct": w2, "h_pct": h2, "target_aspect": round(ar2, 4), "render_mode": "cover", "role": "side_2"},
                {"id": "photo_3", "type": "photo", "x_pct": x3, "y_pct": y3, "w_pct": w3, "h_pct": h3, "target_aspect": round(ar3, 4), "render_mode": "cover", "role": "side_3"}
            ])
        elif family_type == "DOMINANT":
            # 1 Hero Top + 2 Sub-photos Bottom Side-by-Side
            h_top_avail = (avail_h - MIN_GAP) * 0.52
            x1, y1, w1, h1 = fit_photo_in_box(ar1, x_min, y_min, avail_w, h_top_avail)

            h_bot_avail = avail_h - h1 - MIN_GAP
            w_sub = (avail_w - MIN_GAP) / 2.0
            y_bot = y1 + h1 + MIN_GAP

            x2, y2, w2, h2 = fit_photo_in_box(ar2, x_min, y_bot, w_sub, h_bot_avail)
            x3, y3, w3, h3 = fit_photo_in_box(ar3, x_min + w_sub + MIN_GAP, y_bot, w_sub, h_bot_avail)

            slots.extend([
                {"id": "photo_1", "type": "photo", "x_pct": x1, "y_pct": y1, "w_pct": w1, "h_pct": h1, "target_aspect": round(ar1, 4), "render_mode": "cover", "role": "hero_top"},
                {"id": "photo_2", "type": "photo", "x_pct": x2, "y_pct": y2, "w_pct": w2, "h_pct": h2, "target_aspect": round(ar2, 4), "render_mode": "cover", "role": "sub_bot_left"},
                {"id": "photo_3", "type": "photo", "x_pct": x3, "y_pct": y3, "w_pct": w3, "h_pct": h3, "target_aspect": round(ar3, 4), "render_mode": "cover", "role": "sub_bot_right"}
            ])
        else:
            # 3 Stacked Photos for Landscape
            h_sub = (avail_h - 2 * MIN_GAP) / 3.0
            x1, y1, w1, h1 = fit_photo_in_box(ar1, x_min, y_min, avail_w, h_sub)
            x2, y2, w2, h2 = fit_photo_in_box(ar2, x_min, y_min + h_sub + MIN_GAP, avail_w, h_sub)
            x3, y3, w3, h3 = fit_photo_in_box(ar3, x_min, y_min + 2 * (h_sub + MIN_GAP), avail_w, h_sub)

            slots.extend([
                {"id": "photo_1", "type": "photo", "x_pct": x1, "y_pct": y1, "w_pct": w1, "h_pct": h1, "target_aspect": round(ar1, 4), "render_mode": "cover", "role": "stack_1"},
                {"id": "photo_2", "type": "photo", "x_pct": x2, "y_pct": y2, "w_pct": w2, "h_pct": h2, "target_aspect": round(ar2, 4), "render_mode": "cover", "role": "stack_2"},
                {"id": "photo_3", "type": "photo", "x_pct": x3, "y_pct": y3, "w_pct": w3, "h_pct": h3, "target_aspect": round(ar3, 4), "render_mode": "cover", "role": "stack_3"}
            ])

    elapsed_ms = (time.perf_counter() - start_time) * 1000
    logger.debug(f"[DSA Solver Mini-Step] Generated {len(slots)} uncropped slots in {elapsed_ms:.2f}ms for {'Left' if is_left else 'Right'} page")
    return slots

def find_best_spread_partition(
    photos: List[PhotoMeta],
    left_family: str,
    right_family: str,
    has_caption: bool
) -> Tuple[List[PhotoMeta], List[PhotoMeta], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Dynamically optimizes photo partitioning across Left and Right facing pages
    to maximize overall double-spread surface area coverage & aspect ratio harmony.
    """
    total = len(photos)
    if total <= 1:
        left_p = photos
        right_p = []
        l_slots = solve_page_photos_dynamic(len(left_p), True, left_family, [p.aspect_ratio for p in left_p], has_caption)
        r_slots = solve_page_photos_dynamic(0, False, right_family, [], False)
        return left_p, right_p, l_slots, r_slots

    best_score = -9999.0
    best_left_p = photos[:math.ceil(total / 2.0)]
    best_right_p = photos[math.ceil(total / 2.0):]
    best_l_slots: List[Dict[str, Any]] = []
    best_r_slots: List[Dict[str, Any]] = []

    possible_left_sizes = [math.ceil(total / 2.0), math.floor(total / 2.0)]
    possible_left_sizes = list(set([s for s in possible_left_sizes if 1 <= s < total]))

    for left_size in possible_left_sizes:
        for left_indices in itertools.combinations(range(total), left_size):
            left_set = set(left_indices)
            right_indices = [i for i in range(total) if i not in left_set]

            cand_left_p = [photos[i] for i in left_indices]
            cand_right_p = [photos[i] for i in right_indices]

            cand_l_slots = solve_page_photos_dynamic(
                len(cand_left_p), True, left_family, [p.aspect_ratio for p in cand_left_p], has_caption
            )
            cand_r_slots = solve_page_photos_dynamic(
                len(cand_right_p), False, right_family, [p.aspect_ratio for p in cand_right_p], False
            )

            area_l = sum(s["w_pct"] * s["h_pct"] for s in cand_l_slots if s.get("type") == "photo")
            area_r = sum(s["w_pct"] * s["h_pct"] for s in cand_r_slots if s.get("type") == "photo")
            total_area = area_l + area_r

            # Aspect Ratio Harmony Bonus:
            # Reward splitting 1 Landscape + 1 Portrait across Left and Right facing pages!
            score = total_area
            if len(cand_left_p) == 1 and len(cand_right_p) == 1:
                ar_l = cand_left_p[0].aspect_ratio
                ar_r = cand_right_p[0].aspect_ratio
                if (ar_l >= 1.1 and ar_r <= 0.95) or (ar_l <= 0.95 and ar_r >= 1.1):
                    score += 0.25  # High bonus for 1L + 1P cross-page balance!

            if score > best_score:
                best_score = score
                best_left_p = cand_left_p
                best_right_p = cand_right_p
                best_l_slots = cand_l_slots
                best_r_slots = cand_r_slots

    return best_left_p, best_right_p, best_l_slots, best_r_slots

# ==============================================================================
# [DISABLED / COMMENTED OUT FOR MVP] - SMART FACE CROPPING & DYNAMIC ALIGNMENT
# ==============================================================================
# def calculate_smart_crop_offset(photo_meta: PhotoMeta, slot_aspect_ratio: float) -> dict:
#     """
#     Calculates dynamic CSS / PDF cropping offset based on face focal points.
#     DISABLED: MVP strictly uses natural unadjusted framing (no cropping / no alignment).
#     """
#     # if getattr(photo_meta, 'face_boxes', None):
#     #     primary_face = photo_meta.face_boxes[0]
#     #     return {
#     #         "crop_x": primary_face.center_x,
#     #         "crop_y": primary_face.center_y,
#     #         "zoom_scale": 1.0
#     #     }
#     # return {"crop_x": 0.5, "crop_y": 0.5, "zoom_scale": 1.0}
# ==============================================================================

def compute_phash_distance(h1: str, h2: str) -> int:
    """Compute true binary bitwise Hamming distance between two hex pHashes."""
    if not h1 or not h2 or len(h1) != len(h2):
        return 99
    try:
        val1 = int(h1, 16)
        val2 = int(h2, 16)
        return bin(val1 ^ val2).count('1')
    except Exception:
        return 99

def cluster_photos_2tier_engine(photos: List[PhotoMeta], chunk_size: int = 3) -> List[List[PhotoMeta]]:
    """
    Tier 2 (Micro-Clustering Engine):
    Pairs photos into Double-Page Spreads (DPS) based on:
    1. Shell pHash Match (Hamming <= 8): Same background location / lighting vibe.
    2. Core pHash Variation (Hamming >= 4): Complementary poses/angles.
    3. Aspect Ratio Balance: Pairs matching ratios (Landscape+Landscape, Portrait+Portrait, or 1L+1P).
    """
    if not photos:
        return []

    # Stage 1.2 guard: this engine is driven entirely by shell/core pHash. When
    # those are empty, compute_phash_distance() returns its 99 no-data sentinel
    # for every pair, no similarity match ever fires, and spreads silently
    # degrade to array order. Surface that instead of failing quietly.
    usable_phash = sum(1 for p in photos if p.shell_phash and p.core_phash)
    if usable_phash == 0:
        logger.warning(
            f"[Cluster] 0/{len(photos)} photos have usable pHashes — "
            f"spread grouping is falling back to array order."
        )
    elif usable_phash < len(photos):
        logger.info(f"[Cluster] {usable_phash}/{len(photos)} photos have usable pHashes")

    n = len(photos)
    if n <= chunk_size:
        return [photos]

    used_indices = set()
    spread_chunks: List[List[PhotoMeta]] = []

    for i in range(n):
        if i in used_indices:
            continue

        anchor = photos[i]
        used_indices.add(i)
        current_spread = [anchor]

        anchor_shell = getattr(anchor, "shell_phash", "")
        anchor_core = getattr(anchor, "core_phash", "")

        # Lookahead in next 8 photos for matching visual scene vibe
        candidates = []
        for j in range(i + 1, min(n, i + 9)):
            if j in used_indices:
                continue

            cand = photos[j]
            cand_shell = getattr(cand, "shell_phash", "")
            cand_core = getattr(cand, "core_phash", "")

            shell_dist = compute_phash_distance(anchor_shell, cand_shell)
            core_dist = compute_phash_distance(anchor_core, cand_core)

            # Score visual affinity: Lower shell distance (same background) + higher core variation (different pose)
            affinity = 0.0
            if shell_dist <= 8:
                affinity += (10.0 - shell_dist) * 2.0
            if core_dist >= 4:
                affinity += 5.0

            # Aspect ratio harmony bonus
            if abs(anchor.aspect_ratio - cand.aspect_ratio) < 0.25:
                affinity += 6.0

            candidates.append((affinity, j, cand))

        # Sort candidate photos by highest visual affinity
        candidates.sort(key=lambda x: x[0], reverse=True)

        needed = min(chunk_size - 1, n - len(used_indices))
        for _, c_idx, c_photo in candidates[:needed]:
            current_spread.append(c_photo)
            used_indices.add(c_idx)

        spread_chunks.append(current_spread)

    # Any leftover photos assigned cleanly
    leftovers = [photos[k] for k in range(n) if k not in used_indices]
    if leftovers:
        if len(spread_chunks[-1]) + len(leftovers) <= 4:
            spread_chunks[-1].extend(leftovers)
        else:
            spread_chunks.append(leftovers)

    logger.info(f"[Tier 2 Micro Clustering] Created {len(spread_chunks)} Double-Page Spread visual scene pairings.")
    return spread_chunks

# Backward compatibility alias
cluster_photos_sliding_window = cluster_photos_2tier_engine

def build_dsa_spread_pair(
    spread_idx: int,
    photos: List[PhotoMeta],
    caption: str,
    theme_name: str,
    family_variant: str = "BALANCED",
    family_variant_seed: int = 0
) -> SpreadPair:
    """Solves double-spread layout with detailed Loguru stats."""
    start_time = time.perf_counter()
    total_photos = len(photos)
    has_left_text = bool(caption)

    if family_variant == "ALTERNATING":
        left_family = "BALANCED" if (spread_idx + family_variant_seed) % 2 == 0 else "DOMINANT"
        right_family = "DOMINANT" if (spread_idx + family_variant_seed) % 2 == 0 else "BALANCED"
    elif family_variant == "DOMINANT":
        left_family = "DOMINANT"
        right_family = "BALANCED"
    else:
        left_family = "BALANCED"
        right_family = "BALANCED"

    # Cross-adjacent facing page photo partitioning optimization
    left_photos, right_photos, left_slots_raw, right_slots_raw = find_best_spread_partition(
        photos, left_family, right_family, has_left_text
    )

    logger.info(f"[DSA Solver Stats] Spread #{spread_idx} | Total Photos: {total_photos} (L:{len(left_photos)}, R:{len(right_photos)}) | Theme: {theme_name} | Layout Variant: {family_variant} (L_family:{left_family}, R_family:{right_family})")

    # Calculate Pre-Flight Print DPI for Left Page Slots (Standard photobook spread: 420mm x 210mm)
    left_colors = []
    for idx, s in enumerate(left_slots_raw):
        if idx < len(left_photos):
            p = left_photos[idx]
            s["photo_id"] = p.id
            s["photo_url"] = p.url
            left_colors.extend(p.dominant_colors)

            # Pre-flight DPI math: slot width in inches = (w_pct * 420mm) / 25.4
            slot_w_in = max(0.1, (s["w_pct"] * 420.0) / 25.4)
            slot_h_in = max(0.1, (s["h_pct"] * 210.0) / 25.4)
            eff_dpi_w = p.width / slot_w_in
            eff_dpi_h = p.height / slot_h_in
            eff_dpi = round(min(eff_dpi_w, eff_dpi_h), 1)

            s["effective_dpi"] = eff_dpi
            if eff_dpi >= 250:
                s["dpi_quality"] = "excellent"
            elif eff_dpi >= 150:
                s["dpi_quality"] = "warning"
            else:
                s["dpi_quality"] = "alert"

    # Calculate Pre-Flight Print DPI for Right Page Slots
    right_colors = []
    for idx, s in enumerate(right_slots_raw):
        if idx < len(right_photos):
            p = right_photos[idx]
            s["photo_id"] = p.id
            s["photo_url"] = p.url
            right_colors.extend(p.dominant_colors)

            slot_w_in = max(0.1, (s["w_pct"] * 420.0) / 25.4)
            slot_h_in = max(0.1, (s["h_pct"] * 210.0) / 25.4)
            eff_dpi_w = p.width / slot_w_in
            eff_dpi_h = p.height / slot_h_in
            eff_dpi = round(min(eff_dpi_w, eff_dpi_h), 1)

            s["effective_dpi"] = eff_dpi
            if eff_dpi >= 250:
                s["dpi_quality"] = "excellent"
            elif eff_dpi >= 150:
                s["dpi_quality"] = "warning"
            else:
                s["dpi_quality"] = "alert"

    if caption:
        left_slots_raw.append({
            "id": "text_left",
            "type": "text",
            "x_pct": 0.05,
            "y_pct": 0.92,
            "w_pct": 0.40,
            "h_pct": 0.05,
            "text_content": caption
        })

    palette = THEME_PALETTES.get(theme_name, THEME_PALETTES["Warm"])
    left_bg = get_best_background_color(left_colors, theme_name)
    right_bg = get_best_background_color(right_colors, theme_name)

    left_page = SinglePage(
        page_number=spread_idx * 2,
        background_color=left_bg,
        text_color=palette["text"],
        slots=[TemplateSlot(**s) for s in left_slots_raw]
    )

    right_page = SinglePage(
        page_number=spread_idx * 2 + 1,
        background_color=right_bg,
        text_color=palette["text"],
        slots=[TemplateSlot(**s) for s in right_slots_raw]
    )

    elapsed_ms = (time.perf_counter() - start_time) * 1000
    logger.info(f"[Metrics] Spread #{spread_idx} built successfully in {elapsed_ms:.2f}ms | Left BG: {left_bg} | Right BG: {right_bg}")

    return SpreadPair(
        spread_index=spread_idx,
        left_page=left_page,
        right_page=right_page
    )

def reshuffle_single_spread_engine(
    spread: SpreadPair,
    theme_name: str,
    variant_seed: int,
    include_text: bool = True,
) -> SpreadPair:
    """Reshuffles a single spread's layout on click with detailed loguru stats."""
    start_time = time.perf_counter()
    logger.info(
        f"[DSA Reshuffle API] Reshuffling Spread #{spread.spread_index} | "
        f"Theme: {theme_name} | Seed: {variant_seed} | include_text={include_text}"
    )

    all_photos = []
    caption = ""

    for slot in (spread.left_page.slots + spread.right_page.slots):
        if slot.type == "photo" and slot.photo_url:
            ar = slot.target_aspect or 1.33
            all_photos.append(PhotoMeta(
                id=slot.photo_id or "p1",
                filename="photo.jpg",
                url=slot.photo_url,
                width=800,
                height=int(800 / max(0.1, ar)),
                aspect_ratio=ar,
                dominant_colors=["#FFF9F2"]
            ))
        elif slot.type == "text" and slot.text_content:
            caption = slot.text_content

    if not include_text:
        caption = ""

    family_choice = LAYOUT_FAMILIES[variant_seed % len(LAYOUT_FAMILIES)]
    logger.debug(f"[DSA Reshuffle Mini-Step] Selected new family: {family_choice} for {len(all_photos)} photos")

    new_spread = build_dsa_spread_pair(
        spread_idx=spread.spread_index,
        photos=all_photos,
        caption=caption,
        theme_name=theme_name,
        family_variant=family_choice,
        family_variant_seed=variant_seed
    )

    elapsed_ms = (time.perf_counter() - start_time) * 1000
    logger.info(f"[Metrics] Reshuffled Spread #{spread.spread_index} completed in {elapsed_ms:.2f}ms")
    return new_spread

