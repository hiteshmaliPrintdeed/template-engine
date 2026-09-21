"""
Browser-direct upload: presign authorisation and confirm accounting.

A presigned upload bypasses FastAPI entirely, so the presign call is the only
trust boundary and confirm's head_object is the only accounting authority. These
tests are about exactly those two properties — that nothing in a request can
influence the key it gets signed for, and that a client cannot talk the server
into believing an upload happened.
"""

import json

import pytest

boto3 = pytest.importorskip("boto3")
moto = pytest.importorskip("moto")

from tests.conftest import make_thumbnail_bytes  # noqa: E402

BUCKET = "pixovo-direct-test"
REGION = "us-east-1"


def ingest_one(client, session_id, photo_id, original_size_bytes=8_000_000):
    """Put one photo through ingest so it exists in the photos table."""
    meta = [{
        "photo_id": photo_id,
        "filename": f"{photo_id}.jpg",
        "original_width": 4000,
        "original_height": 3000,
        "aspect_ratio": 1.333,
        "orientation": "LANDSCAPE",
        "timestamp": "2026-08-01T10:00:00.000Z",
        "timestamp_epoch": 1_785_535_200,
        "original_size_bytes": original_size_bytes,
        "thumbnail_size_bytes": 30_000,
    }]
    return client.post(
        "/api/photobook/ingest",
        data={
            "session_id": session_id,
            "chunk_index": "0",
            "chunk_count": "1",
            "metadata_json": json.dumps(meta),
        },
        files=[("thumbnails", (f"{photo_id}_thumb.jpg",
                               make_thumbnail_bytes(abs(hash(photo_id)) % 9973),
                               "image/jpeg"))],
    )


@pytest.fixture
def s3_direct(monkeypatch, tmp_path):
    """
    Put the running app into S3 + direct-upload mode.

    Patches app.main (and app.engine.pdf_exporter), NOT app.config: both modules
    do `from app.config import STORAGE`, which binds the name at import time.
    Patching app.config.STORAGE alone changes nothing the handlers can see and
    produces tests that pass without exercising any S3 code.
    """
    from app.storage.objcache import LocalObjectCache
    from app.storage.s3 import S3Backend
    import app.main as main
    import app.engine.pdf_exporter as pdf_exporter

    with moto.mock_aws():
        boto3.client("s3", region_name=REGION).create_bucket(Bucket=BUCKET)
        backend = S3Backend(
            bucket=BUCKET,
            region=REGION,
            cache=LocalObjectCache(tmp_path / "objcache", 32 << 20, 600),
        )
        monkeypatch.setattr(main, "STORAGE", backend)
        monkeypatch.setattr(pdf_exporter, "STORAGE", backend)
        monkeypatch.setattr(main, "DIRECT_UPLOAD_ENABLED", True)
        yield backend


@pytest.fixture
def session_with_photo(client):
    """A live session containing one ingested photo."""
    sess = client.post("/api/sessions", json={"expected_photo_count": 1}).json()["session_id"]
    assert ingest_one(client, sess, "px_direct1").status_code == 200
    return sess


# ------------------------------------------------------------------- fallback


def test_presign_answers_proxy_when_direct_upload_is_disabled(client, session_with_photo):
    """
    The default. PIXOVO_DIRECT_UPLOAD=0 must send every client back to the
    existing multipart endpoint — that is the instant rollback.
    """
    res = client.post("/api/uploads/presign", json={
        "session_id": session_with_photo, "photo_id": "px_direct1",
    })

    assert res.status_code == 200
    body = res.json()
    assert body["mode"] == "proxy"
    assert body["url"].startswith("/api/upload-originals?")
    assert session_with_photo in body["url"]
    assert body["confirm_required"] is False


def test_presign_answers_proxy_when_backend_cannot_presign(client, session_with_photo, monkeypatch):
    """Local disk mode must degrade, not error."""
    import app.main as main
    monkeypatch.setattr(main, "DIRECT_UPLOAD_ENABLED", True)
    # STORAGE is still LocalDiskBackend, whose capability flags are False.
    res = client.post("/api/uploads/presign", json={
        "session_id": session_with_photo, "photo_id": "px_direct1",
    })
    assert res.json()["mode"] == "proxy"


