"""
Story content: the data shapes, validation rules and story context behind a
photobook's titles and captions.

This module makes no network calls and holds no state. story_ai.py decides
WHERE content comes from (cache, Gemini, offline fallback); this module decides
what valid content IS, so both entry points (chat suggestions and generation)
apply the same rules.

Text is stored RAW -- in the case Gemini wrote it. to_display() is the single
place text is transformed for the page, so a future design that wants sentence
case changes one function and re-generates nothing.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from reportlab.pdfbase.pdfmetrics import stringWidth

from app.engine.color_extractor import CATEGORY_THEMES_MAP, THEME_PALETTES

ALLOWED_CATEGORIES = list(CATEGORY_THEMES_MAP.keys())

VARIATION_COUNT = 3
TITLE_COUNT = 4
SUBTITLE_COUNT = 2

# Caption pool per variation. The prompt asks for 6; MIN is the floor below which
# a book of ~50 spreads repeats captions so often the pool is not worth using.
MIN_CAPTIONS = 4
MAX_CAPTIONS = 8

# Per story segment. Lower than MIN_CAPTIONS: a segment can be only a few spreads.
MIN_SEGMENT_CAPTIONS = 2
MAX_SEGMENT_CAPTIONS = 8

# Grouping chapters into segments before prompting. partition_macro_chapters caps
# chapters at 12/16/24 photos, so a 1000-photo book has 40-60 chapters: too many
# to caption in one call within a timeout, and most of those boundaries are cap
# splits rather than story breaks anyway.
MAX_STORY_SEGMENTS = 20

# Cover titles and subtitles are shown in the UI only; the PDF never draws them,
# so this is a readability cap, not a layout limit.
MAX_TITLE_CHARS = 48

# ---------------------------------------------------------------------------
# Caption box geometry -- mirrors the renderer, so "valid" means "prints".
#
#   dsa_solver.build_dsa_spread_pair: caption slot w_pct = 0.40, h_pct = 0.05
#   pdf_exporter: slot width  = w_pct * (page_w * 2)   (slots span the spread)
#                 slot height = h_pct * page_h
#                 font        = Helvetica-Bold at max(10, slot_h * 0.38)
#                 drawn with drawCentredString, which never wraps
#
# The frontend always exports 200 x 200 mm (App.jsx). A smaller or portrait page
# fits fewer characters, because the 10 pt font floor stops the font shrinking
# with the box; revisit this if other sizes are offered.
# ---------------------------------------------------------------------------
_MM_TO_PT = 2.83464567
PRINT_PAGE_W_MM = 200.0
PRINT_PAGE_H_MM = 200.0
CAPTION_FONT = "Helvetica-Bold"
_CAPTION_BOX_W_PT = 0.40 * (PRINT_PAGE_W_MM * _MM_TO_PT * 2.0)
_CAPTION_FONT_PT = max(10.0, 0.05 * PRINT_PAGE_H_MM * _MM_TO_PT * 0.38)
# Headroom for the bleed and for the eye: text that exactly fills the box reads
# as touching its edges.
CAPTION_MAX_WIDTH_PT = _CAPTION_BOX_W_PT * 0.96

_CHAPTER_LABEL = re.compile(r"^CHAPTER \d+:", re.IGNORECASE)
_QUOTES = "\"'“”‘’`"


class StoryContentInvalid(ValueError):
    """Model output that cannot be used. Callers fall back to offline content."""


# ---------------------------------------------------------------------------
# Text rules
# ---------------------------------------------------------------------------

def to_display(text: Optional[str]) -> str:
    """How stored text appears on the page. The ONE place case is transformed."""
    return (text or "").upper()


def normalize_prompt(prompt: Optional[str]) -> str:
    """Cache identity for a prompt: 'Wedding  Udaipur' and 'wedding udaipur' match."""
    return " ".join(unicodedata.normalize("NFKC", prompt or "").lower().split())


def clean_text(value: Any) -> Optional[str]:
    """Trim model text to a canonical form, or None when nothing usable is left."""
    if not isinstance(value, str):
        return None
    text = " ".join(unicodedata.normalize("NFKC", value).split())
    text = text.strip(_QUOTES).strip()
    # A caption is a line, not a sentence: a trailing full stop reads as an
    # error on the page, and the model adds one inconsistently.
    text = re.sub(r"(?<!\.)\.$", "", text).strip()
    return text or None


# ---------------------------------------------------------------------------
# Unverifiable claims
#
# A caption is written from at most a few photos -- or none -- but printed under
# EVERY photo in its pool: book captions rotate across the whole book, segment
# captions across the whole segment. So a caption must not assert anything a
# photo it was never checked against could contradict: time of day, light,
# weather, season, indoor/outdoor, a specific place or object, or a specific
# relationship. Testing on real uploads found these in 1 of 4 lines ("Enjoying
# the sunny afternoon" printed under night concert photos, "Relaxing indoors on
# the couch" under tents). The prompts ask for this too; this is the check that
# holds regardless of what the model does.
#
# Words the user's OWN occasion text contains are grounded and allowed:
# "Beach trip in Goa" legitimately permits "beach".
# ---------------------------------------------------------------------------

_UNVERIFIABLE_TERMS = (
    # time of day
    "morning", "mornings", "noon", "midday", "afternoon", "afternoons", "evening", "evenings",
    "night", "nights", "nighttime", "tonight", "dusk", "dawn", "twilight", "daybreak", "daytime",
    "sunset", "sunsets", "sunrise", "sunrises",
    # light
    "sun", "suns", "sunny", "sunlit", "sunlight", "sunshine", "sunbeam", "sunbeams", "sunkissed",
    "moon", "moonlit", "moonlight", "star", "stars", "starry", "starlight", "candlelight",
    "light", "lights", "lit", "glow", "glowing", "glows", "golden", "shadow", "shadows", "shade",
    # weather and season
    "rain", "rainy", "snow", "snowy", "cloud", "clouds", "cloudy", "fog", "foggy", "mist", "misty",
    "breeze", "breezy", "wind", "windy", "storm", "summer", "winter", "autumn", "monsoon",
    # indoor / outdoor and settings
    "indoor", "indoors", "outdoor", "outdoors", "outside", "inside", "sky", "skies", "sea", "ocean",
    "beach", "shore", "waves", "garden", "gardens", "park", "grass", "field", "fields", "meadow",
    "forest", "woods", "tree", "trees", "mountain", "mountains", "hill", "hills", "lake", "river",
    "city", "street", "streets", "road", "roads", "plaza", "balcony", "waterfront", "room", "rooms", "couch", "sofa", "bench",
    "stage", "venue", "table", "kitchen", "home",
    # specific relationships (the warm generic ones -- family, friends, loved
    # ones, together -- are fine: they describe the book, not a person)
    "bride", "groom", "husband", "wife", "mother", "father", "mom", "mum", "dad", "parents",
    "grandma", "grandpa", "grandmother", "grandfather", "grandparents", "sister", "sisters",
    "brother", "brothers", "siblings", "son", "daughter", "baby", "babies", "kid", "kids",
    "child", "children", "boy", "boys", "girl", "girls",
)
_UNVERIFIABLE = re.compile(r"\b(" + "|".join(_UNVERIFIABLE_TERMS) + r")\b", re.IGNORECASE)
_GOLDEN_HOUR = re.compile(r"\bgolden hour\b", re.IGNORECASE)


def grounded_terms(occasion: Optional[str]) -> set:
    """Lower-case words of the user's occasion text, singular and plural."""
    words = set(re.findall(r"[a-z]+", normalize_prompt(occasion)))
    return words | {w + "s" for w in words} | {w[:-1] for w in words if w.endswith("s")}


