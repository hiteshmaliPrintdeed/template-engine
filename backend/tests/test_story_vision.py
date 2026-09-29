"""
Vision captions: Gemini is shown ~3 representative thumbnails per story segment,
only for books that opted in.

The transport is faked at _invoke_gemini_json and thumbnails at
representative_image_bytes, so these tests cover everything above the network:
the opt-in, per-segment requests, validation, isolation, the time budget, the
cache and reshuffle.
"""

import asyncio
import threading
import time
import uuid

import pytest

import app.engine.representatives as reps
import app.engine.story_ai as story_ai
from app.engine.solver import generate_photobook_variations_engine
from app.engine.story_content import StoryContentInvalid, build_story_context, validate_vision_segment
from app.schemas.photobook import JobStatusResponse
from tests.fixtures.golden_story import _photo


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

def book_response():
    return {
        "category": "Celebration",
        "titles": ["Our Day", "Together", "The Album", "Memories"],
        "subtitles": ["A day to remember", "Together forever"],
        "variations": [
            {"theme_name": t, "cover_title": f"Cover {n}", "cover_subtitle": f"Edition {n}",
             "captions": [f"Book line {n} number {k}" for k in range(1, 7)]}
            for n, t in ((1, "Warm"), (2, "Elegant"), (3, "Minimal"))
        ],
    }


def text_chapters(n):
    return {"segments": [
        {"segment_index": i, "title": f"Text part {i + 1}",
         "captions": [f"Text line {i + 1} number {k}" for k in range(1, 5)]}
        for i in range(n)
    ]}


def vision_segment(i):
    return {"title": f"Seen part {i + 1}",
            "captions": [f"Seen line {i + 1} number {k}" for k in range(1, 7)]}


class FakeGemini:
    def __init__(self):
        self.calls = []            # (kind, image count)
        self.lock = threading.Lock()
        self.fail_segments = set()
        self.vision_delay = 0.0
        self.n_segments = 3

    def __call__(self, prompt_text, timeout_sec, kind, images=None):
        with self.lock:
            self.calls.append((kind, len(images or [])))
        if kind == "book":
            return book_response()
        if kind == "chapters":
            return text_chapters(self.n_segments)
        assert kind.startswith("vision segment=")
        idx = int(kind.split("=")[1])
        if self.vision_delay:
            time.sleep(self.vision_delay)
        if idx in self.fail_segments:
            raise story_ai.GeminiCallFailed("http_error", "fake failure")
        return vision_segment(idx)

    def kinds(self, prefix):
        return [k for k, _ in self.calls if k.startswith(prefix)]

    def images_sent(self):
        return sum(n for _, n in self.calls)


