"""
The StorageBackend contract, asserted identically against every backend.

This is the highest-leverage test in the storage layer: it runs the same body
against LocalDiskBackend and against S3Backend (on moto), so the two cannot
drift. Any future backend gets the whole suite by adding one fixture param.

The S3 cases are what catch the differences that are genuinely dangerous —
prefix boundaries, key validation with no filesystem to fall back on, and
url_for() staying a durable relative path rather than a signed URL.
"""

import threading

import pytest

boto3 = pytest.importorskip("boto3")
moto = pytest.importorskip("moto")

from app.storage import LocalDiskBackend, storage_key  # noqa: E402
from app.storage.objcache import LocalObjectCache  # noqa: E402
from app.storage.s3 import S3Backend  # noqa: E402

BUCKET = "pixovo-test-bucket"
REGION = "us-east-1"


@pytest.fixture
def local_backend(tmp_path):
    return LocalDiskBackend(root=tmp_path / "uploads")


@pytest.fixture
def s3_backend(tmp_path):
    with moto.mock_aws():
        client = boto3.client("s3", region_name=REGION)
        client.create_bucket(Bucket=BUCKET)
        cache = LocalObjectCache(
            root=tmp_path / "objcache",
            max_bytes=64 * 1024 * 1024,
            ttl_seconds=3600,
        )
        yield S3Backend(
            bucket=BUCKET,
            region=REGION,
            cache=cache,
            key_prefix="testpfx",
        )


@pytest.fixture(params=["local", "s3"])
def backend(request):
    """Every test below runs twice — once per backend."""
    return request.getfixturevalue(f"{request.param}_backend")


# --------------------------------------------------------------- key validity


@pytest.mark.parametrize("bad_key", [
    "../../etc/passwd",
    "/absolute/path.jpg",
    "originals/../../escape.jpg",
    "thumbnails/sess/../../../x.jpg",
    "",
])
def test_traversal_keys_are_rejected_by_every_backend(backend, bad_key):
    """
    Keys embed client-minted photo ids.

    For S3 this is the only guard that exists — there is no filesystem to
    resolve against, and "originals/s/../../x.jpg" is a legal S3 key that simply
    is not the one we intended to write.
    """
    with pytest.raises(ValueError):
        backend.put_stream_iter(bad_key, [b"x"])


