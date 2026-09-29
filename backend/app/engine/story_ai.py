"""
Gemini AI Story & Theme Engine for Pixovo Template Engine (PTE)
1. Categorizes user prompt into 1 of 6 Canonical Categories.
2. Selects 3 distinct theme variations from the 20 Canonical Themes matrix based on Category -> Theme mapping.
3. Generates custom cover titles, subtitles, and spread captions.
4. Provides robust offline fallback when GEMINI_API_KEY is missing or network fails.

========================================================================================
[PRODUCTION BLUEPRINT: 1,000-PHOTO HIERARCHICAL AI CHUNKING ARCHITECTURE]
----------------------------------------------------------------------------------------
When scaling to 1,000 photos per album, DO NOT pass 1,000 individual photo metadata objects 
to Gemini directly (this causes prompt token exhaustion and HTTP 429 rate limit errors).

Future AI Execution Flow:
1. Tier 1 (Pure Math Local Partitioning - partition_macro_chapters):
   Group 1,000 photos into 10-15 Chronological / Geo Chapters using timestamp gaps (>45m) 
   and GPS distance shifts (>5km).
2. Tier 2 (Compact Cluster Summary Prompt):
   Send ONLY the 10-15 Chapter Summaries (approx 1,500 tokens total) to Gemini:
   [
     {"chapter_id": 1, "photos_count": 75, "time_range": "09:00 - 11:30", "location_anchor": "Coastline"},
     {"chapter_id": 2, "photos_count": 120, "time_range": "12:00 - 14:30", "location_anchor": "Reception"}
   ]
3. Tier 3 (Layout Engine Allocation):
   The DSA Solver allocates spread templates per chapter without requiring individual photo AI calls.
========================================================================================
"""

import time
import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Dict, Any, List, Optional
from app.config import GEMINI_API_KEY, logger
from app.engine.color_extractor import CATEGORY_THEMES_MAP, THEME_PALETTES, CATEGORY_TYPOGRAPHY_MAP
from app.db.session_store import SessionStore

