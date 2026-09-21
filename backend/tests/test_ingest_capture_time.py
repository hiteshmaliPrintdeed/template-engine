"""
Capture-time parity between storage modes.

This is the subtlest thing in the S3 migration and the reason the ingest handler
stages thumbnails locally before uploading them.

Canvas downsampling in the browser strips EXIF, so
filter_engine.extract_5_signal_metadata() falls back to the thumbnail FILE's
mtime for capture time. Ingest therefore stamps each staged thumbnail with the
client-reported timestamp. Lose that stamp and every photo's capture time
becomes "now" — which silently disables DBSCAN event clustering and the
45-minute chapter rule, producing a plausible-looking book with no chronology.

S3 objects have no mtime to stamp. If a future refactor moves the filter pass to
read from storage instead of the staged file, these tests fail.
"""

import json

import pytest

from tests.conftest import make_thumbnail_bytes

# Three photos, deliberately spread across a >45 minute gap so that losing the
# capture time would change the chaptering, not just a stored number.
CAPTURES = [
    ("px_ct1", 1_785_535_200),          # 10:00
    ("px_ct2", 1_785_535_200 + 300),    # 10:05
    ("px_ct3", 1_785_535_200 + 7_200),  # 12:00 — a new chapter
]


def ingest(client, session_id):
    files, meta = [], []
    for n, (pid, epoch) in enumerate(CAPTURES):
        files.append((
            "thumbnails",
            (f"{pid}_thumb.jpg", make_thumbnail_bytes(1000 + n), "image/jpeg"),
        ))
        meta.append({
            "photo_id": pid,
            "filename": f"{pid}.jpg",
            "original_width": 4000,
            "original_height": 3000,
            "aspect_ratio": 1.333,
            "orientation": "LANDSCAPE",
            "timestamp": "2026-08-01T10:00:00.000Z",
            "timestamp_epoch": epoch,
            "original_size_bytes": 8_000_000,
            "thumbnail_size_bytes": 30_000,
        })
    return client.post(
        "/api/photobook/ingest",
        data={
            "session_id": session_id,
            "chunk_index": "0",
            "chunk_count": "1",
            "metadata_json": json.dumps(meta),
        },
        files=files,
    )


def captured_epochs(client, store_module):
    """Ingest into a fresh session and return {photo_id: persisted epoch}."""
    sess = client.post(
        "/api/sessions", json={"expected_photo_count": len(CAPTURES)}
    ).json()["session_id"]
    assert ingest(client, sess).status_code == 200
    return {p.id: p.timestamp_epoch for p in store_module.get_session_photos(sess)}


def test_local_mode_persists_the_client_capture_time(client, store):
    epochs = captured_epochs(client, store)

    assert epochs, "ingest produced no surviving photos"
    for pid, expected in CAPTURES:
        if pid in epochs:
            assert epochs[pid] == pytest.approx(expected, abs=1), (
                f"{pid} lost its capture time: {epochs[pid]} != {expected}"
            )


def test_s3_mode_persists_the_same_capture_time(s3_app):
    """
    The parity gate. Identical input through an S3-backed app must yield
    identical capture times — the thumbnail is staged locally, stamped, and
    filtered from that path, so the mtime fallback still sees a real timestamp.
    """
    s3_client, _ = s3_app
    from app.db.session_store import SessionStore

    epochs = captured_epochs(s3_client, SessionStore)

    assert epochs, "ingest produced no surviving photos in S3 mode"
    for pid, expected in CAPTURES:
        if pid in epochs:
            assert epochs[pid] == pytest.approx(expected, abs=1), (
                f"{pid} lost its capture time in S3 mode: {epochs[pid]} != {expected}"
            )


def test_s3_mode_uploads_thumbnails_and_leaves_no_scratch_behind(s3_app):
    """
    The staged copies are transient. Leaving them would grow the scratch
    directory by a chunk's worth of thumbnails on every request, forever.
    """
    s3_client, backend = s3_app
    from app.config import SCRATCH_DIR

    sess = s3_client.post(
        "/api/sessions", json={"expected_photo_count": len(CAPTURES)}
    ).json()["session_id"]
    assert ingest(s3_client, sess).status_code == 200

    # Thumbnails really are in the bucket, not just on local disk.
    listed = backend.client.list_objects_v2(
        Bucket=backend.bucket, Prefix=f"thumbnails/{sess}/"
    )
    assert listed.get("KeyCount", 0) == len(CAPTURES), listed

    leftovers = [p.name for p in SCRATCH_DIR.glob(f"ingest-{sess}-*")]
    assert not leftovers, f"scratch directories were not cleaned up: {leftovers}"