def test_concurrent_writes_into_one_new_session_directory(backend, tmp_path):
    """
    Regression: ingest uploads a whole chunk concurrently into a session
    directory that does not exist yet.

    On Windows, Path.resolve() intermittently returns the extended-length
    '\\\\?\\' form while a parent directory is being created by another thread.
    Comparing that against an unprefixed root made LocalDiskBackend's
    containment check reject legitimate keys as traversal attempts — only under
    concurrency, and only some of the time.
    """
    src = tmp_path / "staged.jpg"
    src.write_bytes(b"x" * 64)

    errors = []

    def upload(i):
        try:
            backend.put_path(f"thumbnails/sess_race/px_{i}_thumb.jpg", str(src))
        except Exception as exc:  # pragma: no cover - surfaced by the assert
            errors.append(repr(exc))

    threads = [threading.Thread(target=upload, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    for i in range(12):
        assert backend.exists(f"thumbnails/sess_race/px_{i}_thumb.jpg")


def test_url_and_key_round_trip(backend):
    key = storage_key("originals", "sess_x", "px_1_orig.jpg")
    url = backend.url_for(key)

    # Durable and relative on BOTH backends. If S3 ever returns a signed URL
    # here it lands in photos.url and jobs.variations_json and expires there.
    assert url == "/uploads/originals/sess_x/px_1_orig.jpg"
    assert "X-Amz-Signature" not in url
    assert backend.key_for_url(url) == key
    assert backend.key_for_url("https://example.com/other.jpg") is None


# ------------------------------------------------------------ write then read


def test_put_stream_iter_round_trip(backend):
    key = storage_key("originals", "sess_a", "px_1_orig.jpg")
    assert not backend.exists(key)

    backend.put_stream_iter(key, [b"abc", b"def"])

    assert backend.exists(key)
    info = backend.head(key)
    assert info is not None and info.size == 6
    with open(backend.get_path(key), "rb") as fh:
        assert fh.read() == b"abcdef"


def test_put_path_round_trip(backend, tmp_path):
    src = tmp_path / "staged.jpg"
    src.write_bytes(b"y" * 128)

    key = storage_key("thumbnails", "sess_a", "px_2_thumb.jpg")
    url = backend.put_path(key, str(src))

    assert url == backend.url_for(key)
    assert backend.head(key).size == 128


def test_head_and_get_path_are_none_when_absent(backend):
    key = storage_key("originals", "sess_a", "missing_orig.jpg")
    assert backend.head(key) is None
    assert backend.get_path(key) is None
    assert backend.exists(key) is False


def test_put_stream_iter_cleans_up_on_failure(backend):
    """A raising iterator must not leave a partial object behind."""
    key = storage_key("originals", "sess_a", "px_1_orig.jpg")

    def _boom():
        yield b"partial data"
        raise RuntimeError("upload aborted")

    with pytest.raises(RuntimeError):
        backend.put_stream_iter(key, _boom())

    assert not backend.exists(key)


def test_open_local_yields_a_readable_path(backend):
    key = storage_key("originals", "sess_a", "px_3_orig.jpg")
    backend.put_stream_iter(key, [b"payload"])

    with backend.open_local(key) as path:
        assert path is not None
        with open(path, "rb") as fh:
            assert fh.read() == b"payload"


# ------------------------------------------------------------------- deletion


def test_delete_prefix_does_not_cross_a_session_boundary(backend):
    """
    'originals/sess_a' must not match 'originals/sess_abc'.

    LocalDiskBackend is directory-based and immune to this. S3 prefixes are
    plain string matches, so without a trailing slash retention on one session
    would silently delete another session's originals.
    """
    for i in range(3):
        backend.put_stream_iter(f"originals/sess_a/px_{i}.jpg", [b"x" * 10])
    backend.put_stream_iter("originals/sess_abc/px_9.jpg", [b"x" * 10])
    backend.put_stream_iter("originals/sess_b/px_9.jpg", [b"x" * 10])

    removed = backend.delete_prefix("originals/sess_a")

    assert removed == 3
    assert not backend.exists("originals/sess_a/px_0.jpg")
    assert backend.exists("originals/sess_abc/px_9.jpg"), "deleted a prefix-sibling session"
    assert backend.exists("originals/sess_b/px_9.jpg"), "deleted the wrong session"


def test_delete_is_idempotent(backend):
    key = storage_key("originals", "sess_a", "px_1_orig.jpg")
    backend.put_stream_iter(key, [b"x"])
    backend.delete(key)
    backend.delete(key)  # must not raise
    assert not backend.exists(key)


def test_total_bytes_sums_under_a_prefix(backend):
    backend.put_stream_iter("originals/sess_a/px_0.jpg", [b"x" * 10])
    backend.put_stream_iter("originals/sess_a/px_1.jpg", [b"x" * 15])
    backend.put_stream_iter("originals/sess_b/px_0.jpg", [b"x" * 99])

    assert backend.total_bytes("originals/sess_a") == 25


# ------------------------------------------------- S3-only: presign behaviour


def test_local_backend_declares_no_presign_capability(local_backend):
    """The capability probe is what makes the presign endpoint fall back to proxy."""
    assert local_backend.supports_presigned_upload is False
    assert local_backend.supports_presigned_get is False
    assert local_backend.enforces_upload_size is False


def test_s3_presigned_post_carries_a_content_length_range(s3_backend):
    presigned = s3_backend.presigned_upload(
        storage_key("originals", "sess_a", "px_1_orig.jpg"),
        content_type="image/jpeg",
        max_bytes=20 * 1024 * 1024,
        expires_in=900,
    )

    assert presigned.mode == "s3_post"
    assert presigned.max_bytes == 20 * 1024 * 1024
    assert s3_backend.enforces_upload_size is True
    # The policy is what actually enforces the ceiling; the field is only the
    # promise that it does.
    assert "policy" in presigned.fields
    assert presigned.fields["Content-Type"] == "image/jpeg"


def test_s3_presigned_put_admits_it_cannot_enforce_size(tmp_path):
    """
    A presigned PUT's Content-Length is client-supplied, so max_bytes must be
    None — that is the signal telling the confirm path it is the only defence.
    """
    with moto.mock_aws():
        boto3.client("s3", region_name=REGION).create_bucket(Bucket=BUCKET)
        backend = S3Backend(bucket=BUCKET, region=REGION, presign_mode="put",
                            cache=LocalObjectCache(tmp_path / "c", 1 << 20, 60))

        presigned = backend.presigned_upload(
            storage_key("originals", "sess_a", "px_1_orig.jpg"),
            content_type="image/jpeg", max_bytes=20 * 1024 * 1024, expires_in=900,
        )

    assert presigned.mode == "s3_put"
    assert presigned.max_bytes is None
    assert backend.enforces_upload_size is False


def test_s3_presigned_get_is_signed_and_scoped(s3_backend):
    key = storage_key("thumbnails", "sess_a", "px_1_thumb.jpg")
    s3_backend.put_stream_iter(key, [b"x"])

    url = s3_backend.presigned_get_url(key, expires_in=3600)

    assert "X-Amz-Signature" in url
    assert "px_1_thumb.jpg" in url
    # The configured key prefix must be part of the signed object path.
    assert "testpfx" in url


def test_s3_key_prefix_isolates_environments(s3_backend):
    """A shared bucket must not let staging and prod collide."""
    key = storage_key("originals", "sess_a", "px_1_orig.jpg")
    s3_backend.put_stream_iter(key, [b"x" * 5])

    listed = s3_backend.client.list_objects_v2(Bucket=BUCKET)["Contents"]
    assert [o["Key"] for o in listed] == ["testpfx/originals/sess_a/px_1_orig.jpg"]


def test_s3_get_path_is_cached_and_single_flight(s3_backend):
    """
    A 40-spread export resolves ~80 originals from a thread pool. Without
    single-flight each one downloads once per concurrent caller.
    """
    key = storage_key("originals", "sess_a", "px_1_orig.jpg")
    s3_backend.put_stream_iter(key, [b"z" * 2048])

    calls = []
    real_download = s3_backend.client.download_file

    def counting_download(*args, **kwargs):
        calls.append(1)
        return real_download(*args, **kwargs)

    s3_backend.client.download_file = counting_download

    paths, errors = [], []

    def worker():
        try:
            paths.append(s3_backend.get_path(key))
        except Exception as exc:  # pragma: no cover - surfaced by the assert
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    assert len(set(paths)) == 1, "cache handed out different paths for one object"
    assert len(calls) == 1, f"downloaded {len(calls)} times, expected 1"