# -------------------------------------------------------------- authorisation


def test_presign_rejects_an_unknown_session(client):
    res = client.post("/api/uploads/presign", json={
        "session_id": "sess_doesnotexist", "photo_id": "px_direct1",
    })
    assert res.status_code == 404


def test_presign_rejects_an_unknown_photo(client, session_with_photo):
    res = client.post("/api/uploads/presign", json={
        "session_id": session_with_photo, "photo_id": "px_nosuchphoto",
    })
    assert res.status_code == 404


def test_presign_rejects_a_cross_session_photo(client, session_with_photo):
    """
    The check /api/upload-originals does while streaming, moved to presign —
    because after presign there is no server-side moment left to do it.
    """
    other = client.post("/api/sessions", json={"expected_photo_count": 1}).json()["session_id"]

    res = client.post("/api/uploads/presign", json={
        "session_id": other, "photo_id": "px_direct1",
    })

    assert res.status_code == 403


@pytest.mark.parametrize("bad_id", [
    "../../etc/passwd",
    "px/../../escape",
    "px_1;rm -rf /",
    "",
    "p" * 200,
])
def test_presign_rejects_malformed_identifiers(client, session_with_photo, bad_id):
    res = client.post("/api/uploads/presign", json={
        "session_id": session_with_photo, "photo_id": bad_id,
    })
    assert res.status_code in (400, 404), res.text


def test_presign_rejects_a_disallowed_content_type(client, s3_direct, session_with_photo):
    res = client.post("/api/uploads/presign", json={
        "session_id": session_with_photo, "photo_id": "px_direct1",
        "content_type": "text/html",
    })
    assert res.status_code == 415


def test_presign_rejects_an_oversize_declared_file(client, s3_direct, session_with_photo):
    from app.config import MAX_FILE_SIZE
    res = client.post("/api/uploads/presign", json={
        "session_id": session_with_photo, "photo_id": "px_direct1",
        "declared_bytes": MAX_FILE_SIZE + 1,
    })
    assert res.status_code == 413


def test_presign_rejects_an_oversize_file_in_proxy_mode_too(client, session_with_photo):
    """
    The per-file ceiling is independent of how the bytes would travel.

    Proxy mode enforces it mid-copy anyway, but only after the client has spent
    the entire upload. Since the client's response to a 413 is to discard the
    file either way, refusing at presign saves 20MB of pointless transfer.
    """
    from app.config import MAX_FILE_SIZE

    res = client.post("/api/uploads/presign", json={
        "session_id": session_with_photo, "photo_id": "px_direct1",
        "declared_bytes": MAX_FILE_SIZE + 1,
    })

    assert res.status_code == 413, (
        f"proxy mode accepted an oversize file: {res.status_code} {res.text}"
    )


# ------------------------------------------------------- key is server-chosen


@pytest.mark.parametrize("hostile", [
    "../../evil",
    "x/../../../etc/passwd",
    "evil.html",
    "..\\..\\windows\\system32",
])
def test_no_request_field_can_influence_the_signed_key(
    client, s3_direct, session_with_photo, hostile
):
    """
    The single most important property here. The key is built from the session
    id, the photo id and the filename recorded at INGEST. There is no `key`
    parameter, and a hostile content_type or filename-shaped value in any field
    must not move the object.
    """
    from app.config import storage_key

    expected = storage_key("originals", session_with_photo, "px_direct1_orig.jpg")

    res = client.post("/api/uploads/presign", json={
        "session_id": session_with_photo,
        "photo_id": "px_direct1",
        # Not a field the endpoint reads — included precisely to prove that.
        "key": hostile,
        "filename": hostile,
        "content_type": "image/jpeg",
    })

    assert res.status_code == 200
    assert res.json()["key"] == expected


