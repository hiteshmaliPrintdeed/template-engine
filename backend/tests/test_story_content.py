"""
Story content layer: validation, prompt-scoped caching, the real Gemini
timeout, per-chapter captions, reshuffle caption preservation, and the display
boundary.

Gemini is faked at _invoke_gemini_json -- the single transport function -- so
these tests exercise everything above the network: cache keys, validation,
fallback, and how content reaches the page. The timeout test goes one level
lower and drives the real SDK against a local server that stalls.
"""

import asyncio
import http.server
import threading
import time
import uuid

import pytest

import app.engine.story_ai as story_ai
from app.engine.solver import generate_photobook_variations_engine
from app.engine.story_content import (
    MAX_STORY_SEGMENTS,
    StoryContentInvalid,
    build_story_context,
    caption_fits,
    caption_width_pt,
    to_display,
    valid_caption,
    validate_book_content,
    validate_chapter_content,
)
from app.schemas.photobook import JobStatusResponse
from tests.fixtures.golden_story import _photo, photo_sets


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Distinct words for fake lines. Formulaic fakes ("line 1", "line 2") share
# almost every word, so the book-wide near-duplicate check (rightly) treats
# them as one line; real captions differ in wording, and so must the fakes.
WORDS = (
    "alpha bravo charlie delta echo foxtrot golf hotel india juliett kilo lima mike "
    "november oscar papa quebec romeo sierra tango uniform victor whiskey xray yankee zulu "
    "gamma kappa sigma omega theta zeta iota lambda epsilon upsilon omicron rho tau chi psi"
).split()

def book_response(tag="Wedding", **overrides):
    """A well-formed book response in sentence case, distinct per variation."""
    resp = {
        "category": "Celebration",
        "titles": [f"{tag} Day", f"Our {tag}", f"{tag} Story", f"The {tag} Album"],
        "subtitles": ["A day to remember", "Together forever"],
        "variations": [
            {
                "theme_name": theme,
                "cover_title": f"{tag} cover {n}",
                "cover_subtitle": f"Edition {n}",
                "captions": [f"{tag} moment {WORDS[(n - 1) * 6 + k - 1]}" for k in range(1, 7)],
            }
            for n, theme in ((1, "Warm"), (2, "Elegant"), (3, "Minimal"))
        ],
    }
    resp.update(overrides)
    return resp


def chapter_response(n_segments, tag="Part", lines=40):
    return {
        "segments": [
            {
                "segment_index": i,
                "title": f"{tag} {i + 1} begins",
                "captions": [f"{tag} {i + 1} {WORDS[k % len(WORDS)]}" for k in range(lines)],
            }
            for i in range(n_segments)
        ]
    }