NO_PEOPLE = "few or no people"


def people_label(avg_faces_per_photo: float) -> str:
    """Local face detection, averaged per photo, as the label the prompts use."""
    if avg_faces_per_photo >= 3:
        return "groups"
    if avg_faces_per_photo >= 1:
        return "a few people"
    return NO_PEOPLE


# Lines that are only true if people are in the photo. Under a segment whose
# photos are mostly animals, landscapes or objects -- where local face
# detection found few or no faces -- "Smiles shared among friends" is wrong for
# most of the photos it will be printed under. Testing found exactly this on a
# mixed segment of wildlife, art and one group selfie.
_PEOPLE_WORDS = re.compile(
    r"\b(smiles?|smiling|laugh|laughs|laughter|laughing|faces?|friends?|company|hugs?|hugging|"
    r"embrace|cheers|gathered|gathering|crowd|guests?|everyone|loved ones|people)\b",
    re.IGNORECASE,
)


# Lines that place themselves at the start or end of the story. A segment's
# lines are spread over ALL its spreads, in any order, so "Final farewell
# moments" lands mid-book -- measured live: a large closing segment put
# farewell lines on spreads 3 to 8. Only a title, which sits at the segment's
# first spread, may say where the story is.
_POSITION_WORDS = re.compile(
    r"\b(farewells?|goodbyes?|final|closing|ending|endings|parting|departure|departing|"
    r"begins|beginning|beginnings|arrival|arriving)\b",
    re.IGNORECASE,
)