ALLOWED_CATEGORIES = list(CATEGORY_THEMES_MAP.keys())
GEMINI_TIMEOUT_SEC = 6.0
ENABLE_GEMINI_API = bool(GEMINI_API_KEY)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine formula to compute geographical distance in km."""
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return 0.0
    try:
        import math
        r = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat / 2.0)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2.0)**2
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        return r * c
    except Exception:
        return 0.0


def partition_macro_chapters(
    photos: List[Any],
    time_gap_threshold_sec: float = 2700.0,
    gps_distance_threshold_km: float = 5.0
) -> List[Dict[str, Any]]:
    """
    Tier 1 (Macro-Clustering Engine):
    Partitions photos into cohesive narrative Story Chapters based on:
    - Time Gap Delta > 45 minutes (2700s)
    - GPS Haversine Distance > 5.0 km
    - Dynamic Capacity: Scales max photos per chapter (12 to 28) for up to 1,000 photos per session.
    """
    if not photos:
        return []

    sorted_photos = sorted(
        photos,
        key=lambda p: (
            getattr(p, "timestamp_epoch", 0) if hasattr(p, "timestamp_epoch")
            else (p.get("timestamp_epoch", 0) if isinstance(p, dict) else 0)
        )
    )

    total_count = len(sorted_photos)
    if total_count > 200:
        max_per_chapter = 24
    elif total_count > 50:
        max_per_chapter = 16
    else:
        max_per_chapter = 12

    chapters: List[Dict[str, Any]] = []
    current_chapter_photos = [sorted_photos[0]]
    ch_idx = 1
    split_reasons = {"time": 0, "gps": 0, "cap": 0}

    for i in range(1, total_count):
        prev = sorted_photos[i - 1]
        curr = sorted_photos[i]

        t_prev = getattr(prev, "timestamp_epoch", 0) if hasattr(prev, "timestamp_epoch") else (prev.get("timestamp_epoch", 0) if isinstance(prev, dict) else 0)
        t_curr = getattr(curr, "timestamp_epoch", 0) if hasattr(curr, "timestamp_epoch") else (curr.get("timestamp_epoch", 0) if isinstance(curr, dict) else 0)

        lat_prev = getattr(prev, "latitude", None) if hasattr(prev, "latitude") else (prev.get("latitude") if isinstance(prev, dict) else None)
        lon_prev = getattr(prev, "longitude", None) if hasattr(prev, "longitude") else (prev.get("longitude") if isinstance(prev, dict) else None)
        lat_curr = getattr(curr, "latitude", None) if hasattr(curr, "latitude") else (curr.get("latitude") if isinstance(curr, dict) else None)
        lon_curr = getattr(curr, "longitude", None) if hasattr(curr, "longitude") else (curr.get("longitude") if isinstance(curr, dict) else None)

        time_gap = abs(t_curr - t_prev) if (t_curr > 0 and t_prev > 0) else 0.0
        gps_dist = haversine_km(lat_prev, lon_prev, lat_curr, lon_curr)

        split_on_time = time_gap > time_gap_threshold_sec
        split_on_gps = gps_dist > gps_distance_threshold_km
        split_on_cap = len(current_chapter_photos) >= max_per_chapter
        is_split = split_on_time or split_on_gps or split_on_cap

        if split_on_time:
            split_reasons["time"] += 1
        elif split_on_gps:
            split_reasons["gps"] += 1
        elif split_on_cap:
            split_reasons["cap"] += 1

        if is_split and current_chapter_photos:
            chapters.append({
                "chapter_id": f"chapter_{ch_idx}",
                "chapter_title": f"Chapter {ch_idx}: Story Sequence",
                "photos": current_chapter_photos
            })
            ch_idx += 1
            current_chapter_photos = [curr]
        else:
            current_chapter_photos.append(curr)

    if current_chapter_photos:
        chapters.append({
            "chapter_id": f"chapter_{ch_idx}",
            "chapter_title": f"Chapter {ch_idx}: Highlights",
            "photos": current_chapter_photos
        })

    dated = sum(
        1 for p in sorted_photos
        if (getattr(p, "timestamp_epoch", 0) or (p.get("timestamp_epoch", 0) if isinstance(p, dict) else 0)) > 0
    )
    logger.info(
        f"[Tier 1 Macro Clustering] Partitioned {len(photos)} photos into {len(chapters)} Story Chapters "
        f"| splits: time={split_reasons['time']} gps={split_reasons['gps']} cap={split_reasons['cap']} "
        f"| photos with capture time: {dated}/{total_count}"
    )
    if dated == 0 and total_count > 1:
        logger.warning(
            "[Tier 1 Macro Clustering] No photo has a capture time — chapters are fixed-size "
            "chunks of upload order, not story chapters."
        )
    return chapters


def _classify_prompt_category(user_prompt: str) -> str:
    """Classifies a prompt into one of the 6 canonical themes in CATEGORY_THEMES_MAP."""
    prompt_lower = (user_prompt or "").lower()

    if any(k in prompt_lower for k in ("wedding", "marriage", "party", "birthday", "celebrat", "anniversary", "gathering")):
        return "Celebration"
    if any(k in prompt_lower for k in ("travel", "trip", "vacation", "beach", "journey", "road", "holiday", "adventure", "coast")):
        return "Travel"
    if any(k in prompt_lower for k in ("portrait", "selfie", "studio", "editorial")):
        return "Portraits"
    if any(k in prompt_lower for k in ("gradu", "office", "college", "milestone", "award", "career", "achievement")):
        return "Milestones"
    if any(k in prompt_lower for k in ("memory", "memories", "archive", "retro", "nostalg", "weekend", "reflection", "heritage")):
        return "Memories"
    return "Family"


def _build_batch_from_category_and_captions(
    primary_category: str,
    user_prompt: str,
    titles: List[str],
    subtitles: List[str],
    captions: List[str],
    custom_title: Optional[str] = None,
    include_text: bool = True,
    subtitle: Optional[str] = None,
) -> Dict[str, Any]:
    """Builds the canonical 3-variation batch dict from category, titles, subtitles, and captions."""
    if primary_category not in CATEGORY_THEMES_MAP:
        primary_category = _classify_prompt_category(user_prompt)

    candidate_themes = CATEGORY_THEMES_MAP.get(primary_category, ["Warm", "Classic", "Nostalgic"])
    theme1 = candidate_themes[0]
    theme2 = candidate_themes[1] if len(candidate_themes) > 1 else "Minimal"
    theme3 = candidate_themes[2] if len(candidate_themes) > 2 else "Editorial"

    typo_info = CATEGORY_TYPOGRAPHY_MAP.get(primary_category, CATEGORY_TYPOGRAPHY_MAP["Family"])

    eff_captions = captions if include_text else []
    t1 = (custom_title.upper() if custom_title else (titles[0] if len(titles) > 0 else "CHERISHED MOMENTS"))
    t2 = (custom_title.upper() if custom_title else (titles[1] if len(titles) > 1 else f"CHRONICLES OF {t1}"))
    t3 = (custom_title.upper() if custom_title else (titles[2] if len(titles) > 2 else "DAYTIME UNFOLDED"))

    s1 = subtitle or (subtitles[0] if len(subtitles) > 0 else "A COLLECTION OF MEMORIES")
    s2 = subtitle or (subtitles[1] if len(subtitles) > 1 else "A PICTORIAL JOURNEY")
    s3 = subtitle or (subtitles[0] if len(subtitles) > 0 else "ARCHIVE EDITION")

    return {
        "primary_category": primary_category,
        "primary_theme": theme1,
        "typography": typo_info,
        "titles": titles,
        "subtitles": subtitles,
        "category": primary_category,
        "suggested_captions": captions,
        "variations": [
            {
                "variation_id": "var_1",
                "variation_title": f"{theme1} Storybook",
                "theme_name": theme1,
                "heading_font": typo_info["heading_font"],
                "body_font": typo_info["body_font"],
                "cover_title": t1,
                "cover_subtitle": s1,
                "captions": eff_captions or [
                    "THE JOURNEY BEGINS AT FIRST LIGHT",
                    "GOLDEN HORIZONS IN SOFT FOCUS",
                    "TOGETHER IN THE QUIET AFTERNOON",
                    "MOMENTS TO TREASURE FOREVER",
                ],
            },
            {
                "variation_id": "var_2",
                "variation_title": f"{theme2} Minimalist",
                "theme_name": theme2,
                "heading_font": typo_info["heading_font"],
                "body_font": typo_info["body_font"],
                "cover_title": t2,
                "cover_subtitle": s2,
                "captions": eff_captions or [
                    "FIRST LIGHT REFLECTIONS",
                    "TIMELESS PERSPECTIVES",
                    "SHARED LAUGHTER & WARMTH",
                    "UNFORGETTABLE FOOTPRINTS",
                ],
            },
            {
                "variation_id": "var_3",
                "variation_title": f"{theme3} Chronicle",
                "theme_name": theme3,
                "heading_font": typo_info["heading_font"],
                "body_font": typo_info["body_font"],
                "cover_title": t3,
                "cover_subtitle": s3,
                "captions": eff_captions or [
                    "STEPPING INTO STILLNESS",
                    "STORIES FRAMED IN LIGHT",
                    "GOLDEN HOUR TOGETHERNESS",
                    "MEMORIES WRITTEN IN SUNLIGHT",
                ],
            },
        ],
    }


def get_fallback_ai_response(
    user_prompt: str,
    custom_title: Optional[str] = None,
    include_text: bool = True,
    subtitle: Optional[str] = None,
) -> Dict[str, Any]:
    """Generates structured fallback themes, 4 titles, 2 subtitles, and captions offline."""
    primary_category = _classify_prompt_category(user_prompt)
    clean_prompt = (user_prompt or "").strip().upper()
    short_anchor = clean_prompt[:32].strip() if clean_prompt else "CHERISHED MOMENTS"

    titles = [
        custom_title.upper() if custom_title else short_anchor,
        f"THE {primary_category.upper()} ARCHIVE",
        f"CHRONICLES OF {short_anchor[:20]}".strip(),
        "LIGHT, TIME & TOGETHERNESS",
    ]
    subtitles = [
        subtitle or "A COLLECTION OF MEMORIES",
        subtitle or "EDITORIAL ARCHIVE EDITION",
    ]
    captions = [
        "THE JOURNEY BEGINS AT FIRST LIGHT",
        "GOLDEN HORIZONS IN SOFT FOCUS",
        "TOGETHER IN THE SOFT AFTERNOON",
        "MOMENTS TO TREASURE FOREVER",
    ]

    typo_info = CATEGORY_TYPOGRAPHY_MAP.get(primary_category, CATEGORY_TYPOGRAPHY_MAP["Family"])
    logger.info(
        f"[StoryAI Fallback] User occasion: '{user_prompt}' -> Category: '{primary_category}' "
        f"-> Typo: {typo_info['heading_font']}/{typo_info['body_font']}"
    )

    return _build_batch_from_category_and_captions(
        primary_category=primary_category,
        user_prompt=user_prompt,
        titles=titles,
        subtitles=subtitles,
        captions=captions,
        custom_title=custom_title,
        include_text=include_text,
        subtitle=subtitle,
    )


def _call_with_timeout(fn, timeout_sec: float = GEMINI_TIMEOUT_SEC):
    """Runs a blocking SDK call inside a 1-worker thread pool with a hard timeout."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(fn)
        return future.result(timeout=timeout_sec)