def test_presigned_post_policy_carries_the_size_ceiling(client, s3_direct, session_with_photo):
    from app.config import MAX_FILE_SIZE

    body = client.post("/api/uploads/presign", json={
        "session_id": session_with_photo, "photo_id": "px_direct1",
    }).json()

    assert body["mode"] == "s3_post"
    assert body["max_bytes"] == MAX_FILE_SIZE
    assert body["size_enforced"] is True
    assert body["confirm_required"] is True
    assert "policy" in body["fields"]
    assert body["expires_in"] > 0


# ---------------------------------------------------------- confirm accounting


def test_confirm_refuses_when_no_object_landed(client, s3_direct, session_with_photo, store):
    """
    A client that claims success without uploading must not be believed: the
    export gate depends on original_synced, so a false confirm would ship
    thumbnails into a 300 DPI print.
    """
    client.post("/api/uploads/presign", json={
        "session_id": session_with_photo, "photo_id": "px_direct1",
    })

    res = client.post("/api/uploads/confirm", json={
        "session_id": session_with_photo, "photo_id": "px_direct1",
    })

    assert res.status_code == 409
    assert res.json()["detail"]["error"] == "object_missing"

    photo = store.get_photo("px_direct1")
    assert photo.original_synced is False
    assert int(store.get_session(session_with_photo)["total_bytes"] or 0) == 0


def test_confirm_counts_verified_bytes_once(client, s3_direct, session_with_photo, store):
    """
    Replay safety. The client confirms on reconnect, on `online`, and on every
    resume; each retry must be a no-op rather than another debit against the
    session quota.
    """
    from app.config import storage_key

    body = client.post("/api/uploads/presign", json={
        "session_id": session_with_photo, "photo_id": "px_direct1",
    }).json()

    # Simulate the browser's direct upload.
    payload = b"x" * 4096
    s3_direct.put_stream_iter(body["key"], [payload])

    first = client.post("/api/uploads/confirm", json={
        "session_id": session_with_photo, "photo_id": "px_direct1",
    })
    assert first.status_code == 200
    assert first.json()["synced"] is True
    assert first.json()["original_url"] == f"/uploads/{body['key']}"

    after_first = int(store.get_session(session_with_photo)["total_bytes"] or 0)
    assert after_first == len(payload)

    # Three replays.
    for _ in range(3):
        again = client.post("/api/uploads/confirm", json={
            "session_id": session_with_photo, "photo_id": "px_direct1",
        })
        assert again.status_code == 200

    assert int(store.get_session(session_with_photo)["total_bytes"] or 0) == after_first

    photo = store.get_photo("px_direct1")
    assert photo.original_synced is True
    assert photo.original_key == storage_key("originals", session_with_photo, "px_direct1_orig.jpg")
    assert store.get_original_bytes("px_direct1") == len(payload)


def test_confirm_does_not_trust_a_client_reported_size(client, s3_direct, session_with_photo, store):
    """The accounted size comes from head_object, not from the request."""
    body = client.post("/api/uploads/presign", json={
        "session_id": session_with_photo, "photo_id": "px_direct1",
        "declared_bytes": 19_000_000,          # a big lie
    }).json()

    s3_direct.put_stream_iter(body["key"], [b"y" * 1234])   # the truth

    client.post("/api/uploads/confirm", json={
        "session_id": session_with_photo, "photo_id": "px_direct1",
        "etag": "0" * 32,                       # also a lie; must not be stored
    })

    assert int(store.get_session(session_with_photo)["total_bytes"] or 0) == 1234

    # original_etag is a server-only column (deliberately not on PhotoMeta), so
    # read it directly rather than through the schema.
    from app.db.session_store import get_db_connection
    stored_etag = get_db_connection().execute(
        "SELECT original_etag FROM photos WHERE id = ?", ("px_direct1",)
    ).fetchone()["original_etag"]
    assert stored_etag != "0" * 32