def position_claims(text: str) -> List[str]:
    return [m.group(1).lower() for m in _POSITION_WORDS.finditer(text or "")]


def people_claims(text: str) -> List[str]:
    return [m.group(1).lower() for m in _PEOPLE_WORDS.finditer(text or "")]


def dedupe_across_segments(segments: List[Optional["SegmentContent"]]) -> None:
    """
    Remove captions an earlier segment already uses, in place. Segments are
    written independently (in parallel, for vision), so without this one book
    repeats "A day to remember" in several chapters. A segment keeps its
    repeats only as far as needed to stay at MIN_SEGMENT_CAPTIONS.
    """
    seen: set = set()
    for seg in segments:
        if seg is None:
            continue
        fresh = [c for c in seg.captions if c.upper() not in seen]
        if len(fresh) < MIN_SEGMENT_CAPTIONS:
            fresh += [c for c in seg.captions if c not in fresh][: MIN_SEGMENT_CAPTIONS - len(fresh)]
        seg.captions = fresh
        seen.update(c.upper() for c in seg.captions)
        seen.add(seg.title.upper())


def unverifiable_claims(text: str, occasion: Optional[str] = None) -> List[str]:
    """The claim words in text that the occasion does not itself ground."""
    allowed = grounded_terms(occasion)
    found = [m.group(1).lower() for m in _UNVERIFIABLE.finditer(text or "")]
    if _GOLDEN_HOUR.search(text or "") and "golden" not in allowed:
        found.append("golden hour")
    return [w for w in found if w not in allowed]


def is_printable(text: str) -> bool:
    """
    True when Helvetica can draw every character.

    The PDF uses a standard Type-1 font, whose WinAnsi encoding is cp1252. Emoji
    or non-Latin text (Hindi, say) would render as blank boxes in the print file
    while looking fine in the browser preview -- so it is rejected here, where
    the difference is still visible.
    """
    if any(unicodedata.category(ch) in ("Cc", "Cf") for ch in text):
        return False
    try:
        text.encode("cp1252")
    except UnicodeEncodeError:
        return False
    return True


def caption_width_pt(text: str) -> float:
    return stringWidth(to_display(text), CAPTION_FONT, _CAPTION_FONT_PT)


def caption_fits(text: str) -> bool:
    """
    Whether text fits the caption box once displayed.

    Measured on the DISPLAY form, since uppercasing can lengthen text ('ß' ->
    'SS') and caps are wider than lowercase. Measured in points rather than
    characters, because width varies too much per glyph for a character count to
    mean anything: 44 'W's overflow where 60 'I's do not.
    """
    return caption_width_pt(text) <= CAPTION_MAX_WIDTH_PT


def valid_caption(value: Any) -> Optional[str]:
    text = clean_text(value)
    if text is None or not is_printable(text) or not caption_fits(text):
        return None
    return text


def valid_title(value: Any) -> Optional[str]:
    text = clean_text(value)
    if text is None or not is_printable(text) or len(to_display(text)) > MAX_TITLE_CHARS:
        return None
    return text