def _invoke_gemini_json(prompt_text: str) -> Dict[str, Any]:
    """Calls Gemini (`gemini-3.5-flash-lite`) via google.genai or legacy google.generativeai with a 6s timeout."""
    try:
        from google import genai
        from google.genai import types

        def _run_genai():
            client = genai.Client(api_key=GEMINI_API_KEY)
            resp = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=prompt_text,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.4,
                ),
            )
            return json.loads(resp.text)

        return _call_with_timeout(_run_genai, GEMINI_TIMEOUT_SEC)
    except Exception as e1:
        logger.warning(f"[StoryAI] google-genai call failed or timed out ({e1}). Trying legacy google-generativeai SDK...")

    import google.generativeai as genai_legacy

    def _run_legacy():
        genai_legacy.configure(api_key=GEMINI_API_KEY)
        model = genai_legacy.GenerativeModel("gemini-3.5-flash-lite")
        resp = model.generate_content(
            prompt_text,
            generation_config={"response_mime_type": "application/json"},
        )
        return json.loads(resp.text)

    return _call_with_timeout(_run_legacy, GEMINI_TIMEOUT_SEC)


def suggest_creative_titles(
    user_prompt: str,
    photo_count: int = 0,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Proposes 4 tailored book cover titles, 2 matching subtitles, category classification,
    and 4 caption lines. Cached in SessionStore by session_id so a session only invokes
    Gemini (or the fallback generator) once across both title brainstorming and job generation.
    """
    start_time = time.perf_counter()

    if session_id:
        cached = SessionStore.get_title_suggestions(session_id)
        if cached and isinstance(cached, dict) and cached.get("titles"):
            logger.info(f"[StoryAI] Returning cached title suggestions for session={session_id}")
            return {
                "titles": cached["titles"],
                "subtitles": cached["subtitles"],
                "category": cached["category"],
                "suggested_captions": cached["suggested_captions"],
            }

    batch: Optional[Dict[str, Any]] = None
    if ENABLE_GEMINI_API and GEMINI_API_KEY:
        try:
            prompt_text = f"""
            User Occasion / Story: "{user_prompt}" (Total photos: {photo_count}).
            Categorize into EXACTLY ONE of: {json.dumps(ALLOWED_CATEGORIES)}.
            Return valid JSON with:
            {{
                "category": "<Selected Category>",
                "titles": ["<Title 1>", "<Title 2>", "<Title 3>", "<Title 4>"],
                "subtitles": ["<Subtitle 1>", "<Subtitle 2>"],
                "suggested_captions": ["<Caption 1>", "<Caption 2>", "<Caption 3>", "<Caption 4>"]
            }}
            """
            raw = _invoke_gemini_json(prompt_text)
            titles = [str(t).strip().upper() for t in (raw.get("titles") or []) if str(t).strip()][:4]
            subtitles = [str(s).strip().upper() for s in (raw.get("subtitles") or []) if str(s).strip()][:2]
            captions = [str(c).strip().upper() for c in (raw.get("suggested_captions") or []) if str(c).strip()][:4]
            category = str(raw.get("category") or "").strip()
            if len(titles) >= 4 and len(subtitles) >= 2 and category in ALLOWED_CATEGORIES and len(captions) >= 4:
                batch = _build_batch_from_category_and_captions(
                    primary_category=category,
                    user_prompt=user_prompt,
                    titles=titles,
                    subtitles=subtitles,
                    captions=captions,
                )
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                logger.info(f"[Metrics] Gemini suggest-titles succeeded in {elapsed_ms:.2f}ms | Category: '{category}'")
        except Exception as exc:
            logger.warning(f"[StoryAI] suggest_creative_titles Gemini call failed ({exc}); using fallback.")

    if batch is None:
        batch = get_fallback_ai_response(user_prompt)

    if session_id:
        SessionStore.save_title_suggestions(session_id, batch)

    return {
        "titles": batch["titles"][:4],
        "subtitles": batch["subtitles"][:2],
        "category": batch["category"],
        "suggested_captions": batch["suggested_captions"][:4],
    }


def generate_story_theme_batch(
    user_prompt: str,
    total_photos: int = 10,
    session_id: Optional[str] = None,
    custom_title: Optional[str] = None,
    include_text: bool = True,
    subtitle: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Calls Gemini API or uses fast intelligent local NLP theme & caption engine.
    Checks SessionStore for a cached suggest_creative_titles result under session_id first
    so a session never makes a second AI call on generate-async.
    """
    start_time = time.perf_counter()

    if session_id:
        cached = SessionStore.get_title_suggestions(session_id)
        if cached and isinstance(cached, dict) and cached.get("category"):
            logger.info(f"[StoryAI] Reusing cached session AI batch for session={session_id}")
            return _build_batch_from_category_and_captions(
                primary_category=cached.get("category") or cached.get("primary_category", "Family"),
                user_prompt=user_prompt,
                titles=cached.get("titles") or [],
                subtitles=cached.get("subtitles") or [],
                captions=cached.get("suggested_captions") or [],
                custom_title=custom_title,
                include_text=include_text,
                subtitle=subtitle,
            )

    if not ENABLE_GEMINI_API or not GEMINI_API_KEY:
        logger.info(f"[StoryAI] Local theme engine active. Generating layout styles for: '{user_prompt}'")
        res = get_fallback_ai_response(
            user_prompt,
            custom_title=custom_title,
            include_text=include_text,
            subtitle=subtitle,
        )
        if session_id:
            SessionStore.save_title_suggestions(session_id, res)
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            f"[StoryAI] Local Story & Theme batch generated in {elapsed_ms:.2f}ms | "
            f"Category: '{res.get('primary_category')}' | Primary Theme: '{res.get('primary_theme')}'"
        )
        return res

    try:
        prompt_text = f"""
        User Occasion / Emotion: "{user_prompt}" (Total photos: {total_photos}).
        
        Task:
        1. Categorize this occasion into EXACTLY ONE of these Top Categories:
           {json.dumps(ALLOWED_CATEGORIES)}
        
        2. Map the category to candidate themes using this matrix:
           {json.dumps(CATEGORY_THEMES_MAP)}
        
        3. Generate 3 distinct photobook design variations in valid JSON format:
        {{
            "primary_category": "<Selected Category>",
            "primary_theme": "<Selected Primary Theme from mapped list>",
            "variations": [
                {{
                    "variation_id": "var_1",
                    "variation_title": "Variation Style 1",
                    "theme_name": "<Theme Name 1 from category mapped list>",
                    "cover_title": "<Customized title based on user occasion>",
                    "cover_subtitle": "<Subtitle e.g. 2026 EDITION>",
                    "captions": ["Caption 1", "Caption 2", "Caption 3", "Caption 4"]
                }},
                {{
                    "variation_id": "var_2",
                    "variation_title": "Variation Style 2",
                    "theme_name": "<Theme Name 2 from category mapped list>",
                    "cover_title": "<Customized title 2>",
                    "cover_subtitle": "<Subtitle>",
                    "captions": ["Caption 1", "Caption 2", "Caption 3", "Caption 4"]
                }},
                {{
                    "variation_id": "var_3",
                    "variation_title": "Variation Style 3",
                    "theme_name": "<Theme Name 3 from category mapped list>",
                    "cover_title": "<Customized title 3>",
                    "cover_subtitle": "<Subtitle>",
                    "captions": ["Caption 1", "Caption 2", "Caption 3", "Caption 4"]
                }}
            ]
        }}
        """
        data = _invoke_gemini_json(prompt_text)
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            f"[Metrics] Gemini API call succeeded in {elapsed_ms:.2f}ms | "
            f"Category: '{data.get('primary_category')}' | Primary Theme: '{data.get('primary_theme')}'"
        )
        if session_id:
            vars_list = data.get("variations") or []
            titles = [v.get("cover_title", "YOUR PHOTOBOOK") for v in vars_list]
            while len(titles) < 4:
                titles.append("LIGHT, TIME & TOGETHERNESS")
            subtitles = [v.get("cover_subtitle", "A COLLECTION OF MEMORIES") for v in vars_list[:2]]
            while len(subtitles) < 2:
                subtitles.append("EDITORIAL ARCHIVE EDITION")
            captions = (vars_list[0].get("captions") if vars_list else None) or [
                "THE JOURNEY BEGINS AT FIRST LIGHT",
                "GOLDEN HORIZONS IN SOFT FOCUS",
                "TOGETHER IN THE SOFT AFTERNOON",
                "MOMENTS TO TREASURE FOREVER",
            ]
            SessionStore.save_title_suggestions(session_id, {
                "titles": titles[:4],
                "subtitles": subtitles[:2],
                "category": data.get("primary_category", "Family"),
                "suggested_captions": captions[:4],
            })
        return data
    except Exception as e2:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.warning(f"[Metrics] All Gemini API attempts failed ({e2}) after {elapsed_ms:.2f}ms. Using offline fallback.")
        res = get_fallback_ai_response(
            user_prompt,
            custom_title=custom_title,
            include_text=include_text,
            subtitle=subtitle,
        )
        if session_id:
            SessionStore.save_title_suggestions(session_id, res)
        return res
