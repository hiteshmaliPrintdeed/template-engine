"""
Golden-output builder for the story/caption pipeline with NO Gemini key.

The contract this pins: with GEMINI_API_KEY unset, the book a user gets is
byte-for-byte what it was before the story-content rework. Everything the
rework adds (prompt-scoped cache, validation, chapter captions, the display
boundary) must be invisible on the offline path.

Photo hashes use hashlib rather than hash(). Python's hash() is salted per
process (PYTHONHASHSEED), so the pHash-driven spread clustering would differ
between the run that captured the golden file and the run that checks it.

Regenerate ONLY when a change to offline output is intended:
    python -m tests.fixtures.golden_story --write
"""

import hashlib
import json
import sys
from pathlib import Path

GOLDEN_PATH = Path(__file__).with_name("golden_story_nokey.json")

# The full dump is ~4 MB -- too heavy to commit. The golden file instead holds
# (a) a compact projection of every field the story/caption layer can influence,
#     so a failure shows a readable diff of exactly what moved, and
# (b) a SHA-256 of the complete dump, so nothing outside the projection can
#     drift unnoticed either.

PROMPTS = [
    "Wedding celebration in Udaipur",
    "Family trip to the temple",
    "Beach vacation in Goa",
    "an ordinary tuesday",
]


def _hex16(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()[:16]


def _photo(pid: str, ts: float, hero: float, ar: float, faces: int):
    from app.schemas.photobook import PhotoMeta

    return PhotoMeta(
        id=pid,
        filename=f"{pid}.jpg",
        url=f"/uploads/thumbnails/sess_golden/{pid}_thumb.jpg",
        thumbnail_url=f"/uploads/thumbnails/sess_golden/{pid}_thumb.jpg",
        preview_url=f"/uploads/thumbnails/sess_golden/{pid}_thumb.jpg",
        width=4000,
        height=int(4000 / ar),
        aspect_ratio=ar,
        hero_score=hero,
        face_count=faces,
        shell_phash=_hex16(pid + "s"),
        core_phash=_hex16(pid + "c"),
        dominant_colors=["#1E293B", "#64748B", "#F8FAFC"],
        timestamp_epoch=ts,
    )


def photo_sets():
    """Three shapes: one chapter, three time-split chapters, and a book large
    enough to hit the per-chapter photo cap as well as time gaps."""
    base = 1_785_500_000.0
    single = [_photo(f"s{i}", base + i * 60, 90.0 - i, 1.5, 1) for i in range(8)]

    multi = []
    for c, offset in enumerate((0, 10_800, 21_600)):
        for i in range(6 if c == 0 else 5):
            multi.append(_photo(f"m{c}_{i}", base + offset + i * 120, 92.0 - c * 5 - i, 1.5, 1))

    large = []
    ars = (1.5, 0.75, 1.0, 1.33)
    for c in range(5):
        for i in range(30):
            large.append(_photo(
                f"l{c}_{i}",
                base + c * 14_400 + i * 90,
                95.0 - ((c * 7 + i * 3) % 40),
                ars[(c + i) % len(ars)],
                (c + i) % 5,
            ))
    return {"single": single, "multi": multi, "large": large}


SCENARIOS = [
    {"include_text": True, "custom_title": None, "subtitle": None},
    {"include_text": False, "custom_title": None, "subtitle": None},
    {"include_text": True, "custom_title": "Nordic Light", "subtitle": "Summer 2026"},
]


def build():
    from app.engine.solver import generate_photobook_variations_engine
    from app.engine.story_ai import generate_story_theme_batch

    out = {}
    for set_name, photos in photo_sets().items():
        for prompt in PROMPTS:
            for s_i, sc in enumerate(SCENARIOS):
                batch = generate_story_theme_batch(
                    prompt,
                    total_photos=len(photos),
                    custom_title=sc["custom_title"],
                    include_text=sc["include_text"],
                    subtitle=sc["subtitle"],
                )
                variations = generate_photobook_variations_engine(
                    photos,
                    batch,
                    custom_title=sc["custom_title"],
                    include_text=sc["include_text"],
                    subtitle=sc["subtitle"],
                )
                out[f"{set_name}|{prompt}|{s_i}"] = [v.model_dump(mode="json") for v in variations]
    return out


def dump(data) -> str:
    return json.dumps(data, indent=1, sort_keys=True)


def project(data):
    """Text- and structure-bearing fields only: themes, cover text, and per
    spread the slot count plus every text slot's content."""
    proj = {}
    for key, variations in data.items():
        proj[key] = [
            {
                "id": v["id"],
                "theme_name": v["theme_name"],
                "variation_title": v["variation_title"],
                "cover_title": v["cover_title"],
                "cover_subtitle": v["cover_subtitle"],
                "spreads": [
                    [
                        len(sp["left_page"]["slots"]) + len(sp["right_page"]["slots"]),
                        [
                            s.get("text_content")
                            for pg in ("left_page", "right_page")
                            for s in sp[pg]["slots"]
                            if s.get("type") == "text"
                        ],
                    ]
                    for sp in v["spreads"]
                ],
            }
            for v in variations
        ]
    return proj


def golden_payload(data):
    return {
        "full_sha256": hashlib.sha256(dump(data).encode()).hexdigest(),
        "projection": project(data),
    }


if __name__ == "__main__":
    payload = golden_payload(build())
    if "--write" in sys.argv:
        GOLDEN_PATH.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
        print(f"wrote {GOLDEN_PATH} ({GOLDEN_PATH.stat().st_size} bytes)")
    else:
        print(payload["full_sha256"])
