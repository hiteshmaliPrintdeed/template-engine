"""
Stage 3.2 / 3.3 regression tests — Guided Story Studio contract, caption gating,
session-cached title suggestions, and reshuffle preference persistence.
"""

import asyncio
import time
import uuid
import pytest

from app.schemas.photobook import PhotoMeta, JobStatusResponse
from app.engine.story_ai import partition_macro_chapters, generate_story_theme_batch
from app.engine.solver import generate_photobook_variations_engine


def _make_photo(pid: str, ts_epoch: float, hero: float = 80.0, ar: float = 1.5) -> PhotoMeta:
    return PhotoMeta(
        id=pid,
        filename=f"{pid}.jpg",
        url=f"/uploads/thumbnails/sess_studio/{pid}_thumb.jpg",
        thumbnail_url=f"/uploads/thumbnails/sess_studio/{pid}_thumb.jpg",
        preview_url=f"/uploads/thumbnails/sess_studio/{pid}_thumb.jpg",
        original_url=None,
        original_synced=False,
        width=4000,
        height=int(4000 / ar),
        aspect_ratio=ar,
        hero_score=hero,
        face_count=1,
        shell_phash=f"{abs(hash(pid)) % (16**16):016x}",
        core_phash=f"{abs(hash(pid + 'c')) % (16**16):016x}",
        dominant_colors=["#1E293B", "#64748B", "#F8FAFC"],
        timestamp_epoch=ts_epoch,
    )


@pytest.fixture
def multi_chapter_photos():
    """
    16 photos separated by two 3-hour time gaps (> 2700s threshold) so
    partition_macro_chapters() produces 3 distinct chapters and the
    `c_i == 0 and ch_title and len(macro_chapters) > 1` branch in solver.py
    is guaranteed reachable.
    """
    base_ts = 1_785_500_000.0
    photos = []
    for i in range(6):
        photos.append(_make_photo(f"ch1_p{i}", base_ts + i * 120, hero=92.0 - i))
    for i in range(5):
        photos.append(_make_photo(f"ch2_p{i}", base_ts + 10_800 + i * 120, hero=85.0 - i))
    for i in range(5):
        photos.append(_make_photo(f"ch3_p{i}", base_ts + 21_600 + i * 120, hero=78.0 - i))
    return photos