def grounded(validator, occasion: Optional[str], people: Optional[str] = None):
    """
    validator, plus: reject text making claims the occasion does not ground,
    and -- where face detection found few or no people -- text that is only
    true of photos with people in them.
    """
    allowed = grounded_terms(occasion)

    def check(value: Any) -> Optional[str]:
        text = validator(value)
        if text is None or unverifiable_claims(text, occasion):
            return None
        if people == NO_PEOPLE and people_claims(text):
            return None
        # Lines about the medium or the book's own structure ("Middle of the
        # journey", "Passing through the middle chapters") -- the model echoing
        # the prompt's framing back. Testing produced several.
        if any(m.group(1).lower() not in allowed for m in _META_WORDS.finditer(text)):
            return None
        return text
    return check


def clean_pool(values: Any, validator=valid_caption, limit: int = MAX_CAPTIONS) -> List[str]:
    """Validated, case-insensitively de-duplicated entries, in order, capped at limit."""
    if not isinstance(values, list):
        return []
    out: List[str] = []
    seen = set()
    for value in values:
        text = validator(value)
        if text is None:
            continue
        key = to_display(text)
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# Content shapes
# ---------------------------------------------------------------------------

@dataclass
class VariationContent:
    theme_name: str
    cover_title: str
    cover_subtitle: str
    captions: List[str]


@dataclass
class BookContent:
    """Book-level text: category, cover options, and a caption pool per variation."""
    category: str
    titles: List[str]
    subtitles: List[str]
    variations: List[VariationContent]

    @property
    def primary_theme(self) -> str:
        return self.variations[0].theme_name

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BookContent":
        return cls(
            category=data["category"],
            titles=list(data["titles"]),
            subtitles=list(data["subtitles"]),
            variations=[VariationContent(**v) for v in data["variations"]],
        )


@dataclass
class SegmentContent:
    """
    One story segment's text. captions are NEUTRAL lines (true under any photo,
    free of people words); people are lines for spreads where face detection
    found someone. Pools are sized to the segment's spreads, so no spread in
    the book needs to repeat a line.
    """
    title: str
    captions: List[str]
    people: List[str] = field(default_factory=list)

    @property
    def all_lines(self) -> List[str]:
        return list(self.captions) + list(self.people)


