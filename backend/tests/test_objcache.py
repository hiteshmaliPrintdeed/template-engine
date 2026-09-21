"""
The bounded local object cache.

In S3 mode this is the only thing that can still fill the disk: get_path()
materialises remote bytes locally, and a 40-spread PDF export resolves ~80
originals at up to 20 MB each. The uploads watermark is a database counter and
does not see these files at all, so the cache has to police itself.
"""

import os
import threading
import time

from app.storage.objcache import LocalObjectCache, ScratchDir


def writer(payload: bytes):
    """A download callable that writes fixed content to the given path."""
    def _download(dest: str) -> None:
        with open(dest, "wb") as fh:
            fh.write(payload)
    return _download


def test_fetch_downloads_once_then_serves_from_cache(tmp_path):
    cache = LocalObjectCache(tmp_path, max_bytes=1 << 20, ttl_seconds=600)
    calls = []

    def counting(dest):
        calls.append(1)
        writer(b"x" * 100)(dest)

    first = cache.fetch("originals/s/a.jpg", "etag1", counting)
    second = cache.fetch("originals/s/a.jpg", "etag1", counting)

    assert first == second
    assert len(calls) == 1
    with open(first, "rb") as fh:
        assert fh.read() == b"x" * 100


def test_a_new_etag_invalidates_the_cached_bytes(tmp_path):
    """
    A re-uploaded original must never serve its predecessor's bytes — these
    files go into a PDF someone pays to print.
    """
    cache = LocalObjectCache(tmp_path, max_bytes=1 << 20, ttl_seconds=600)

    old = cache.fetch("originals/s/a.jpg", "etag1", writer(b"OLD"))
    new = cache.fetch("originals/s/a.jpg", "etag2", writer(b"NEW"))

    assert old != new
    with open(new, "rb") as fh:
        assert fh.read() == b"NEW"


def test_concurrent_fetches_of_one_object_download_once(tmp_path):
    """
    Single-flight. An export resolves photos from a thread pool, and two users
    exporting the same session would otherwise each pull every original.
    """
    cache = LocalObjectCache(tmp_path, max_bytes=1 << 20, ttl_seconds=600)
    calls = []
    lock = threading.Lock()

    def slow_download(dest):
        with lock:
            calls.append(1)
        time.sleep(0.05)          # widen the window the race needs
        writer(b"y" * 512)(dest)

    results, errors = [], []

    def worker():
        try:
            results.append(cache.fetch("originals/s/big.jpg", "etagX", slow_download))
        except Exception as exc:  # pragma: no cover - surfaced by the assert
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    assert len(set(results)) == 1
    assert len(calls) == 1, f"downloaded {len(calls)} times"


def test_partial_downloads_are_never_observable(tmp_path):
    """
    Bytes are published with os.replace, so a concurrent is_file() check can
    never see a half-written file and hand it to reportlab.
    """
    cache = LocalObjectCache(tmp_path, max_bytes=1 << 20, ttl_seconds=600)
    seen = []

    def failing_download(dest):
        with open(dest, "wb") as fh:
            fh.write(b"half")
        seen.append(dest)
        raise RuntimeError("connection reset")

    try:
        cache.fetch("originals/s/a.jpg", "etag1", failing_download)
    except RuntimeError:
        pass

    assert seen, "download was never attempted"
    assert not os.path.exists(seen[0]), ".part file was left behind"
    assert not cache._slot("originals/s/a.jpg", "etag1").exists(), \
        "a failed download was published to the cache slot"


def test_lru_eviction_respects_the_byte_budget(tmp_path):
    cache = LocalObjectCache(tmp_path, max_bytes=2_500, ttl_seconds=600)

    first = cache.fetch("originals/s/a.jpg", "e1", writer(b"a" * 1000))
    time.sleep(0.02)
    cache.fetch("originals/s/b.jpg", "e2", writer(b"b" * 1000))
    time.sleep(0.02)
    cache.fetch("originals/s/c.jpg", "e3", writer(b"c" * 1000))

    # 3000 bytes over a 2500 budget, so the least recently used goes.
    assert cache.total_bytes() <= 2_500
    assert not os.path.exists(first), "LRU kept the oldest entry"


def test_ttl_eviction_drops_stale_entries(tmp_path):
    cache = LocalObjectCache(tmp_path, max_bytes=1 << 20, ttl_seconds=1)
    path = cache.fetch("originals/s/a.jpg", "e1", writer(b"z" * 100))

    # Backdate past the TTL rather than sleeping through it.
    stale = time.time() - 10
    os.utime(path, (stale, stale))
    cache.evict()

    assert not os.path.exists(path)


def test_invalidate_prefix_drops_one_session(tmp_path):
    """Retention deletes a session by prefix; its cached bytes must go too."""
    cache = LocalObjectCache(tmp_path, max_bytes=1 << 20, ttl_seconds=600)

    a = cache.fetch("originals/sess_a/1.jpg", "e1", writer(b"a" * 10))
    cache.record_key("originals/sess_a/1.jpg", "e1")
    b = cache.fetch("originals/sess_b/1.jpg", "e2", writer(b"b" * 10))
    cache.record_key("originals/sess_b/1.jpg", "e2")

    removed = cache.invalidate_prefix("originals/sess_a")

    assert removed == 1
    assert not os.path.exists(a)
    assert os.path.exists(b), "invalidated the wrong session"


def test_sidecars_are_not_counted_against_the_budget(tmp_path):
    cache = LocalObjectCache(tmp_path, max_bytes=1 << 20, ttl_seconds=600)
    cache.fetch("originals/s/a.jpg", "e1", writer(b"x" * 100))
    cache.record_key("originals/s/a.jpg", "e1")

    assert cache.total_bytes() == 100


def test_startup_sweep_clears_orphaned_part_files(tmp_path):
    """A crashed process leaves .part files nothing will ever complete."""
    cache = LocalObjectCache(tmp_path, max_bytes=1 << 20, ttl_seconds=600)
    orphan = tmp_path / "ab" / "deadbeef.jpg.9999.part"
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"incomplete")

    cache.sweep_startup()

    assert not orphan.exists()


# --------------------------------------------------------------------- scratch


def test_scratch_dir_writes_and_cleans_up(tmp_path):
    import io

    with ScratchDir(tmp_path, prefix="ingest-test-") as scratch:
        path = scratch.write(io.BytesIO(b"thumbnail bytes"), "px_1_thumb.jpg")
        assert os.path.isfile(path)
        root = scratch.path

    assert not root.exists(), "scratch directory survived its context"


def test_scratch_dir_ignores_a_directory_in_the_upload_filename(tmp_path):
    """
    The name comes from a client-supplied multipart filename, so it must not be
    able to escape the scratch directory.
    """
    import io

    with ScratchDir(tmp_path) as scratch:
        path = scratch.write(io.BytesIO(b"x"), "../../escape.jpg")
        assert os.path.dirname(os.path.abspath(path)) == str(scratch.path)
        assert os.path.basename(path) == "escape.jpg"
