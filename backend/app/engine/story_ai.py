"""
Gemini AI Story & Theme Engine for Pixovo Template Engine (PTE)
1. Categorizes user prompt into 1 of 10 Combined Categories.
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
     {"chapter_id": 1, "photos_count": 75, "time_range": "09:00 - 11:30", "location_anchor": "Temple"},
     {"chapter_id": 2, "photos_count": 120, "time_range": "12:00 - 14:30", "location_anchor": "Reception"}
   ]
3. Tier 3 (Layout Engine Allocation):
   The DSA Solver allocates spread templates per chapter without requiring individual photo AI calls.
========================================================================================
"""

import time
import json
from typing import Dict, Any, List
from app.config import GEMINI_API_KEY, logger
from app.engine.color_extractor import CATEGORY_THEMES_MAP, THEME_PALETTES, CATEGORY_TYPOGRAPHY_MAP

ALLOWED_CATEGORIES = list(CATEGORY_THEMES_MAP.keys())

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

    # Sort photos chronologically if timestamp exists
    sorted_photos = sorted(
        photos,
        key=lambda p: (
            getattr(p, "timestamp_epoch", 0) if hasattr(p, "timestamp_epoch")
            else (p.get("timestamp_epoch", 0) if isinstance(p, dict) else 0)
        )
    )

    total_count = len(sorted_photos)
    # Dynamic chapter threshold: For <=50 photos: 12/ch; for 50-200: 16/ch; for 200+: 24/ch
    if total_count > 200:
        max_per_chapter = 24
    elif total_count > 50:
        max_per_chapter = 16
    else:
        max_per_chapter = 12

    chapters: List[Dict[str, Any]] = []
    current_chapter_photos = [sorted_photos[0]]
    ch_idx = 1
    # Stage 1.2 diagnostics: which rule actually drove each split. Before
    # timestamp_epoch existed on PhotoMeta, every photo read 0, so time and GPS
    # rules could never fire and chapters were purely `cap` splits — fixed-size
    # chunks of upload order wearing the name "story chapters".
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

        # Trigger new chapter if time gap > 45m OR GPS distance > 5km OR max photos per chapter reached
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

def get_fallback_ai_response(user_prompt: str) -> Dict[str, Any]:
    """Generates structured fallback themes and captions offline."""
    prompt_lower = user_prompt.lower()
    
    if "temple" in prompt_lower or "iskcon" in prompt_lower or "devotion" in prompt_lower or "prayer" in prompt_lower:
        primary_category = "Memories"
    elif "wedding" in prompt_lower or "marriage" in prompt_lower or "party" in prompt_lower or "birthday" in prompt_lower:
        primary_category = "Celebration"
    elif "travel" in prompt_lower or "trip" in prompt_lower or "vacation" in prompt_lower or "beach" in prompt_lower:
        primary_category = "Travel"
    elif "portrait" in prompt_lower or "selfie" in prompt_lower:
        primary_category = "Portraits"
    elif "gradu" in prompt_lower or "office" in prompt_lower or "college" in prompt_lower:
        primary_category = "Milestones"
    else:
        primary_category = "Family"

    candidate_themes = CATEGORY_THEMES_MAP.get(primary_category, ["Warm", "Classic", "Nostalgic"])
    
    theme1 = candidate_themes[0]
    theme2 = candidate_themes[1] if len(candidate_themes) > 1 else "Minimal"
    theme3 = candidate_themes[2] if len(candidate_themes) > 2 else "Editorial"

    upper_title = user_prompt.upper() if user_prompt else "CHERISHED MOMENTS"
    typo_info = CATEGORY_TYPOGRAPHY_MAP.get(primary_category, CATEGORY_TYPOGRAPHY_MAP["Family"])
    logger.info(f"[StoryAI Fallback] User occasion: '{user_prompt}' -> Category: '{primary_category}' -> Typo: {typo_info['heading_font']}/{typo_info['body_font']}")

    return {
        "primary_category": primary_category,
        "primary_theme": theme1,
        "typography": typo_info,
        "variations": [
            {
                "variation_id": "var_1",
                "variation_title": f"{theme1} Storybook",
                "theme_name": theme1,
                "heading_font": typo_info["heading_font"],
                "body_font": typo_info["body_font"],
                "cover_title": upper_title,
                "cover_subtitle": "2025 • MEMORIES COLLECTION",
                "captions": [
                    "THE JOURNEY BEGINS AT FIRST LIGHT",
                    "BLUE SKIES OVER SACRED SPIRES",
                    "TOGETHER IN THE SOFT AFTERNOON",
                    "MOMENTS TO TREASURE FOREVER"
                ]
            },
            {
                "variation_id": "var_2",
                "variation_title": f"{theme2} Minimalist",
                "theme_name": theme2,
                "heading_font": typo_info["heading_font"],
                "body_font": typo_info["body_font"],
                "cover_title": f"CHRONICLES OF {upper_title}",
                "cover_subtitle": "A PICTORIAL JOURNEY",
                "captions": [
                    "FIRST LIGHT REFLECTIONS",
                    "ARCHITECTURAL MAJESTY",
                    "SHARED LAUGHTER & BLISS",
                    "UNFORGETTABLE FOOTPRINTS"
                ]
            },
            {
                "variation_id": "var_3",
                "variation_title": f"{theme3} Chronicle",
                "theme_name": theme3,
                "heading_font": typo_info["heading_font"],
                "body_font": typo_info["body_font"],
                "cover_title": "DAYTIME UNFOLDED",
                "cover_subtitle": "PIXOVO SPECIAL MEMORIES",
                "captions": [
                    "STEPPING INTO PEACE",
                    "FAITH, FELLOWSHIP & SMILES",
                    "GOLDEN HOUR TOGETHERNESS",
                    "MEMORIES WRITTEN IN SUNLIGHT"
                ]
            }
        ]
    }