def test_suggest_titles_without_key(client, monkeypatch):
    """
    With GEMINI_API_KEY unset, /api/chat/suggest-titles returns the fallback
    response shape in < 50ms wall time.
    """
    import app.engine.story_ai as story_ai

    monkeypatch.setattr(story_ai, "ENABLE_GEMINI_API", False)
    monkeypatch.setattr(story_ai, "GEMINI_API_KEY", "")

    t0 = time.perf_counter()
    res = client.post(
        "/api/chat/suggest-titles",
        json={"user_prompt": "Summer road trip along the coast", "photo_count": 24},
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert res.status_code == 200
    assert elapsed_ms < 50.0, f"Fallback took {elapsed_ms:.2f}ms (expected < 50ms)"

    data = res.json()
    assert isinstance(data["titles"], list) and len(data["titles"]) == 4
    assert isinstance(data["subtitles"], list) and len(data["subtitles"]) == 2
    assert data["category"] == "Travel"
    assert isinstance(data["suggested_captions"], list) and len(data["suggested_captions"]) == 4


def test_suggest_titles_caches_by_session(client, monkeypatch):
    """
    Two suggest-titles calls with the same session_id — followed by
    generate_story_theme_batch for that same session_id — must invoke the
    underlying AI/fallback generator exactly once.
    """
    import app.engine.story_ai as story_ai

    monkeypatch.setattr(story_ai, "ENABLE_GEMINI_API", False)
    monkeypatch.setattr(story_ai, "GEMINI_API_KEY", "")

    call_count = {"n": 0}
    real_fallback = story_ai.get_fallback_ai_response

    def counted_fallback(*args, **kwargs):
        call_count["n"] += 1
        return real_fallback(*args, **kwargs)

    monkeypatch.setattr(story_ai, "get_fallback_ai_response", counted_fallback)

    sid = f"sess_cache_{uuid.uuid4().hex[:8]}"

    r1 = client.post(
        "/api/chat/suggest-titles",
        json={"user_prompt": "Wedding celebration in Udaipur", "photo_count": 40, "session_id": sid},
    )
    r2 = client.post(
        "/api/chat/suggest-titles",
        json={"user_prompt": "Wedding celebration in Udaipur", "photo_count": 40, "session_id": sid},
    )
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json() == r2.json()
    assert call_count["n"] == 1, f"Expected 1 generator call after 2 suggest-titles requests, got {call_count['n']}"

    # Now run generate_story_theme_batch with the same session_id: must reuse the cached suggestion
    batch = generate_story_theme_batch("Wedding celebration in Udaipur", total_photos=40, session_id=sid)
    assert batch["primary_category"] == "Celebration"
    assert call_count["n"] == 1, "generate_story_theme_batch issued a second AI/fallback call instead of reusing cache"


def test_include_text_false_yields_zero_text_slots(multi_chapter_photos):
    """
    Direct regression test for the chapter-title caption branch in solver.py:
    with include_text=False and a multi-chapter photo set (len(macro_chapters) > 1),
    EVERY spread across EVERY variation must have zero text slots.
    """
    chapters = partition_macro_chapters(multi_chapter_photos)
    assert len(chapters) > 1, "Fixture must produce multiple chapters to reach the ch_title branch"

    ai_batch = generate_story_theme_batch(
        "Family holiday in the mountains",
        total_photos=len(multi_chapter_photos),
        include_text=False,
    )
    variations = generate_photobook_variations_engine(
        multi_chapter_photos,
        ai_batch,
        include_text=False,
    )
    assert len(variations) == 3

    for v in variations:
        assert len(v.spreads) > 0
        for spread in v.spreads:
            for page in (spread.left_page, spread.right_page):
                text_slots = [s for s in page.slots if s.type == "text"]
                assert text_slots == [], (
                    f"Variation {v.id} spread #{spread.spread_index} page {page.page_number} "
                    f"contains unexpected text slots when include_text=False: {text_slots}"
                )


def test_custom_title_applied_to_all_variations(multi_chapter_photos):
    """
    A custom_title and subtitle must be applied uniformly across all 3 variations,
    not only the primary variation.
    """
    ai_batch = generate_story_theme_batch(
        "Summer road trip",
        total_photos=len(multi_chapter_photos),
        custom_title="The Pacific Coast",
        subtitle="Summer 2026 • Archive",
    )
    variations = generate_photobook_variations_engine(
        multi_chapter_photos,
        ai_batch,
        custom_title="The Pacific Coast",
        subtitle="Summer 2026 • Archive",
    )
    assert len(variations) == 3
    for v in variations:
        assert v.cover_title == "THE PACIFIC COAST"
        assert v.cover_subtitle == "Summer 2026 • Archive"


def test_reshuffle_preserves_include_text(client, store, multi_chapter_photos):
    """
    Generating with include_text=False and custom_title='Nordic Light', then calling
    both /api/variations/reshuffle and /api/spreads/reshuffle with ONLY session_id
    (no include_text or custom_title in the reshuffle body), must keep all spreads
    100% caption-free and preserve the custom cover title.
    """
    from app.main import process_async_job

    sid = f"sess_reshuf_{uuid.uuid4().hex[:8]}"
    job_id = f"job_{uuid.uuid4().hex[:8]}"
    store.create_session(sid, expected_photo_count=len(multi_chapter_photos))
    store.save_photos_batch(multi_chapter_photos, session_id=sid)

    initial_job = JobStatusResponse(
        job_id=job_id,
        status="processing",
        progress=10,
        message="Queued",
        result=None,
    )
    store.save_job(
        initial_job,
        session_id=sid,
        custom_title="Nordic Light",
        include_text=False,
        subtitle="Winter Collection",
    )

    asyncio.run(
        process_async_job(
            job_id=job_id,
            photo_ids=[p.id for p in multi_chapter_photos],
            user_prompt="Winter journey",
            session_id=sid,
            custom_title="Nordic Light",
            include_text=False,
            subtitle="Winter Collection",
        )
    )

    # 1. Variation-level reshuffle (no include_text or custom_title in request body)
    res_vars = client.post(
        "/api/variations/reshuffle",
        json={"job_id": job_id, "seed_offset": 2, "session_id": sid},
    )
    assert res_vars.status_code == 200
    reshuffled_vars = res_vars.json()["variations"]
    assert len(reshuffled_vars) == 3

    for v in reshuffled_vars:
        assert v["cover_title"] == "NORDIC LIGHT"
        assert v["cover_subtitle"] == "Winter Collection"
        for spread in v["spreads"]:
            for page in (spread["left_page"], spread["right_page"]):
                text_slots = [s for s in page["slots"] if s["type"] == "text"]
                assert text_slots == [], f"Reshuffled variation leaked text slot: {text_slots}"

    # 2. Single-spread reshuffle (no include_text in request body)
    first_spread = reshuffled_vars[0]["spreads"][0]
    res_spread = client.post(
        "/api/spreads/reshuffle",
        json={
            "spread": first_spread,
            "theme_name": reshuffled_vars[0]["theme_name"],
            "seed": 3,
            "session_id": sid,
        },
    )
    assert res_spread.status_code == 200
    new_spread = res_spread.json()
    for page in (new_spread["left_page"], new_spread["right_page"]):
        text_slots = [s for s in page["slots"] if s["type"] == "text"]
        assert text_slots == [], f"Single-spread reshuffle fabricated a text slot: {text_slots}"