@pytest.fixture
def gemini(monkeypatch):
    fake = FakeGemini()
    monkeypatch.setattr(story_ai, "ENABLE_GEMINI_API", True)
    monkeypatch.setattr(story_ai, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(story_ai, "CHAPTER_CAPTIONS_ENABLED", True)
    monkeypatch.setattr(story_ai, "CAPTION_STRATEGY", "vision")
    monkeypatch.setattr(story_ai, "_invoke_gemini_json", fake)
    # Thumbnails: every photo with a thumbnail_key reads as a small JPEG.
    monkeypatch.setattr(reps, "representative_image_bytes", lambda p: b"jpeg:" + p.id.encode())
    return fake


def sid():
    return f"sess_vis_{uuid.uuid4().hex[:8]}"


def book_photos(groups=3, per_group=5, prefix=None):
    """Bursts separated by 3h gaps -> one story segment per burst."""
    prefix = prefix or f"v{uuid.uuid4().hex[:5]}_"
    base = 1_785_500_000.0
    photos = []
    for g in range(groups):
        for i in range(per_group):
            p = _photo(f"{prefix}{g}_{i}", base + g * 10_800 + i * 60, 90.0 - i, 1.5, 1)
            p.thumbnail_key = f"thumbnails/sess/{p.id}_thumb.jpg"
            photos.append(p)
    return photos


def generate(photos, session, vision=True, **kw):
    ctx = build_story_context("Family wedding", photos)
    batch = story_ai.generate_story_theme_batch(
        "Family wedding", len(photos), session, story_context=ctx, use_photo_vision=vision, **kw
    )
    return batch, ctx


def seg_titles(batch):
    return [s["title"] if s else None for s in batch["chapters"]["segments"]]


# ---------------------------------------------------------------------------
# Opt-in: the privacy guarantee
# ---------------------------------------------------------------------------

def test_no_images_leave_without_opt_in(gemini):
    batch, _ = generate(book_photos(), sid(), vision=False)
    assert gemini.images_sent() == 0
    assert gemini.kinds("vision") == []
    assert seg_titles(batch)[0] == "Text part 1"


def test_server_strategy_chapter_overrides_opt_in(gemini, monkeypatch):
    monkeypatch.setattr(story_ai, "CAPTION_STRATEGY", "chapter")
    generate(book_photos(), sid(), vision=True)
    assert gemini.images_sent() == 0


def test_no_images_for_photo_only_books(gemini):
    generate(book_photos(), sid(), vision=True, include_text=False)
    assert gemini.images_sent() == 0


# ---------------------------------------------------------------------------
# The vision pass
# ---------------------------------------------------------------------------

def test_one_vision_call_per_segment_with_up_to_three_images(gemini):
    batch, ctx = generate(book_photos(), sid())
    vision = [(k, n) for k, n in gemini.calls if k.startswith("vision")]
    assert sorted(k for k, _ in vision) == [f"vision segment={i}" for i in range(len(ctx.segments))]
    assert all(1 <= n <= 3 for _, n in vision)
    assert gemini.kinds("chapters") == [], "text call should only run to fill gaps"
    assert seg_titles(batch) == ["Seen part 1", "Seen part 2", "Seen part 3"]


def test_vision_captions_reach_the_page(gemini):
    photos = book_photos()
    batch, ctx = generate(photos, sid())
    texts = [
        s.text_content
        for sp in generate_photobook_variations_engine(photos, batch, story_context=ctx)[0].spreads
        for pg in (sp.left_page, sp.right_page) for s in pg.slots if s.type == "text"
    ]
    assert texts[0] == "SEEN PART 1"
    assert any(t.startswith("SEEN LINE 2") for t in texts)


def test_failed_segment_is_filled_from_text_only(gemini):
    gemini.fail_segments = {1}
    batch, _ = generate(book_photos(), sid())
    assert seg_titles(batch) == ["Seen part 1", "Text part 2", "Seen part 3"]
    assert gemini.kinds("chapters") == ["chapters"]


def test_segment_without_thumbnails_is_filled_from_text_only(gemini):
    photos = book_photos()
    for p in photos[5:10]:          # segment 2 only: no key AND no thumbnail URL
        p.thumbnail_key = None
        p.url = p.thumbnail_url = p.preview_url = "/uploads/originals/none.jpg"
    batch, _ = generate(photos, sid())
    assert seg_titles(batch) == ["Seen part 1", "Text part 2", "Seen part 3"]
    assert "vision segment=1" not in gemini.kinds("vision")


def test_budget_bounds_generation_and_late_results_are_kept(gemini, monkeypatch):
    monkeypatch.setattr(story_ai, "GEMINI_VISION_BUDGET_SEC", 0.5)
    gemini.vision_delay = 1.5
    session, photos = sid(), book_photos()

    start = time.perf_counter()
    batch, _ = generate(photos, session)
    elapsed = time.perf_counter() - start
    assert elapsed < 1.4, f"budget 0.5s took {elapsed:.2f}s"
    assert seg_titles(batch) == ["Text part 1", "Text part 2", "Text part 3"]

    time.sleep(1.6)                  # let the in-flight calls finish and cache
    gemini.vision_delay = 0.0
    before = len(gemini.kinds("vision"))
    batch, _ = generate(photos, session)
    assert len(gemini.kinds("vision")) == before, "late results were not cached"
    assert seg_titles(batch) == ["Seen part 1", "Seen part 2", "Seen part 3"]


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def test_repeat_generation_makes_no_calls(gemini):
    session, photos = sid(), book_photos()
    generate(photos, session)
    n = len(gemini.calls)
    generate(photos, session)
    assert len(gemini.calls) == n


def test_changing_one_segment_recaptions_only_that_segment(gemini):
    session, photos = sid(), book_photos()
    generate(photos, session)
    first = set(gemini.kinds("vision"))

    replacement = book_photos(groups=3, per_group=5, prefix="swap_")[5]   # a different photo...
    replacement.timestamp_epoch = photos[5].timestamp_epoch              # ...in segment 2's slot
    replacement.hero_score = 99.0                                         # so it is picked
    photos[5] = replacement
    generate(photos, session)
    second = gemini.kinds("vision")[len(first):]
    assert second == ["vision segment=1"], f"re-captioned more than the changed segment: {second}"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    "A lovely photo of the family",      # names the medium
    "Captured in golden light",
    "Joy",                                # too short
    "One two three four five six seven eight nine",   # too long
])
def test_vision_captions_are_filtered(bad):
    seg = validate_vision_segment({"title": "Where it all began",
                                   "captions": [bad, "Warm smiles all around", "Together in this moment"]})
    assert bad not in seg.captions
    assert seg.captions == ["Warm smiles all around", "Together in this moment"]


