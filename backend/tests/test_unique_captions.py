"""
A different caption on every spread.

The mechanism: the spread plan (spread_plan.py) says, before any Gemini call,
how many spreads each story segment gets in each variation. Each request asks
for that many lines (instead of a fixed handful), the solver's allocator gives
every spread a line no other spread in the book uses, and a free local bank
covers any shortfall -- and the whole book when Gemini is off.
"""

import collections
import hashlib
import json
import re
import uuid

import pytest

import app.engine.story_ai as story_ai
from app.engine import caption_bank
from app.engine.caption_assign import CaptionAllocator
from app.engine.solver import generate_photobook_variations_engine
from app.engine.spread_plan import caption_demand, chapter_chunks, spread_has_people
from app.engine.story_content import (
    _META_WORDS, build_story_context, people_claims, position_claims, unverifiable_claims, valid_caption,
    validate_vision_segment,
)
from app.schemas.photobook import PhotoMeta
from tests.fixtures.golden_story import photo_sets

WORDS = (
    "alpha bravo charlie delta echo foxtrot golf hotel india juliett kilo lima mike "
    "november oscar papa quebec romeo sierra tango uniform victor whiskey xray yankee zulu"
).split()


# ---------------------------------------------------------------------------
# Books
# ---------------------------------------------------------------------------

def _photo(pid, ts, faces, ar=1.5, hero=80.0):
    h = hashlib.sha256(pid.encode()).hexdigest()
    return PhotoMeta(
        id=pid, filename=f"{pid}.jpg", url=f"/uploads/thumbnails/s/{pid}_thumb.jpg",
        thumbnail_key=f"thumbnails/s/{pid}_thumb.jpg", width=4000, height=int(4000 / ar),
        aspect_ratio=ar, hero_score=hero, face_count=faces,
        shell_phash=h[:16], core_phash=h[16:32], timestamp_epoch=ts,
    )


def big_book(groups=50, per_group=20, prefix="big"):
    """1,000 photos: bursts 3 h apart; alternate bursts with and without faces."""
    base = 1_785_500_000.0
    return [
        _photo(f"{prefix}{g}_{i}", base + g * 10_800 + i * 60, 2 if g % 2 == 0 else 0,
               ar=(1.5, 0.75, 1.0)[(g + i) % 3], hero=60.0 + (g * 7 + i * 3) % 35)
        for g in range(groups) for i in range(per_group)
    ]


def captions_of(variation):
    return [
        s.text_content
        for sp in variation.spreads for pg in (sp.left_page, sp.right_page)
        for s in pg.slots if s.type == "text" and s.text_content
    ]


def repeats(variation):
    return [t for t, n in collections.Counter(captions_of(variation)).items() if n > 1]


# ---------------------------------------------------------------------------
# A fake Gemini that answers with exactly what the prompt asks for
# ---------------------------------------------------------------------------