@dataclass
class ChapterContent:
    """
    Per-segment text for one chapter structure. signature pins it to the photos
    it was written for: content whose signature differs from the book being laid
    out belongs to a different photo set and must not be applied.
    """
    signature: str
    segments: List[Optional[SegmentContent]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signature": self.signature,
            "segments": [asdict(s) if s else None for s in self.segments],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChapterContent":
        return cls(
            signature=data["signature"],
            segments=[SegmentContent(**s) if s else None for s in data["segments"]],
        )


def _themes_for(category: str) -> List[str]:
    """The category's mapped themes that actually have a palette, padded to 3."""
    mapped = [t for t in CATEGORY_THEMES_MAP.get(category, []) if t in THEME_PALETTES]
    for fallback in ("Warm", "Minimal", "Editorial", "Classic"):
        if len(mapped) >= VARIATION_COUNT:
            break
        if fallback in THEME_PALETTES and fallback not in mapped:
            mapped.append(fallback)
    return mapped


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_book_content(raw: Any, occasion: Optional[str] = None) -> BookContent:
    """
    Turn model output into BookContent, or raise StoryContentInvalid.

    Severity is split so one bad field does not discard a good response:
      reject  -- wrong structure, unknown category, too few titles/captions left
      repair  -- unknown theme (-> the category's mapped theme), a bad per-
                 variation cover title/subtitle (-> the book-level options)
      drop    -- an individual caption that is empty, unprintable, too wide
                 for the caption box, or a duplicate
    """
    if not isinstance(raw, dict):
        raise StoryContentInvalid("response is not a JSON object")

    category = clean_text(raw.get("category"))
    if category not in ALLOWED_CATEGORIES:
        raise StoryContentInvalid(f"unknown category {raw.get('category')!r}")

    titles = clean_pool(raw.get("titles"), valid_title, TITLE_COUNT)
    subtitles = clean_pool(raw.get("subtitles"), valid_title, SUBTITLE_COUNT)
    if len(titles) < TITLE_COUNT or len(subtitles) < SUBTITLE_COUNT:
        raise StoryContentInvalid(
            f"need {TITLE_COUNT} titles and {SUBTITLE_COUNT} subtitles, "
            f"got {len(titles)} and {len(subtitles)} valid"
        )

    raw_vars = raw.get("variations")
    if not isinstance(raw_vars, list) or len(raw_vars) < VARIATION_COUNT:
        raise StoryContentInvalid(f"need {VARIATION_COUNT} variations")

    themes = _themes_for(category)
    variations: List[VariationContent] = []
    for i, rv in enumerate(raw_vars[:VARIATION_COUNT]):
        if not isinstance(rv, dict):
            raise StoryContentInvalid(f"variation {i + 1} is not an object")
        # Book captions rotate across the whole book: nothing unverifiable.
        captions = clean_pool(rv.get("captions"), grounded(valid_caption, occasion))
        if len(captions) < MIN_CAPTIONS:
            raise StoryContentInvalid(
                f"variation {i + 1} has {len(captions)} usable captions, need {MIN_CAPTIONS}"
            )
        theme = clean_text(rv.get("theme_name"))
        if theme not in THEME_PALETTES:
            theme = themes[i % len(themes)]
        variations.append(VariationContent(
            theme_name=theme,
            cover_title=valid_title(rv.get("cover_title")) or titles[i % len(titles)],
            cover_subtitle=valid_title(rv.get("cover_subtitle")) or subtitles[i % len(subtitles)],
            captions=captions,
        ))

    return BookContent(category=category, titles=titles, subtitles=subtitles, variations=variations)


def validate_chapter_content(
    raw: Any,
    signature: str,
    segment_count: int,
    occasion: Optional[str] = None,
    facts: Optional[List[Dict[str, Any]]] = None,
) -> ChapterContent:
    """
    Turn model output into ChapterContent, or raise StoryContentInvalid.

    Segments are validated independently: an unusable segment becomes None and
    lays out with book-level captions, while its neighbours keep their text. Only
    a response with no usable segment at all is rejected.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("segments"), list):
        raise StoryContentInvalid("response has no segments list")

    by_index: Dict[int, Dict[str, Any]] = {}
    for pos, entry in enumerate(raw["segments"]):
        if not isinstance(entry, dict):
            continue
        idx = entry.get("segment_index", pos)
        if isinstance(idx, int) and 0 <= idx < segment_count and idx not in by_index:
            by_index[idx] = entry

    segments: List[Optional[SegmentContent]] = []
    for idx in range(segment_count):
        entry = by_index.get(idx)
        if entry is None:
            segments.append(None)
            continue
        people_fact = facts[idx].get("people") if facts and idx < len(facts) else None
        title = grounded(valid_caption, occasion, people_fact)(entry.get("title"))  # printed in the caption box
        neutral, people = split_pools(entry, valid_caption, occasion, people_fact)
        if title:
            neutral = [c for c in neutral if c.upper() != title.upper()]
            people = [c for c in people if c.upper() != title.upper()]
        if title is None or len(neutral) + len(people) < MIN_SEGMENT_CAPTIONS:
            segments.append(None)
            continue
        segments.append(SegmentContent(title=title, captions=neutral, people=people))

    if not any(segments):
        raise StoryContentInvalid("no segment passed validation")
    dedupe_across_segments(segments)
    return ChapterContent(signature=signature, segments=segments)


# A pool is sized to its spreads, not a fixed handful; this cap only guards
# against a runaway response.
MAX_POOL_LINES = 240


def split_pools(
    entry: Dict[str, Any],
    validator,
    occasion: Optional[str],
    people_fact: Optional[str] = None,
    limit: int = MAX_POOL_LINES,
) -> Tuple[List[str], List[str]]:
    """
    (neutral, people) lines from one segment entry.

    Neutral lines are placed on spreads without faces, so any line with a
    people word is refused there. People lines keep them. The single
    "captions" list of the earlier response shape (and of cached entries) is
    still read: its people lines are sorted into the people pool.
    """
    def placeable(check):
        # Lines, unlike titles, must not claim a position in the story.
        def run(value: Any) -> Optional[str]:
            text = check(value)
            return None if text is None or position_claims(text) else text
        return run

    no_people = placeable(grounded(validator, occasion, NO_PEOPLE))
    with_people = placeable(grounded(validator, occasion, None))
    if "neutral_lines" in entry or "people_lines" in entry:
        neutral = clean_pool(entry.get("neutral_lines"), no_people, limit)
        people = clean_pool(entry.get("people_lines"), with_people, limit)
    else:
        mixed = clean_pool(entry.get("captions"), with_people, limit)
        neutral = [c for c in mixed if not people_claims(c)]
        people = [c for c in mixed if people_claims(c)]
    if people_fact == NO_PEOPLE:
        people = []
    return neutral, people


# ---------------------------------------------------------------------------
# Story context
# ---------------------------------------------------------------------------

@dataclass
class ChapterContext:
    index: int
    photo_count: int
    start_epoch: float          # 0 when the chapter has no capture times
    end_epoch: float
    gap_before_sec: float       # 0 for the first chapter or without capture times
    moved_before: bool          # GPS jump > threshold from the previous chapter
    avg_faces: float

    @property
    def story_break_before(self) -> bool:
        """
        True when this chapter starts because the STORY moved on -- a time gap or
        a change of place -- rather than because the previous chapter hit its
        photo cap. Cap splits are layout bookkeeping, not narrative.
        """
        return self.index > 0 and (self.gap_before_sec > _TIME_GAP_SEC or self.moved_before)


# Must match partition_macro_chapters' defaults, so a boundary counts as a story
# break here exactly when it caused a time/GPS split there.
_TIME_GAP_SEC = 2700.0
_GPS_KM = 5.0


@dataclass
class StoryContext:
    """
    The one shared description of a book's story structure. Built once per
    generation and handed to both the content layer (what to write) and the
    solver (where chapters begin), so the two can never disagree about it.
    """
    prompt: str
    normalized_prompt: str
    raw_chapters: List[Dict[str, Any]] = field(repr=False)
    chapters: List[ChapterContext]
    segments: List[List[int]]   # chapter indices per segment, contiguous, in order
    signature: str
    # Per segment: {"people": n, "neutral": m} -- the lines needed so that no
    # spread in any variation repeats a caption (spread_plan.caption_demand).
    demand: List[Dict[str, int]] = field(default_factory=list)

    @property
    def chapter_segment(self) -> List[int]:
        mapping = [0] * len(self.chapters)
        for s_idx, members in enumerate(self.segments):
            for c_idx in members:
                mapping[c_idx] = s_idx
        return mapping

    def segment_facts(self) -> List[Dict[str, Any]]:
        """
        Compact, timezone-free facts per segment for the prompt.

        Deliberately no time of day: capture times come from EXIF parsed in the
        SERVER's timezone or, lacking EXIF, from the browser's UTC lastModified,
        and PhotoMeta does not record which. A 'morning' label would be wrong for
        some photos on any server whose timezone differs from the user's. Hours
        relative to the first photo are correct either way.
        """
        first_start = next((c.start_epoch for c in self.chapters if c.start_epoch > 0), 0.0)
        # A book in which not one photo has a detected face almost certainly
        # never ran face detection (it can silently fail to load), rather than
        # being a book with no people. Saying "few or no people" then would be
        # false for most books -- testing found every stored photo at 0 faces,
        # group selfies included -- so the fact is left out instead.
        faces_known = any(c.avg_faces > 0 for c in self.chapters)
        facts = []
        for s_idx, members in enumerate(self.segments):
            chs = [self.chapters[i] for i in members]
            photos = sum(c.photo_count for c in chs)
            fact: Dict[str, Any] = {"segment_index": s_idx, "photos": photos}
            starts = [c.start_epoch for c in chs if c.start_epoch > 0]
            ends = [c.end_epoch for c in chs if c.end_epoch > 0]
            if starts and ends and first_start:
                fact["hours_after_first_photo"] = round((min(starts) - first_start) / 3600.0, 1)
                fact["duration_hours"] = round((max(ends) - min(starts)) / 3600.0, 1)
            head = chs[0]
            if s_idx > 0:
                if head.gap_before_sec > 0:
                    fact["break_before_hours"] = round(head.gap_before_sec / 3600.0, 1)
                if head.moved_before:
                    fact["new_location"] = True
            if faces_known:
                faces = sum(c.avg_faces * c.photo_count for c in chs) / max(1, photos)
                fact["people"] = people_label(faces)
            facts.append(fact)
        return facts


def _attr(photo: Any, name: str, default=None):
    if isinstance(photo, dict):
        return photo.get(name, default)
    return getattr(photo, name, default)


def chapter_signature(raw_chapters: Sequence[Dict[str, Any]]) -> str:
    """Photo count per chapter. Partitioning is deterministic, so identical photos
    give an identical signature and any change to the photo set gives a new one."""
    return ",".join(str(len(ch.get("photos", []))) for ch in raw_chapters)


def _group_segments(chapters: List[ChapterContext]) -> List[List[int]]:
    """
    Group chapters into at most MAX_STORY_SEGMENTS contiguous segments, cutting
    only at story breaks. When there are more breaks than segments allow, the
    strongest are kept: a change of place first, then the longest time gap.
    """
    if not chapters:
        return []
    breaks = [c for c in chapters if c.story_break_before]
    if len(breaks) > MAX_STORY_SEGMENTS - 1:
        ranked = sorted(breaks, key=lambda c: (c.moved_before, c.gap_before_sec, -c.index), reverse=True)
        keep = {c.index for c in ranked[:MAX_STORY_SEGMENTS - 1]}
    else:
        keep = {c.index for c in breaks}

    segments: List[List[int]] = [[]]
    for c in chapters:
        if c.index in keep:
            segments.append([])
        segments[-1].append(c.index)
    return segments


def build_story_context(prompt: str, photos: Sequence[Any]) -> StoryContext:
    """Partition photos into chapters ONCE and derive everything story-shaped from it."""
    # Imported here: story_ai imports this module at load time.
    from app.engine.story_ai import haversine_km, partition_macro_chapters

    raw_chapters = partition_macro_chapters(list(photos))
    chapters: List[ChapterContext] = []
    prev_last = None
    prev_end = 0.0
    for idx, ch in enumerate(raw_chapters):
        ch_photos = ch.get("photos", [])
        times = [float(_attr(p, "timestamp_epoch", 0) or 0) for p in ch_photos]
        timed = [t for t in times if t > 0]
        start = min(timed) if timed else 0.0
        end = max(timed) if timed else 0.0
        first = ch_photos[0] if ch_photos else None

        gap = 0.0
        moved = False
        if idx > 0 and first is not None and prev_last is not None:
            t_first = float(_attr(first, "timestamp_epoch", 0) or 0)
            if t_first > 0 and prev_end > 0:
                gap = max(0.0, t_first - prev_end)
            moved = haversine_km(
                _attr(prev_last, "latitude"), _attr(prev_last, "longitude"),
                _attr(first, "latitude"), _attr(first, "longitude"),
            ) > _GPS_KM

        faces = [int(_attr(p, "face_count", 0) or 0) for p in ch_photos]
        chapters.append(ChapterContext(
            index=idx,
            photo_count=len(ch_photos),
            start_epoch=start,
            end_epoch=end,
            gap_before_sec=gap,
            moved_before=moved,
            avg_faces=(sum(faces) / len(faces)) if faces else 0.0,
        ))
        prev_last = ch_photos[-1] if ch_photos else prev_last
        prev_end = end or prev_end

    segments = _group_segments(chapters)
    ctx = StoryContext(
        prompt=prompt or "",
        normalized_prompt=normalize_prompt(prompt),
        raw_chapters=raw_chapters,
        chapters=chapters,
        segments=segments,
        signature=chapter_signature(raw_chapters),
    )
    from app.engine.spread_plan import caption_demand

    ctx.demand = caption_demand(raw_chapters, ctx.chapter_segment, len(segments))
    return ctx


# ---------------------------------------------------------------------------
# Cache keys
# ---------------------------------------------------------------------------

def book_cache_key(prompt: str, prompt_version: str) -> str:
    """
    Keyed on the prompt only. photo_count is deliberately excluded: the chat
    widget sends an estimate (often 0) before upload finishes and generation
    sends the real count, so including it would make every chat -> generate
    lookup miss -- doubling Gemini calls and showing different titles in the
    book than the chat just offered.
    """
    return "book:" + hashlib.sha256(f"{normalize_prompt(prompt)}|{prompt_version}".encode()).hexdigest()


def chapter_cache_key(prompt: str, signature: str, prompt_version: str, strategy: str = "chapter") -> str:
    """
    The whole book's chapter content. Text and vision content for the same
    photos are different content, so the strategy is part of the key. The
    'chapter' key is left exactly as it was, so existing entries stay valid.
    """
    ident = f"{normalize_prompt(prompt)}|{signature}|{prompt_version}"
    if strategy != "chapter":
        ident += f"|{strategy}"
    return "chapters:" + hashlib.sha256(ident.encode()).hexdigest()


def segment_cache_key(
    prompt: str, category: str, position: str, representative_ids: Sequence[str], prompt_version: str
) -> str:
    """
    One segment's vision captions. Identified by everything the request is built
    from: the prompt, category, story position and the exact images shown. Photo
    ids are unique and immutable, so they stand in for the images themselves --
    changing one segment's photos re-captions only that segment.
    """
    ids = ",".join(sorted(representative_ids))
    return "segment:" + hashlib.sha256(
        f"{normalize_prompt(prompt)}|{category}|{position}|{ids}|{prompt_version}".encode()
    ).hexdigest()


# ---------------------------------------------------------------------------
# Vision captions: stricter than text captions, because the model is now
# describing pixels and is tempted to narrate the medium or over-read a scene.
# ---------------------------------------------------------------------------

VISION_MIN_WORDS = 3
VISION_MAX_WORDS = 8
VISION_TITLE_MAX_WORDS = 6

# Captions sit under the photos; naming the medium ("a photo of...") reads as a
# description of the book rather than of the moment.
_META_WORDS = re.compile(
    r"\b(photos?|photographs?|images?|pictures?|pics?|shots?|snapshots?|captured?|capturing|camera|frames?|"
    r"chapters?|pages?|books?|albums?|photobooks?|middle)\b",
    re.IGNORECASE,
)


def _no_meta(text: Optional[str]) -> Optional[str]:
    return None if text is None or _META_WORDS.search(text) else text


def valid_vision_caption(value: Any) -> Optional[str]:
    text = _no_meta(valid_caption(value))
    if text is None or not (VISION_MIN_WORDS <= len(text.split()) <= VISION_MAX_WORDS):
        return None
    return text


def valid_vision_title(value: Any) -> Optional[str]:
    text = _no_meta(valid_caption(value))
    if text is None or len(text.split()) > VISION_TITLE_MAX_WORDS:
        return None
    return text


def validate_vision_segment(
    raw: Any, occasion: Optional[str] = None, people: Optional[str] = None, need_title: bool = True
) -> SegmentContent:
    """
    One segment's (or sub-part's) vision response -> SegmentContent, or
    StoryContentInvalid. Sub-parts after the first carry no title: only the
    segment's opening spread prints one.
    """
    if not isinstance(raw, dict):
        raise StoryContentInvalid("response is not a JSON object")
    # Gemini's own report of the photos it saw. Unlike local face counts it
    # cannot silently be zero, so it is trusted to switch the people filter on:
    # "some" (a mixed chapter) as much as "none", since a people line would be
    # printed under the photos without people too.
    if str(raw.get("people_visible", "")).strip().lower() == "none":
        people = NO_PEOPLE
    title = grounded(valid_vision_title, occasion, people)(raw.get("title")) if need_title else ""
    neutral, people_lines = split_pools(raw, valid_vision_caption, occasion, people)
    if title:
        neutral = [c for c in neutral if c.upper() != title.upper()]
        people_lines = [c for c in people_lines if c.upper() != title.upper()]
    if need_title and not title:
        raise StoryContentInvalid(f"unusable title {raw.get('title')!r}")
    if len(neutral) + len(people_lines) < MIN_SEGMENT_CAPTIONS:
        raise StoryContentInvalid(
            f"{len(neutral) + len(people_lines)} usable captions, need {MIN_SEGMENT_CAPTIONS}"
        )
    return SegmentContent(title=title, captions=neutral, people=people_lines)


def is_chapter_label(text: Optional[str]) -> bool:
    """The generic 'CHAPTER N: ...' label the solver prints at chapter starts."""
    return bool(text) and bool(_CHAPTER_LABEL.match(text))