class FakeGemini:
    """Stands in for _invoke_gemini_json; records every call by kind."""

    def __init__(self, book=None, chapters=None):
        self.book = book or (lambda prompt: book_response())
        self.chapters = chapters
        self.calls = []

    def __call__(self, prompt_text, timeout_sec, kind):
        self.calls.append(kind)
        if kind == "book":
            return self.book(prompt_text)
        if self.chapters is None:
            raise story_ai.GeminiCallFailed("error", "no chapter fake configured")
        return self.chapters(prompt_text)

    def count(self, kind=None):
        # Text requests are labelled "chapters [0.0,1.0]" (the parts they cover).
        return len(self.calls) if kind is None else sum(1 for k in self.calls if k.split(" ")[0] == kind)

    def kinds(self):
        return [k.split(" ")[0] for k in self.calls]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Every test starts offline, so a real key in backend/.env can never make
    this suite call Gemini. The gemini fixture opts a test back in, with a fake."""
    monkeypatch.setattr(story_ai, "ENABLE_GEMINI_API", False)
    monkeypatch.setattr(story_ai, "GEMINI_API_KEY", "")


@pytest.fixture
def gemini(monkeypatch):
    """Gemini 'enabled' with a fake transport. Tests configure responses."""
    fake = FakeGemini()
    monkeypatch.setattr(story_ai, "ENABLE_GEMINI_API", True)
    monkeypatch.setattr(story_ai, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(story_ai, "CHAPTER_CAPTIONS_ENABLED", True)
    monkeypatch.setattr(story_ai, "_invoke_gemini_json", fake)
    return fake


def new_sid():
    return f"sess_story_{uuid.uuid4().hex[:8]}"


def text_slots(variation):
    """Caption texts in reading order."""
    return [
        s.text_content
        for sp in variation.spreads
        for pg in (sp.left_page, sp.right_page)
        for s in pg.slots
        if s.type == "text"
    ]


def timed_groups(groups, per_group, gap_sec=10_800, prefix="g"):
    """Photos in `groups` bursts separated by gap_sec -- one story break each."""
    base = 1_785_500_000.0
    return [
        _photo(f"{prefix}{g}_{i}", base + g * gap_sec + i * 60, 90.0 - i, 1.5, 1)
        for g in range(groups)
        for i in range(per_group)
    ]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_valid_book_is_accepted_and_kept_raw():
    book = validate_book_content(book_response())
    assert book.category == "Celebration"
    assert [v.theme_name for v in book.variations] == ["Warm", "Elegant", "Minimal"]
    # Stored in the case Gemini wrote it; only to_display uppercases.
    assert book.variations[0].captions[0] == "Wedding moment alpha"


def test_book_trims_whitespace_and_quotes():
    resp = book_response()
    resp["variations"][0]["captions"][0] = '  "Two   hearts,  one day"  '
    book = validate_book_content(resp)
    assert book.variations[0].captions[0] == "Two hearts, one day"


@pytest.mark.parametrize("mutate, why", [
    (lambda r: r.update(category="Birthdays"), "unknown category"),
    (lambda r: r.update(variations=r["variations"][:2]), "too few variations"),
    (lambda r: r.update(titles=["Only one"]), "too few titles"),
    (lambda r: r["variations"][1].update(captions=["a", "b"]), "caption pool below minimum"),
    (lambda r: r.update(variations="nope"), "variations not a list"),
])
def test_structural_problems_reject(mutate, why):
    resp = book_response()
    mutate(resp)
    with pytest.raises(StoryContentInvalid):
        validate_book_content(resp)


def test_non_object_rejects():
    with pytest.raises(StoryContentInvalid):
        validate_book_content(["not", "an", "object"])


def test_unknown_theme_is_repaired_not_rejected():
    resp = book_response()
    resp["variations"][1]["theme_name"] = "Neon Cyberpunk"
    book = validate_book_content(resp)
    assert book.variations[1].theme_name in story_ai.THEME_PALETTES
    assert book.variations[1].theme_name != "Neon Cyberpunk"


def test_bad_cover_title_falls_back_to_book_title():
    resp = book_response()
    resp["variations"][2]["cover_title"] = "x" * 200
    book = validate_book_content(resp)
    assert book.variations[2].cover_title == book.titles[2]


@pytest.mark.parametrize("bad", [
    "Pure joy \U0001F389",            # emoji: not in the PDF font
    "शुभ विवाह",  # Hindi: renders as blank boxes
    "W" * 60,                          # wider than the caption box
    "   ",                             # empty after trimming
    "Zero​width",                 # invisible format character
])
def test_unprintable_or_oversized_captions_are_dropped(bad):
    resp = book_response()
    resp["variations"][0]["captions"] = [bad] + resp["variations"][0]["captions"]
    book = validate_book_content(resp)
    assert all(c.strip() for c in book.variations[0].captions)
    assert bad.strip() not in book.variations[0].captions
    assert len(book.variations[0].captions) == 6


def test_duplicates_dropped_case_insensitively():
    resp = book_response()
    caps = resp["variations"][0]["captions"]
    resp["variations"][0]["captions"] = [caps[0], caps[0].upper(), caps[0].lower()] + caps[1:]
    book = validate_book_content(resp)
    assert [c.upper() for c in book.variations[0].captions].count(caps[0].upper()) == 1


def test_oversized_pool_is_truncated():
    resp = book_response()
    resp["variations"][0]["captions"] = [f"Line number {i}" for i in range(20)]
    assert len(validate_book_content(resp).variations[0].captions) == 8


def test_width_is_measured_on_display_form():
    # Uppercasing can lengthen text: the German sharp s becomes 'SS'.
    assert caption_width_pt("ß") == caption_width_pt("SS")
    assert to_display("straße") == "STRASSE"


def test_width_not_char_count_decides_fit():
    # Same character count, very different printed width.
    assert caption_fits("I" * 50)
    assert not caption_fits("W" * 50)


def test_chapter_validation_isolates_bad_segments():
    resp = chapter_response(3)
    resp["segments"][1]["title"] = "\U0001F600"          # unprintable title
    content = validate_chapter_content(resp, "8,8,8", 3)
    assert content.segments[0] is not None
    assert content.segments[1] is None                     # only this one falls back
    assert content.segments[2] is not None


def test_chapter_validation_rejects_when_nothing_usable():
    with pytest.raises(StoryContentInvalid):
        validate_chapter_content({"segments": [{"segment_index": 0, "title": "", "captions": []}]}, "8", 1)


def test_chapter_title_is_not_reused_as_a_caption():
    resp = chapter_response(1)
    seg = resp["segments"][0]
    seg["captions"] = [seg["title"].upper()] + seg["captions"]
    content = validate_chapter_content(resp, "8", 1)
    assert content.segments[0].title.upper() not in [c.upper() for c in content.segments[0].captions]


# ---------------------------------------------------------------------------
# Prompt-scoped cache
# ---------------------------------------------------------------------------

def test_changing_prompt_in_session_gets_new_content(gemini):
    gemini.book = lambda p: book_response("Beach") if "Goa" in p else book_response("Wedding")
    sid = new_sid()
    wedding = story_ai.suggest_creative_titles("Wedding in Udaipur", 40, sid)
    beach = story_ai.suggest_creative_titles("Beach trip in Goa", 40, sid)
    assert gemini.count("book") == 2
    assert wedding["titles"] != beach["titles"]
    assert beach["titles"][0] == "BEACH DAY"


def test_prompt_variants_share_one_entry(gemini):
    sid = new_sid()
    story_ai.suggest_creative_titles("Wedding in Udaipur", 40, sid)
    story_ai.suggest_creative_titles("  wedding   IN udaipur ", 40, sid)
    assert gemini.count("book") == 1


def test_chat_and_generate_share_book_content(gemini):
    sid = new_sid()
    chat = story_ai.suggest_creative_titles("Wedding in Udaipur", 0, sid)
    # A different photo count must not miss the cache: the chat sends 0 before
    # upload finishes.
    batch = story_ai.generate_story_theme_batch("Wedding in Udaipur", 120, sid)
    assert gemini.count("book") == 1
    assert batch["variations"][0]["cover_title"] == "Wedding cover 1"
    assert chat["category"] == batch["primary_category"]


def test_call_budget_is_two_then_zero(gemini):
    photos = photo_sets()["multi"]
    ctx = build_story_context("Wedding in Udaipur", photos)
    assert len(ctx.segments) == 3
    gemini.chapters = lambda p: chapter_response(3)
    sid = new_sid()

    story_ai.suggest_creative_titles("Wedding in Udaipur", 16, sid)
    story_ai.generate_story_theme_batch("Wedding in Udaipur", 16, sid, story_context=ctx)
    assert gemini.kinds() == ["book", "chapters"]

    story_ai.suggest_creative_titles("Wedding in Udaipur", 16, sid)
    story_ai.generate_story_theme_batch("Wedding in Udaipur", 16, sid, story_context=ctx)
    assert gemini.count() == 2, "a repeat generation must be served from cache"


def test_all_three_variation_pools_survive_the_cache(gemini):
    sid = new_sid()
    first = story_ai.generate_story_theme_batch("Wedding in Udaipur", 16, sid)
    again = story_ai.generate_story_theme_batch("Wedding in Udaipur", 16, sid)
    assert gemini.count("book") == 1
    for batch in (first, again):
        pools = [tuple(v["captions"]) for v in batch["variations"]]
        assert len(set(pools)) == 3, "variations collapsed to one shared caption pool"
    assert first["variations"] == again["variations"]


def test_display_preferences_do_not_leak_through_cache(gemini):
    sid = new_sid()
    custom = story_ai.generate_story_theme_batch(
        "Wedding in Udaipur", 16, sid, custom_title="Nordic Light", subtitle="Winter 2026"
    )
    plain = story_ai.generate_story_theme_batch("Wedding in Udaipur", 16, sid)
    assert custom["variations"][0]["cover_title"] == "NORDIC LIGHT"
    assert plain["variations"][0]["cover_title"] == "Wedding cover 1"
    assert plain["variations"][0]["cover_subtitle"] == "Edition 1"


def test_invalid_response_falls_back_and_is_cached(gemini):
    gemini.book = lambda p: {"category": "Nonsense"}
    sid = new_sid()
    batch = story_ai.generate_story_theme_batch("Wedding in Udaipur", 16, sid)
    assert batch["variations"][0]["captions"][0] == "THE STORY UNFOLDS HERE"
    story_ai.generate_story_theme_batch("Wedding in Udaipur", 16, sid)
    assert gemini.count("book") == 1, "a failed attempt must not be retried every request"


def test_failed_chapter_call_is_remembered(gemini):
    photos = photo_sets()["multi"]
    ctx = build_story_context("Wedding", photos)
    sid = new_sid()                    # gemini.chapters is None -> every call fails
    story_ai.generate_story_theme_batch("Wedding", 16, sid, story_context=ctx)
    story_ai.generate_story_theme_batch("Wedding", 16, sid, story_context=ctx)
    assert gemini.count("chapters") == 1


def test_chapter_calls_follow_the_text_setting_not_the_segment_count(gemini):
    gemini.chapters = lambda p: chapter_response(3)
    sid = new_sid()
    multi_ctx = build_story_context("Wedding", photo_sets()["multi"])
    story_ai.generate_story_theme_batch("Wedding", 16, sid, include_text=False, story_context=multi_ctx)
    assert gemini.count("chapters") == 0, "a photo-only book needs no captions"
    # Photos without capture times: no known story structure, one segment. It
    # shows no title, but every spread still needs its own line.
    untimed = [_photo(f"u{i}", 0.0, 80.0, 1.5, 1) for i in range(30)]
    untimed_ctx = build_story_context("Wedding", untimed)
    assert len(untimed_ctx.segments) == 1
    story_ai.generate_story_theme_batch("Wedding", 30, sid, story_context=untimed_ctx)
    assert gemini.count("chapters") == 1


def test_chapter_switch_off(gemini, monkeypatch):
    monkeypatch.setattr(story_ai, "CHAPTER_CAPTIONS_ENABLED", False)
    gemini.chapters = lambda p: chapter_response(3)
    ctx = build_story_context("Wedding", photo_sets()["multi"])
    batch = story_ai.generate_story_theme_batch("Wedding", 16, new_sid(), story_context=ctx)
    assert "chapters" not in batch and gemini.count("chapters") == 0


# ---------------------------------------------------------------------------
# Story context and segments
# ---------------------------------------------------------------------------

def test_cap_splits_are_not_story_breaks():
    # 5 bursts of 30 photos: the 16-photo cap splits each burst in two, but only
    # the 4 time gaps are story breaks.
    ctx = build_story_context("Trip", photo_sets()["large"])
    assert len(ctx.chapters) == 10
    assert len(ctx.segments) == 5
    assert all(len(seg) == 2 for seg in ctx.segments)


def test_many_chapters_are_grouped_into_bounded_segments():
    ctx = build_story_context("Long trip", timed_groups(60, 2))
    assert len(ctx.chapters) == 60
    assert len(ctx.segments) == MAX_STORY_SEGMENTS
    flat = [c for seg in ctx.segments for c in seg]
    assert flat == list(range(60)), "segments must be contiguous and cover every chapter once"
    facts = ctx.segment_facts()
    requests = story_ai._line_requests(ctx, story_ai.TEXT_LINES_PER_REQUEST)
    assert all(r["people_lines"] + r["neutral_lines"] <= story_ai.TEXT_LINES_PER_REQUEST for r in requests)
    prompt = story_ai._chapter_prompt("Long trip", "Travel", facts, requests[:5])
    assert len(prompt) < 8000, "one request's prompt must stay bounded"


def test_segment_facts_are_relative_and_invent_nothing():
    facts = build_story_context("Wedding", photo_sets()["multi"]).segment_facts()
    assert facts[0]["hours_after_first_photo"] == 0.0
    assert facts[1]["break_before_hours"] > 2
    assert "time_of_day" not in facts[0] and "location" not in facts[0]


def test_gps_move_is_a_story_break():
    base = 1_785_500_000.0
    photos = []
    for i in range(10):
        p = _photo(f"gps{i}", base + i * 60, 90.0, 1.5, 1)   # no time gap at all
        p.latitude, p.longitude = (26.9, 75.8) if i < 5 else (24.6, 73.7)
        photos.append(p)
    ctx = build_story_context("Rajasthan", photos)
    assert len(ctx.segments) == 2
    assert ctx.segment_facts()[1]["new_location"] is True


# ---------------------------------------------------------------------------
# Solver: chapter captions on the page
# ---------------------------------------------------------------------------

def _layout_with_chapters(gemini, photos, prompt="Wedding", **kwargs):
    ctx = build_story_context(prompt, photos)
    gemini.chapters = lambda p: chapter_response(len(ctx.segments))
    batch = story_ai.generate_story_theme_batch(prompt, len(photos), new_sid(), story_context=ctx, **kwargs)
    return generate_photobook_variations_engine(
        photos, batch, include_text=kwargs.get("include_text", True), story_context=ctx
    ), ctx


def test_segment_titles_open_segments_and_captions_stay_inside(gemini):
    variations, ctx = _layout_with_chapters(gemini, photo_sets()["multi"])
    texts = text_slots(variations[0])
    assert texts[0] == "PART 1 BEGINS"
    assert "PART 2 BEGINS" in texts and "PART 3 BEGINS" in texts
    # Every caption belongs to the segment whose title precedes it.
    current = None
    for t in texts:
        if t.endswith("BEGINS"):
            current = t.split()[1]
        else:
            assert t.startswith(f"PART {current} "), f"{t!r} outside segment {current}"
    assert not any(t.startswith("CHAPTER ") for t in texts)


def test_variations_do_not_repeat_each_others_captions(gemini):
    variations, _ = _layout_with_chapters(gemini, photo_sets()["large"])
    first_caption = [text_slots(v)[1] for v in variations]
    assert len(set(first_caption)) == 3


def test_chapter_content_for_other_photos_is_ignored(gemini):
    photos_a = photo_sets()["multi"]
    ctx_a = build_story_context("Wedding", photos_a)
    gemini.chapters = lambda p: chapter_response(len(ctx_a.segments))
    batch = story_ai.generate_story_theme_batch("Wedding", 16, new_sid(), story_context=ctx_a)
    assert "chapters" in batch

    photos_b = timed_groups(4, 5, prefix="b")          # a different photo set
    variations = generate_photobook_variations_engine(photos_b, batch)
    texts = text_slots(variations[0])
    assert not any("PART" in t for t in texts), "stale chapter text applied to other photos"


def test_include_text_false_prints_nothing_even_with_chapters(gemini):
    photos = photo_sets()["multi"]
    ctx = build_story_context("Wedding", photos)
    gemini.chapters = lambda p: chapter_response(len(ctx.segments))
    batch = story_ai.generate_story_theme_batch("Wedding", 16, new_sid(), story_context=ctx)
    variations = generate_photobook_variations_engine(photos, batch, include_text=False, story_context=ctx)
    assert all(text_slots(v) == [] for v in variations)


def test_invalid_segment_lays_out_like_before(gemini):
    photos = photo_sets()["multi"]
    ctx = build_story_context("Wedding", photos)

    def partly_bad(_p):
        resp = chapter_response(3)
        resp["segments"][1]["captions"] = []          # segment 2 unusable
        return resp

    gemini.chapters = partly_bad
    batch = story_ai.generate_story_theme_batch("Wedding", 16, new_sid(), story_context=ctx)
    texts = text_slots(generate_photobook_variations_engine(photos, batch, story_context=ctx)[0])
    assert "PART 1 BEGINS" in texts and "PART 3 BEGINS" in texts
    assert "CHAPTER 2: STORY SEQUENCE" in texts, "the failed segment should keep its generic label"


def test_generated_text_is_displayed_uppercase(gemini):
    batch = story_ai.generate_story_theme_batch("Wedding", 8, new_sid())
    v = generate_photobook_variations_engine(photo_sets()["single"], batch)[0]
    assert v.cover_title == "WEDDING COVER 1"
    assert v.cover_subtitle == "EDITION 1"
    assert text_slots(v)[0] == "WEDDING MOMENT ALPHA"


def test_user_subtitle_keeps_its_case(gemini):
    batch = story_ai.generate_story_theme_batch("Wedding", 8, new_sid(), subtitle="Summer 2026")
    v = generate_photobook_variations_engine(photo_sets()["single"], batch, subtitle="Summer 2026")[0]
    assert v.cover_subtitle == "Summer 2026"


# ---------------------------------------------------------------------------
# Reshuffle keeps the book's captions
# ---------------------------------------------------------------------------

def _run_job(store, photos, prompt, sid, save_prompt=True):
    from app.main import process_async_job

    job_id = f"job_{uuid.uuid4().hex[:8]}"
    store.create_session(sid, expected_photo_count=len(photos))
    store.save_photos_batch(photos, session_id=sid)
    store.save_job(
        JobStatusResponse(job_id=job_id, status="processing", progress=10, message="Queued", result=None),
        session_id=sid,
        include_text=True,
        user_prompt=prompt if save_prompt else None,
    )
    asyncio.run(process_async_job(
        job_id=job_id, photo_ids=[p.id for p in photos], user_prompt=prompt, session_id=sid,
    ))
    return job_id, store.get_job(job_id)


def test_job_prompt_survives_progress_updates(store):
    photos = timed_groups(2, 3, prefix=f"jp{uuid.uuid4().hex[:4]}_")
    job_id, job = _run_job(store, photos, "Prompt kept", new_sid())
    assert job.status == "completed"
    assert store.get_job_prompt(job_id) == "Prompt kept"


@pytest.mark.parametrize("chapters_on", [True, False], ids=["chapter-captions", "book-captions"])
def test_variation_reshuffle_keeps_generated_captions(gemini, client, store, monkeypatch, chapters_on):
    # Both paths: with chapter content every caption comes from segment pools,
    # so the book-level pools are only exercised with chapters off.
    monkeypatch.setattr(story_ai, "CHAPTER_CAPTIONS_ENABLED", chapters_on)
    photos = timed_groups(3, 5, prefix=f"rs{uuid.uuid4().hex[:4]}_")
    gemini.chapters = lambda p: chapter_response(3)
    sid = new_sid()
    job_id, job = _run_job(store, photos, "Wedding in Udaipur", sid)
    before = [set(text_slots(v)) for v in job.result.variations]
    if chapters_on:
        assert any("PART 1 BEGINS" in b for b in before)
    else:
        assert any("Wedding moment".upper() in t for b in before for t in b)

    res = client.post("/api/variations/reshuffle", json={"job_id": job_id, "seed_offset": 2, "session_id": sid})
    assert res.status_code == 200
    for v_before, v_after in zip(before, res.json()["variations"]):
        after = {
            s["text_content"]
            for sp in v_after["spreads"]
            for pg in ("left_page", "right_page")
            for s in sp[pg]["slots"]
            if s["type"] == "text"
        }
        assert after <= v_before, f"reshuffle introduced captions the book never had: {after - v_before}"
    assert gemini.count() == (2 if chapters_on else 1), "reshuffle must not call Gemini"


def test_reshuffle_recovers_captions_for_jobs_without_a_prompt(client, store):
    # 15 photos: enough spreads to reach the 4th caption, where the solver's
    # hardcoded defaults ('GENTLE SPIRITS...') first differ from the fallback
    # captions. With fewer, the old buggy rebuild would pass this test too.
    photos = timed_groups(1, 15, prefix=f"old{uuid.uuid4().hex[:4]}_")
    sid = new_sid()
    job_id, job = _run_job(store, photos, "Old job", sid, save_prompt=False)
    before = set(text_slots(job.result.variations[0]))

    res = client.post("/api/variations/reshuffle", json={"job_id": job_id, "seed_offset": 1, "session_id": sid})
    after = {
        s["text_content"]
        for sp in res.json()["variations"][0]["spreads"]
        for pg in ("left_page", "right_page")
        for s in sp[pg]["slots"]
        if s["type"] == "text"
    }
    # The solver's hardcoded defaults include lines the fallback never uses.
    assert "GENTLE SPIRITS IN STILLNESS" not in after
    assert after <= before


# ---------------------------------------------------------------------------
# Real timeout: the SDK against a server that never answers in time
# ---------------------------------------------------------------------------

class _StallHandler(http.server.BaseHTTPRequestHandler):
    seen_deadlines = []

    def do_POST(self):
        _StallHandler.seen_deadlines.append(self.headers.get("X-Server-Timeout"))
        time.sleep(5)
        try:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")
        except OSError:
            pass

    def log_message(self, *args):
        pass


def test_timeout_actually_bounds_the_call(monkeypatch):
    """
    The regression this guards is 'correct result, wrong duration': the old
    wrapper noticed the timeout and then waited for the slow call anyway. So
    the assertion is on elapsed time, against a real HTTP stall.
    """
    from google import genai
    from google.genai import types

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _StallHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client = genai.Client(
            api_key="test-key",
            http_options=types.HttpOptions(
                base_url=f"http://127.0.0.1:{server.server_address[1]}",
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        monkeypatch.setattr(story_ai, "_client", client)
        start = time.perf_counter()
        with pytest.raises(story_ai.GeminiCallFailed) as exc:
            story_ai._invoke_gemini_json("hello", 0.3, "book")
        elapsed = time.perf_counter() - start
    finally:
        server.shutdown()
    assert exc.value.reason == "timeout"
    assert elapsed < 2.0, f"timeout of 0.3s took {elapsed:.2f}s"
    # A short local timeout must not become a short SERVER deadline: the Gemini
    # API rejects deadlines under 10s with 400, which failed every real call.
    assert _StallHandler.seen_deadlines, "request never reached the server"
    assert int(_StallHandler.seen_deadlines[-1]) >= 10


# ---------------------------------------------------------------------------
# The caption limit matches what the PDF renderer actually draws
# ---------------------------------------------------------------------------

def test_longest_valid_caption_fits_its_printed_box(monkeypatch, tmp_path):
    """
    Renders a real PDF through pdf_exporter and records every string it draws,
    so the check is against the renderer's own geometry and font -- not a copy
    of its formula that could drift.
    """
    import app.engine.pdf_exporter as pdf_exporter
    from reportlab.pdfbase.pdfmetrics import stringWidth

    longest = "W"
    while valid_caption(longest + "W"):
        longest += "W"
    assert valid_caption(longest) and not valid_caption(longest + "W")

    drawn = []
    real_canvas = pdf_exporter.rl_canvas.Canvas

    class RecordingCanvas(real_canvas):
        def drawCentredString(self, x, y, text, *args, **kwargs):
            drawn.append((x, text, self._fontname, self._fontsize))
            return super().drawCentredString(x, y, text, *args, **kwargs)

    monkeypatch.setattr(pdf_exporter.rl_canvas, "Canvas", RecordingCanvas)
    monkeypatch.setattr(pdf_exporter, "SCRATCH_DIR", str(tmp_path))

    photos = photo_sets()["single"]
    batch = story_ai.book_to_batch(story_ai._fallback_book("Wedding"))
    for v in batch["variations"]:
        v["captions"] = [longest]
    variation = generate_photobook_variations_engine(photos, batch)[0]
    # The exporter refuses to print a book whose photo files are missing (it
    # fails honestly rather than ship blanks), and these fixtures have none.
    # Only the text is under test, so export the solver's real spreads with the
    # photo slots removed; the caption slot keeps the geometry the solver gave it.
    for sp in variation.spreads:
        sp.left_page.slots = [s for s in sp.left_page.slots if s.type == "text"]
        sp.right_page.slots = [s for s in sp.right_page.slots if s.type == "text"]
    pdf_exporter.generate_print_pdf_engine(variation, page_width_mm=200, page_height_mm=200, bleed_mm=3.0)

    mm = pdf_exporter.MM_TO_PT
    single_w, bleed = 200 * mm, 3.0 * mm
    slot = next(s for sp in variation.spreads for s in sp.left_page.slots if s.type == "text")
    box_left = bleed + slot.x_pct * single_w * 2
    box_right = box_left + slot.w_pct * single_w * 2

    captions = [d for d in drawn if d[1] == longest]
    assert captions, "the caption was never drawn"
    for x, text, font, size in captions:
        half = stringWidth(text, font, size) / 2
        assert box_left <= x - half and x + half <= box_right, (
            f"caption spans {x - half:.1f}-{x + half:.1f}pt, box is {box_left:.1f}-{box_right:.1f}pt"
        )