class SizedGemini:
    """Parses the requested line counts out of the real prompt text."""

    def __init__(self):
        self.calls = []
        self.counter = 0

    def _line(self, people):
        self.counter += 1
        a, b = WORDS[self.counter % 26], WORDS[(self.counter // 26) % 26]
        return f"{'Smiles' if people else 'Tale'} {self.counter} {a} {b}"

    def __call__(self, prompt, timeout_sec, kind, images=None):
        self.calls.append((kind.split(" ")[0], len(images or []), 0))
        if kind == "book":
            return {
                "category": "Travel", "titles": ["Away", "Journeys", "The trip", "Wander"],
                "subtitles": ["Far and wide", "Time away"],
                "variations": [{"theme_name": t, "cover_title": "Away", "cover_subtitle": "Far",
                                "captions": [self._line(False) for _ in range(6)]}
                               for t in ("Warm", "Elegant", "Minimal")],
            }
        if kind.startswith("chapters"):
            asked = json.loads(prompt.split("known about each segment:\n", 1)[1].split("\n", 1)[0])
            out = []
            for a in asked:
                out.append({
                    "segment_index": a["segment_index"], "title": f"Part {a['segment_index']} {WORDS[a['segment_index'] % 26]}",
                    "neutral_lines": [self._line(False) for _ in range(a["neutral_lines"])],
                    "people_lines": [self._line(True) for _ in range(a["people_lines"])],
                })
            self.calls[-1] = (self.calls[-1][0], 0, sum(a["neutral_lines"] + a["people_lines"] for a in asked))
            return {"segments": out}
        # vision
        n = int(re.search(r"EXACTLY (\d+) neutral", prompt).group(1))
        m = int(re.search(r"EXACTLY (\d+) people", prompt).group(1))
        self.calls[-1] = ("vision", len(images or []), n + m)
        return {"people_visible": "all", "title": f"Seen {self.counter} bravo",
                "neutral_lines": [self._line(False) for _ in range(n)],
                "people_lines": [self._line(True) for _ in range(m)]}


@pytest.fixture
def sized(monkeypatch):
    fake = SizedGemini()
    monkeypatch.setattr(story_ai, "ENABLE_GEMINI_API", True)
    monkeypatch.setattr(story_ai, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(story_ai, "CHAPTER_CAPTIONS_ENABLED", True)
    monkeypatch.setattr(story_ai, "CAPTION_STRATEGY", "vision")
    monkeypatch.setattr(story_ai, "_invoke_gemini_json", fake)
    import app.engine.representatives as reps
    monkeypatch.setattr(reps, "representative_image_bytes", lambda p: b"jpeg:" + p.id.encode())
    return fake


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr(story_ai, "ENABLE_GEMINI_API", False)
    monkeypatch.setattr(story_ai, "GEMINI_API_KEY", "")


def generate(photos, prompt="Family holiday", vision=False, session=None):
    ctx = build_story_context(prompt, photos)
    batch = story_ai.generate_story_theme_batch(
        prompt, len(photos), session or f"sess_u_{uuid.uuid4().hex[:8]}", story_context=ctx,
        use_photo_vision=vision,
    )
    return generate_photobook_variations_engine(photos, batch, story_context=ctx), ctx


# ---------------------------------------------------------------------------
# Bank
# ---------------------------------------------------------------------------

def _all_bank():
    out = [("neutral", l) for l in caption_bank.GENERAL_NEUTRAL] + [("people", l) for l in caption_bank.GENERAL_PEOPLE]
    for kinds in caption_bank.CATEGORY_LINES.values():
        out += [(k, l) for k, ls in kinds.items() for l in ls]
    return out


def test_every_bank_line_obeys_the_caption_rules():
    for kind, line in _all_bank():
        assert valid_caption(line) == line, f"{line!r} fails basic validation"
        assert unverifiable_claims(line, None) == [], f"{line!r} makes a claim"
        assert not _META_WORDS.search(line), f"{line!r} mentions the medium or book"
        assert position_claims(line) == [], f"{line!r} claims a place in the story"
        if kind == "neutral":
            assert people_claims(line) == [], f"neutral {line!r} needs people in the photo"


def test_bank_has_no_duplicates():
    lines = [l.upper() for _, l in _all_bank()]
    assert len(lines) == len(set(lines))


def test_bank_covers_every_category():
    from app.engine.color_extractor import CATEGORY_THEMES_MAP
    assert set(CATEGORY_THEMES_MAP) == set(caption_bank.CATEGORY_LINES)


# ---------------------------------------------------------------------------
# Spread plan
# ---------------------------------------------------------------------------

def test_demand_covers_the_densest_variation():
    photos = big_book(groups=6, per_group=20, prefix="dm")
    ctx = build_story_context("Trip", photos)
    for s_idx, members in enumerate(ctx.segments):
        for v in range(3):
            chunks = [c for ci in members for c in chapter_chunks(ctx.raw_chapters[ci]["photos"], v)]
            people = sum(1 for c in chunks if spread_has_people(c))
            assert people <= ctx.demand[s_idx]["people"]
            assert len(chunks) - people <= ctx.demand[s_idx]["neutral"]


def test_solver_lays_out_exactly_the_planned_spreads(offline):
    photos = big_book(groups=4, per_group=15, prefix="pl")
    variations, ctx = generate(photos)
    for v, variation in enumerate(variations):
        planned = sum(len(chapter_chunks(ch["photos"], v)) for ch in ctx.raw_chapters)
        assert len(variation.spreads) == planned


# ---------------------------------------------------------------------------
# Uniqueness
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["single", "multi", "large"])
def test_offline_books_never_repeat_a_caption(offline, name):
    variations, _ = generate(photo_sets()[name])
    for v in variations:
        assert repeats(v) == [], f"{name} variation {v.id} repeats {repeats(v)[:3]}"


def test_online_thousand_photo_book_never_repeats(sized):
    variations, ctx = generate(big_book(), vision=False)
    assert len(ctx.segments) == 20
    for v in variations:
        assert repeats(v) == [], f"variation {v.id} repeats {repeats(v)[:3]}"
        assert len(captions_of(v)) == len(v.spreads)


def test_online_vision_thousand_photo_book_never_repeats(sized):
    variations, _ = generate(big_book(prefix="vb"), vision=True)
    for v in variations:
        assert repeats(v) == [], f"variation {v.id} repeats {repeats(v)[:3]}"


def test_request_sizing_matches_demand_and_limits(sized):
    _, ctx = generate(big_book(prefix="cs"), vision=True)
    needed = sum(d["people"] + d["neutral"] for d in ctx.demand)
    vision = [c for c in sized.calls if c[0] == "vision"]
    assert all(lines <= story_ai.VISION_LINES_PER_REQUEST for _, _, lines in vision)
    assert all(images <= 3 for _, images, _ in vision)
    asked = sum(lines for _, _, lines in vision)
    assert needed <= asked <= needed * 1.25 + 2 * len(ctx.segments), (needed, asked)
    # Cost stays per segment, not per photo: a 1,000-photo book is ~20-30 requests.
    assert len(vision) <= 40
    assert sum(images for _, images, _ in vision) <= 3 * 40


def test_text_requests_are_batched(sized):
    _, ctx = generate(big_book(prefix="tb"), vision=False)
    text = [c for c in sized.calls if c[0] == "chapters"]
    assert all(lines <= story_ai.TEXT_LINES_PER_REQUEST for _, _, lines in text)
    needed = sum(d["people"] + d["neutral"] for d in ctx.demand)
    assert len(text) <= needed // story_ai.TEXT_LINES_PER_REQUEST + len(ctx.segments)


def test_people_lines_only_on_spreads_with_faces(sized):
    # Faces vary WITHIN each segment (pairs of photos with, pairs without), so
    # every segment has both a people pool and spreads that must not use it.
    base = 1_785_500_000.0
    photos = [_photo(f"pp{g}_{i}", base + g * 10_800 + i * 60, 2 if (i // 2) % 2 == 0 else 0)
              for g in range(8) for i in range(20)]
    faces = {p.id: p.face_count for p in photos}
    variations, _ = generate(photos, vision=False)
    checked = with_people_lines = 0
    for v in variations:
        for sp in v.spreads:
            texts = [s.text_content for pg in (sp.left_page, sp.right_page) for s in pg.slots if s.type == "text"]
            photo_ids = {s.photo_id for pg in (sp.left_page, sp.right_page) for s in pg.slots if s.type == "photo"}
            has_faces = any(faces.get(pid, 0) > 0 for pid in photo_ids)
            checked += 1
            for t in texts:
                if t.startswith("SMILES"):
                    with_people_lines += 1
                    assert has_faces, f"people line {t!r} on a spread without faces"
    assert with_people_lines > 0, "the test must actually exercise people lines"
    assert any(
        not any(faces.get(s.photo_id, 0) for pg in (sp.left_page, sp.right_page) for s in pg.slots if s.type == "photo")
        for v in variations for sp in v.spreads
    ), "the test must include spreads without faces"


def test_variations_do_not_start_the_same(sized):
    variations, _ = generate(big_book(groups=6, prefix="vs"), vision=False)
    first = [captions_of(v)[1:4] for v in variations]
    assert first[0] != first[1] != first[2]


def test_regenerate_and_reshuffle_structure_reproduce_captions(offline):
    photos = photo_sets()["large"]
    a, _ = generate(photos, session="sess_u_same")
    b, _ = generate(photos, session="sess_u_same")
    assert [captions_of(v) for v in a] == [captions_of(v) for v in b]


# ---------------------------------------------------------------------------
# Found in the live run
# ---------------------------------------------------------------------------

def test_story_position_lines_are_dropped_but_titles_may_say_it():
    # Live: a large closing segment put "Final farewell moments" on spread 3.
    seg = validate_vision_segment({
        "title": "The journey begins",
        "neutral_lines": ["Final farewell moments", "Cherishing the closing scenes", "Every step an adventure",
                          "Where wonder lives on", "Arriving at last"],
        "people_lines": [],
    })
    assert seg.title == "The journey begins"
    assert seg.captions == ["Every step an adventure", "Where wonder lives on"]


def test_people_word_title_never_lands_on_a_faceless_spread():
    # Live: the title "Shared laughter everywhere" was printed on a spread
    # without faces in all three variations.
    base = 1_785_500_000.0
    photos = [_photo(f"tt{g}_{i}", base + g * 10_800 + i * 60, 0 if g == 1 else 2) for g in range(3) for i in range(6)]
    ctx = build_story_context("Trip", photos)
    assert len(ctx.segments) == 3
    batch = {
        "variations": [{"theme_name": "Warm", "captions": [f"Line {w} story" for w in WORDS]}] * 3,
        "chapters": {
            "signature": ctx.signature, "chapter_segment": ctx.chapter_segment,
            "segments": [{"title": t, "captions": [f"Seg {i} {w} tale" for w in WORDS], "people": []}
                         for i, t in enumerate(["Where it starts", "Shared laughter everywhere", "Onward we go"])],
        },
        "reserve": {"people": [], "neutral": []},
    }
    for v in generate_photobook_variations_engine(photos, batch, story_context=ctx):
        assert "SHARED LAUGHTER EVERYWHERE" not in captions_of(v)
        assert "WHERE IT STARTS" in captions_of(v) and "ONWARD WE GO" in captions_of(v)


# ---------------------------------------------------------------------------
# Allocator
# ---------------------------------------------------------------------------

def test_allocator_skips_near_duplicates():
    alloc = CaptionAllocator(0, variation_pool=["A day to remember", "A day to remember forever", "Onward we go"])
    assert alloc.take(None, False) == "A day to remember"
    assert alloc.take(None, False) == "Onward we go"


def test_allocator_keeps_digits_significant():
    alloc = CaptionAllocator(0, variation_pool=["Day 1 begins here", "Day 2 begins here"])
    assert {alloc.take(None, False), alloc.take(None, False)} == {"Day 1 begins here", "Day 2 begins here"}


def test_allocator_never_puts_people_words_on_faceless_spreads():
    alloc = CaptionAllocator(0, variation_pool=["Smiles that say it all", "Every detail tells a story"])
    assert alloc.take(None, has_people=False) == "Every detail tells a story"


def test_allocator_falls_back_to_reserve_then_repeats():
    alloc = CaptionAllocator(0, variation_pool=["Only one line here"], reserve={"neutral": ["A reserve line"], "people": []})
    got = [alloc.take(None, False) for _ in range(3)]
    assert got[:2] == ["Only one line here", "A reserve line"]
    assert alloc.repeats == 1