def test_confirm_deletes_and_refuses_an_oversize_object(
    client, s3_direct, session_with_photo, store, monkeypatch
):
    """
    Reachable when presign_mode is "put", which cannot enforce a size. The
    object must not survive, and must not be counted.
    """
    import app.main as main

    # Presign under the real limit first: with the limit already lowered,
    # presign would reject the declared size and never hand back a key.
    body = client.post("/api/uploads/presign", json={
        "session_id": session_with_photo, "photo_id": "px_direct1",
    }).json()
    s3_direct.put_stream_iter(body["key"], [b"z" * 4096])

    # Now the object in the bucket is over the ceiling, which is exactly the
    # state a presigned PUT can produce since it cannot constrain the size.
    monkeypatch.setattr(main, "MAX_FILE_SIZE", 1024)

    res = client.post("/api/uploads/confirm", json={
        "session_id": session_with_photo, "photo_id": "px_direct1",
    })

    assert res.status_code == 413
    assert res.json()["detail"]["error"] == "too_large"
    assert not s3_direct.exists(body["key"]), "oversize object was left in the bucket"
    assert store.get_photo("px_direct1").original_synced is False
    assert int(store.get_session(session_with_photo)["total_bytes"] or 0) == 0


def test_confirm_rejects_a_cross_session_caller(client, s3_direct, session_with_photo):
    other = client.post("/api/sessions", json={"expected_photo_count": 1}).json()["session_id"]
    res = client.post("/api/uploads/confirm", json={
        "session_id": other, "photo_id": "px_direct1",
    })
    assert res.status_code == 403


def test_confirm_unblocks_the_pdf_export_gate(client, s3_direct, session_with_photo, store):
    """
    Ties the new path back to the existing guarantee: export stays blocked until
    a real original is verified, and then proceeds.
    """
    photos = store.get_session_photos(session_with_photo)
    assert photos, "ingest produced no surviving photo"
    pid = photos[0].id

    from app.schemas.photobook import PhotobookVariation, SinglePage, SpreadPair, TemplateSlot

    slot = TemplateSlot(
        id="slot_0", type="photo", x_pct=0.0, y_pct=0.0, w_pct=50.0, h_pct=50.0,
        photo_id=pid, photo_url=photos[0].url,
    )
    page = SinglePage(page_number=1, background_color="#FFF", text_color="#000", slots=[slot])
    empty = SinglePage(page_number=2, background_color="#FFF", text_color="#000", slots=[])
    variation = PhotobookVariation(
        id="var_1", variation_title="Direct upload proof", theme_name="Warm",
        cover_title="C", cover_subtitle="S", cover_image_url=photos[0].url,
        base_color="#FFF", accent_color="#000", text_color="#000",
        spreads=[SpreadPair(spread_index=1, left_page=page, right_page=empty)],
    )
    payload = {
        "variation": json.loads(variation.model_dump_json()),
        "session_id": session_with_photo,
    }

    blocked = client.post("/api/export-pdf", json=payload)
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["error"] == "originals_pending"

    body = client.post("/api/uploads/presign", json={
        "session_id": session_with_photo, "photo_id": pid,
    }).json()
    s3_direct.put_stream_iter(body["key"], [make_thumbnail_bytes(7)])
    assert client.post("/api/uploads/confirm", json={
        "session_id": session_with_photo, "photo_id": pid,
    }).status_code == 200

    allowed = client.post("/api/export-pdf", json=payload)
    assert allowed.status_code == 200, allowed.text


# ------------------------------------------------------------------ rate limit


def test_presign_rate_limits_a_hot_session(client, s3_direct, session_with_photo, monkeypatch):
    import app.main as main
    from app.upload_policy import RateLimiter
    monkeypatch.setattr(main, "_PRESIGN_LIMITER", RateLimiter(per_minute=3))

    codes = [
        client.post("/api/uploads/presign", json={
            "session_id": session_with_photo, "photo_id": "px_direct1",
        }).status_code
        for _ in range(5)
    ]

    assert codes[:3] == [200, 200, 200]
    assert 429 in codes[3:]