@pytest.mark.parametrize("claim", [
    "Enjoying the sunny afternoon",        # time of day + light
    "Relaxing indoors on the couch",       # setting + object
    "Dancing under the green trees",       # setting
    "The bride and her mother",            # specific relationships
    "Golden hour smiles all around",       # light
])
def test_unverifiable_claims_are_dropped(claim):
    seg = validate_vision_segment({"title": "Where it all began",
                                   "captions": [claim, "Warm smiles all around", "Together in this moment"]},
                                  occasion="Family holiday")
    assert claim not in seg.captions


@pytest.mark.parametrize("line", [
    "Smiles shared among friends", "Laughter filling the air", "Surrounded by good company",
    "Everyone gathered close",
])
def test_people_lines_dropped_where_faces_are_rare(line):
    raw = {"title": "Where it all began", "captions": [line, "Wonders along the way", "Every step tells a story"]}
    # Face detection found people: the line is fine.
    assert line in validate_vision_segment(raw, occasion="Trip", people="a few people").captions
    # Mostly animals, landscapes or objects: the line would be wrong under most photos.
    assert line not in validate_vision_segment(raw, occasion="Trip", people="few or no people").captions


@pytest.mark.parametrize("line, seen", [
    ("Celebrating surrounded by loved ones", "some"),   # found live in round 4
    ("Views from the road", "all"),                    # literal setting, found live in round 4
])
def test_round_four_leaks_are_closed(line, seen):
    raw = {"people_visible": seen, "title": "Where it all began",
           "captions": [line, "Every step tells a story", "Onward we go together"]}
    assert line not in validate_vision_segment(raw, occasion="Trip").captions


@pytest.mark.parametrize("seen", ["none", "some"])
def test_gemini_reporting_few_people_enables_the_people_filter(seen):
    raw = {"people_visible": seen, "title": "Wonders along the way",
           "captions": ["Smiles shared among friends", "Every step tells a story", "Deep into the wild"]}
    assert "Smiles shared among friends" not in validate_vision_segment(raw, occasion="Trip").captions


def test_gemini_reporting_all_people_keeps_people_lines():
    raw = {"people_visible": "all", "title": "Where it all began",
           "captions": ["Smiles shared among friends", "Every step tells a story"]}
    assert "Smiles shared among friends" in validate_vision_segment(raw, occasion="Trip").captions


@pytest.mark.parametrize("line", [
    "Middle of the journey", "Passing through the middle chapters", "Turning another page",
    "A book of memories",
])
def test_structure_words_are_dropped(line):
    raw = {"title": "Where it all began", "captions": [line, "Every step tells a story", "Onward we go together"]}
    assert line not in validate_vision_segment(raw, occasion="Trip").captions


