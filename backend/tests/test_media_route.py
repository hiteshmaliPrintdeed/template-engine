"""
Media access in both storage modes.

The invariant: a photo URL is the same durable "/uploads/{key}" string whichever
backend is live. Local mode serves the bytes from the static mount; S3 mode
redirects to a freshly-signed GET. Nothing persisted can tell the difference,
which is what makes switching modes — in either direction — need no data
migration.
"""

import pytest

boto3 = pytest.importorskip("boto3")
moto = pytest.importorskip("moto")

BUCKET = "pixovo-media-test"
REGION = "us-east-1"


def test_local_mode_serves_bytes_from_the_static_mount(client):
    from app.config import STORAGE, storage_key

    key = storage_key("thumbnails", "sess_media", "px_m1_thumb.jpg")
    STORAGE.put_stream_iter(key, [b"JPEGBYTES"])

    res = client.get(STORAGE.url_for(key))

    assert res.status_code == 200
    assert res.content == b"JPEGBYTES"


def test_local_mode_url_is_relative_and_unsigned(client):
    from app.config import STORAGE, storage_key

    url = STORAGE.url_for(storage_key("thumbnails", "sess_media", "px_m1_thumb.jpg"))

    assert url == "/uploads/thumbnails/sess_media/px_m1_thumb.jpg"
    assert "X-Amz" not in url


# --------------------------------------------------------------- S3 media mode


def test_s3_mode_redirects_to_a_signed_url(s3_app):
    client, storage = s3_app
    from app.storage import storage_key

    key = storage_key("thumbnails", "sess_media", "px_m1_thumb.jpg")
    storage.put_stream_iter(key, [b"JPEGBYTES"])

    res = client.get(f"/uploads/{key}", follow_redirects=False)

    assert res.status_code == 307
    location = res.headers["location"]
    assert "X-Amz-Signature" in location, location
    assert "px_m1_thumb.jpg" in location
    # Cached for less than the signature's own lifetime, so a cached redirect
    # can never outlive the URL it points at.
    assert "private" in res.headers.get("cache-control", "")


def test_s3_mode_rejects_a_traversal_key(s3_app):
    """Without the guard this route is a read primitive over the whole bucket."""
    client, _ = s3_app

    res = client.get("/uploads/../../etc/passwd", follow_redirects=False)

    assert res.status_code in (400, 404), res.text


def test_s3_mode_404s_a_missing_object(s3_app):
    """
    A redirect to a signed URL for an object that does not exist would give the
    browser an opaque S3 error instead of a 404.
    """
    client, _ = s3_app

    res = client.get("/uploads/thumbnails/sess_media/nope_thumb.jpg", follow_redirects=False)

    assert res.status_code == 404


def test_s3_mode_serves_exports_through_their_own_route(s3_app):
    client, storage = s3_app
    from app.storage import storage_key

    key = storage_key("exports", "sess_media", "print_var_1_abc.pdf")
    storage.put_stream_iter(key, [b"%PDF-1.4"], "application/pdf")

    res = client.get("/exports/sess_media/print_var_1_abc.pdf", follow_redirects=False)

    assert res.status_code == 307
    assert "print_var_1_abc.pdf" in res.headers["location"]
