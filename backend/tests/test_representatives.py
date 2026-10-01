"""
Representative-photo selection: which few photos Gemini is shown per segment.
All local -- no network, and image loading is injected.
"""

from contextlib import contextmanager

import pytest

import app.engine.representatives as reps
from app.engine.representatives import VISION_MAX_SIDE_PX, representative_image_bytes, select_representatives
from app.schemas.photobook import PhotoMeta

FAR_A = "0000000000000000"
FAR_B = "ffffffffffffffff"          # 64 bits from FAR_A
MID = "00000000ffffffff"            # 32 bits from both


def photo(pid, hero=80.0, shell=None, core=None, ts=0.0, blur=None, thumb=True):
    return PhotoMeta(
        id=pid,
        filename=f"{pid}.jpg",
        url=f"/u/{pid}.jpg",
        hero_score=hero,
        shell_phash=shell or "",
        core_phash=core or shell or "",
        timestamp_epoch=ts,
        blur_score=blur,
        thumbnail_key=f"thumbnails/sess/{pid}_thumb.jpg" if thumb else None,
    )


def ok_loader(p):
    return b"jpeg:" + p.id.encode()


def ids(picks):
    return [p.id for p, _ in picks]


def test_deterministic():
    photos = [photo(f"p{i}", hero=50 + i % 7, shell=f"{i:016x}") for i in range(20)]
    assert ids(select_representatives(photos, 3, ok_loader)) == ids(select_representatives(list(reversed(photos)), 3, ok_loader))


def test_first_pick_is_highest_hero():
    photos = [photo("low", 40, FAR_A), photo("top", 95, FAR_B), photo("mid", 70, MID)]
    assert ids(select_representatives(photos, 1, ok_loader)) == ["top"]


def test_near_duplicates_are_skipped_while_alternatives_exist():
    # The score alone would prefer "burst" (0.6*8/64 + 0.4*0.95 = 0.455) over
    # "other" (0.6*12/64 + 0.4*0.20 = 0.19); only the near-duplicate rule
    # (distance < 10) keeps a second copy of the same moment out.
    photos = [
        photo("hero", 99, FAR_A),
        photo("burst", 95, "00000000000000ff"),   # 8 bits from hero: same moment
        photo("other", 20, "0000000000000fff"),   # 12 bits: a different scene
    ]
    assert ids(select_representatives(photos, 2, ok_loader)) == ["hero", "other"]


def test_near_duplicate_is_used_when_nothing_else_exists():
    photos = [photo("hero", 99, FAR_A), photo("burst", 95, "00000000000000ff")]
    assert ids(select_representatives(photos, 2, ok_loader)) == ["hero", "burst"]


def test_quality_decides_between_equally_different_photos():
    photos = [photo("first", 95, FAR_A), photo("weak", 40, FAR_B), photo("strong", 90, FAR_B)]
    assert ids(select_representatives(photos, 2, ok_loader)) == ["first", "strong"]


def test_equal_scores_spread_across_the_time_range():
    # No hashes (maximally distant) and equal quality: only time separates them.
    base = 1_785_500_000.0
    photos = [photo("a0", 80, ts=base), photo("a1", 80, ts=base + 10), photo("a2", 80, ts=base + 20),
              photo("m0", 80, ts=base + 5000), photo("z0", 80, ts=base + 9000)]
    picked = ids(select_representatives(photos, 3, ok_loader))
    assert picked[0] == "a0"
    assert set(picked[1:]) == {"m0", "z0"}, f"picks bunched in one burst: {picked}"


def test_unreadable_thumbnail_is_replaced_by_next_best():
    photos = [photo("broken", 95, FAR_A), photo("good1", 90, FAR_B), photo("good2", 85, MID)]
    picks = select_representatives(photos, 2, lambda p: None if p.id == "broken" else ok_loader(p))
    assert ids(picks) == ["good1", "good2"]


def test_photos_without_thumbnails_are_never_picked():
    photos = [photo("nothumb", 99, FAR_A, thumb=False), photo("thumb", 10, FAR_B)]
    assert ids(select_representatives(photos, 3, ok_loader)) == ["thumb"]


def test_fewer_photos_than_k():
    assert len(select_representatives([photo("only", 80, FAR_A)], 3, ok_loader)) == 1
    assert select_representatives([], 3, ok_loader) == []


def test_blurriest_third_is_dropped_when_enough_remain():
    photos = [photo(f"p{i}", hero=99 if i < 3 else 50, shell=f"{i * 0x1111111111111:016x}"[-16:], blur=i)
              for i in range(9)]
    picked = ids(select_representatives(photos, 3, ok_loader))
    assert not {"p0", "p1", "p2"} & set(picked), f"blurriest photos shown to Gemini: {picked}"


def test_image_bytes_are_small_jpeg(tmp_path, monkeypatch):
    from PIL import Image
    import io

    src = tmp_path / "t.jpg"
    Image.new("RGB", (512, 400), (120, 80, 40)).save(src, format="JPEG")

    class FakeStorage:
        @contextmanager
        def open_local(self, key):
            yield str(src) if key == "thumbnails/sess/x_thumb.jpg" else None

    monkeypatch.setattr(reps, "STORAGE", FakeStorage())
    data = representative_image_bytes(photo("x"))
    img = Image.open(io.BytesIO(data))
    assert img.format == "JPEG"
    assert max(img.size) <= VISION_MAX_SIDE_PX
    assert representative_image_bytes(photo("missing")) is None
    assert representative_image_bytes(photo("nothumb", thumb=False)) is None