def test_people_fact_omitted_when_no_face_was_ever_detected():
    # Face detection can silently fail to load and store 0 for everyone; "few
    # or no people" would then be false for most books.
    photos = book_photos()
    for p in photos:
        p.face_count = 0
    facts = build_story_context("Trip", photos).segment_facts()
    assert all("people" not in f for f in facts)
    for p in photos[:5]:
        p.face_count = 4
    facts = build_story_context("Trip", photos).segment_facts()
    assert facts[0]["people"] == "groups" and facts[1]["people"] == "few or no people"


@pytest.mark.parametrize("line", ["Sweet focus on the hours", "Where our story began", "Sunday funday"])
def test_filters_match_whole_words_only(line):
    # Guards the word boundaries: without them "us" matches inside "focus",
    # "sun" inside "Sunday", and good lines are rejected.
    from app.engine.story_content import people_claims, unverifiable_claims

    assert people_claims(line) == [] and unverifiable_claims(line, "Trip") == []


def test_repeated_captions_are_removed_across_segments():
    from app.engine.story_content import SegmentContent, dedupe_across_segments

    segs = [
        SegmentContent("Where it all began", ["A day to remember", "Every step tells a story", "Wonders along the way"]),
        None,
        SegmentContent("The journey continues", ["A day to remember", "Every step tells a story", "Onward together"]),
    ]
    dedupe_across_segments(segs)
    assert segs[2].captions[0] == "Onward together"
    assert len(segs[2].captions) >= 2, "a segment must keep its minimum even when that means a repeat"


def test_occasion_text_grounds_its_own_words():
    raw = {"title": "Beach days together", "captions": ["Toes in the beach sand", "Warm smiles all around"]}
    assert validate_vision_segment(raw, occasion="Beach trip in Goa").title == "Beach days together"
    with pytest.raises(StoryContentInvalid):
        validate_vision_segment(raw, occasion="Family holiday")   # 'beach' not grounded here


def test_trailing_full_stop_is_removed_but_ellipsis_kept():
    seg = validate_vision_segment({"title": "Where it all began.",
                                   "captions": ["Warm smiles all around.", "And so it begins..."]})
    assert seg.title == "Where it all began"
    assert seg.captions == ["Warm smiles all around", "And so it begins..."]


def test_vision_segment_without_usable_title_is_rejected():
    with pytest.raises(StoryContentInvalid):
        validate_vision_segment({"title": "Picture perfect", "captions": ["Warm smiles all around"] * 3})


# ---------------------------------------------------------------------------
# Reshuffle keeps vision captions
# ---------------------------------------------------------------------------

def test_reshuffle_keeps_vision_captions(gemini, client, store):
    from app.main import process_async_job

    photos = book_photos()
    session, job_id = sid(), f"job_{uuid.uuid4().hex[:8]}"
    store.create_session(session, expected_photo_count=len(photos))
    store.save_photos_batch(photos, session_id=session)
    store.save_job(
        JobStatusResponse(job_id=job_id, status="processing", progress=10, message="Queued", result=None),
        session_id=session, include_text=True, user_prompt="Family wedding", caption_strategy="vision",
    )
    asyncio.run(process_async_job(
        job_id=job_id, photo_ids=[p.id for p in photos], user_prompt="Family wedding",
        session_id=session, use_photo_vision=True,
    ))
    job = store.get_job(job_id)
    before = {s.text_content for sp in job.result.variations[0].spreads
              for pg in (sp.left_page, sp.right_page) for s in pg.slots if s.type == "text"}
    assert "SEEN PART 1" in before
    calls = len(gemini.calls)

    res = client.post("/api/variations/reshuffle", json={"job_id": job_id, "seed_offset": 1, "session_id": session})
    assert res.status_code == 200
    after = {s["text_content"] for sp in res.json()["variations"][0]["spreads"]
             for pg in ("left_page", "right_page") for s in sp[pg]["slots"] if s["type"] == "text"}
    assert after <= before and "SEEN PART 1" in after
    assert len(gemini.calls) == calls, "reshuffle must not call Gemini"