ENABLE_GEMINI_API = False  # Set to False to use ultra-fast local intelligent Story & Theme engine

def generate_story_theme_batch(user_prompt: str, total_photos: int = 10) -> Dict[str, Any]:
    """Calls Gemini API or uses fast intelligent local NLP theme & caption engine."""
    start_time = time.perf_counter()

    if not ENABLE_GEMINI_API or not GEMINI_API_KEY:
        logger.info(f"[StoryAI] Local theme engine active (Gemini API disabled). Generating layout styles for: '{user_prompt}'")
        res = get_fallback_ai_response(user_prompt)
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.info(f"[StoryAI] Local Story & Theme batch generated in {elapsed_ms:.2f}ms | Category: '{res.get('primary_category')}' | Primary Theme: '{res.get('primary_theme')}'")
        return res

    try:
        from google import genai
        from google.genai import types

        logger.info(f"[StoryAI] Calling Gemini API (google-genai) for occasion prompt: '{user_prompt}'")
        client = genai.Client(api_key=GEMINI_API_KEY)
        
        prompt_text = f"""
        User Occasion / Emotion: "{user_prompt}" (Total photos: {total_photos}).
        
        Task:
        1. Categorize this occasion into EXACTLY ONE of these 10 Top Categories:
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
                    "cover_subtitle": "<Subtitle e.g. 2025 EDITION>",
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

        response = client.models.generate_content(
            model='gemini-3.5-flash-lite',
            contents=prompt_text,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.4
            )
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        data = json.loads(response.text)
        logger.info(f"[Metrics] Gemini API call succeeded in {elapsed_ms:.2f}ms | Category: '{data.get('primary_category')}' | Primary Theme: '{data.get('primary_theme')}'")
        return data
    except Exception as e1:
        logger.warning(f"[StoryAI] google-genai call failed: {e1}. Trying legacy google-generativeai SDK...")

    try:
        import google.generativeai as genai_legacy
        genai_legacy.configure(api_key=GEMINI_API_KEY)
        model = genai_legacy.GenerativeModel('gemini-3.5-flash-lite')
        
        prompt_text = f"""
        User Occasion: "{user_prompt}".
        Categorize into one of {json.dumps(ALLOWED_CATEGORIES)} and pick themes from {json.dumps(CATEGORY_THEMES_MAP)}. Return valid JSON with primary_category, primary_theme, and 3 variations (var_1, var_2, var_3) having cover_title, cover_subtitle, theme_name, and captions array.
        """
        response = model.generate_content(
            prompt_text,
            generation_config={"response_mime_type": "application/json"}
        )
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        data = json.loads(response.text)
        logger.info(f"[Metrics] Legacy Gemini API call succeeded in {elapsed_ms:.2f}ms | Category: '{data.get('primary_category')}'")
        return data
    except Exception as e2:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.warning(f"[Metrics] All Gemini API attempts failed ({e2}) after {elapsed_ms:.2f}ms. Using offline fallback.")
        return get_fallback_ai_response(user_prompt)
