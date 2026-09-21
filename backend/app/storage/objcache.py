"""
Bounded local mirror of remote objects.

Why this exists: StorageBackend.get_path() must return a real filesystem path,
because reportlab, PIL and cv2 all read paths rather than streams. For a remote
backend that means materialising bytes locally, and the PDF exporter calls
get_path() once per placed photo — so a single 40-spread export can pull ~80
originals at up to 20 MB each. A naive NamedTemporaryFile(delete=False) leaks
1.6 GB per export and re-downloads everything on the second export of the same
book.

So: a size-bounded, self-evicting, content-addressed cache. Nobody has to
remember to clean up, because nothing here is owned by a caller.
"""

import hashlib
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import BinaryIO, Callable, Dict, Optional

from loguru import logger

_PART_SUFFIX = ".part"
_COPY_CHUNK = 1024 * 1024  # 1 MB — constant memory regardless of file size


class ScratchDir:
    """
    A temporary directory that cleans itself up, for bytes in transit.

    The ingest handler stages thumbnails here so it can stamp each one's mtime
    with the client's reported capture time and run the filter engine against a
    real local path, before handing the file to storage. Going through storage
    first and reading back would cost an upload plus a download per photo on a
    remote backend — 80 round trips per 40-photo chunk.
    """

    def __init__(self, root: Path, prefix: str = "scratch-"):
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        self.path = Path(tempfile.mkdtemp(prefix=prefix, dir=str(root)))

    def write(self, stream: BinaryIO, name: str) -> str:
        """Copy a stream into this directory in fixed chunks. Returns the path."""
        # basename only: `name` comes from a client-supplied upload filename.
        dest = self.path / os.path.basename(name)
        with open(dest, "wb") as fh:
            shutil.copyfileobj(stream, fh, length=_COPY_CHUNK)
        return str(dest)

    def __enter__(self) -> "ScratchDir":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)


class LocalObjectCache:
    """
    Content-addressed local cache of remote objects, keyed by (storage key, etag).

    Keying on the etag as well as the key is what makes it safe to cache bytes
    that back a paid print: a re-uploaded original has a different etag, so it
    lands in a different slot and the stale bytes are never served. Keying on
    the storage key alone would serve the old photo until the TTL expired.
    """

    def __init__(
        self,
        root: Path,
        max_bytes: int,
        ttl_seconds: int,
        min_free_bytes: int = 0,
    ):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_bytes = int(max_bytes)
        self.ttl = int(ttl_seconds)
        self.min_free_bytes = int(min_free_bytes)
        # One lock per in-flight (key, etag) so concurrent readers of the same
        # object download it once. Guarded by _guard, which is only ever held
        # long enough to hand out a lock — never across a download.
        self._locks: Dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    # ------------------------------------------------------------------ paths

    def _slot(self, key: str, etag: Optional[str]) -> Path:
        digest = hashlib.sha256(f"{key}\0{etag or ''}".encode("utf-8")).hexdigest()
        # Two-level fan-out: a flat directory of 20,000 entries is slow to scan
        # on Windows, and eviction scans the whole tree.
        suffix = Path(key).suffix.lower()
        return self.root / digest[:2] / f"{digest}{suffix}"

    def _key_lock(self, token: str) -> threading.Lock:
        with self._guard:
            lock = self._locks.get(token)
            if lock is None:
                lock = threading.Lock()
                self._locks[token] = lock
            return lock

    # ------------------------------------------------------------------ fetch

    def fetch(
        self,
        key: str,
        etag: Optional[str],
        download: Callable[[str], None],
    ) -> str:
        """
        Return a local path holding `key`'s bytes, downloading if necessary.

        `download` is called with a destination path and must write the whole
        object there. It is invoked at most once per (key, etag) across threads.
        """
        slot = self._slot(key, etag)
        if slot.is_file():
            self._touch(slot)
            return str(slot)

        token = f"{key}\0{etag or ''}"
        lock = self._key_lock(token)
        with lock:
            # Re-check: another thread may have completed the download while we
            # waited for the lock. Without this the single-flight is pointless.
            if slot.is_file():
                self._touch(slot)
                return str(slot)

            slot.parent.mkdir(parents=True, exist_ok=True)
            # PID-tagged so two processes sharing a scratch volume cannot write
            # the same partial file.
            part = slot.with_name(f"{slot.name}.{os.getpid()}{_PART_SUFFIX}")
            try:
                download(str(part))
                # Atomic publish: a partially-downloaded file is never
                # observable under `slot`, which is what makes a concurrent
                # is_file() check above trustworthy.
                os.replace(part, slot)
            finally:
                Path(part).unlink(missing_ok=True)

        with self._guard:
            self._locks.pop(token, None)

        self.evict()
        return str(slot)

    @staticmethod
    def _touch(path: Path) -> None:
        """Stamp access time so eviction's LRU ordering is meaningful."""
        try:
            os.utime(path, None)
        except OSError:
            pass

    # --------------------------------------------------------------- eviction

    def _entries(self):
        """
        Cached objects only — never the `.key` sidecars.

        Sidecars are metadata about a slot, not cache content: they must not be
        counted against the byte budget and must not be evicted on their own
        schedule, or invalidate_prefix() would lose the ability to identify a
        slot whose sidecar aged out first.
        """
        for path in self.root.rglob("*"):
            if not path.is_file() or path.name.endswith(".key"):
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            yield path, stat

    @staticmethod
    def _drop(path: Path) -> None:
        """Remove a slot and its sidecar together."""
        path.unlink(missing_ok=True)
        path.with_name(path.name + ".key").unlink(missing_ok=True)

    def evict(self) -> int:
        """
        Enforce TTL, then the byte budget, then the free-space floor.

        Returns the number of files removed. Runs after every insert: it is a
        directory scan of a few thousand small entries, which is cheap relative
        to the download that just happened.
        """
        removed = 0
        now = time.time()
        live = []

        for path, stat in self._entries():
            # Orphaned .part files: a process died mid-download. Nothing will
            # ever complete them, and they count against the budget.
            if path.name.endswith(_PART_SUFFIX):
                if now - stat.st_mtime > 300:
                    path.unlink(missing_ok=True)
                    removed += 1
                continue
            if self.ttl and now - stat.st_mtime > self.ttl:
                self._drop(path)
                removed += 1
                continue
            live.append((stat.st_mtime, stat.st_size, path))

        total = sum(size for _, size, _ in live)

        # LRU by mtime (which _touch keeps current) until under budget.
        live.sort(key=lambda item: item[0])
        idx = 0
        while self.max_bytes and total > self.max_bytes and idx < len(live):
            _, size, path = live[idx]
            self._drop(path)
            total -= size
            removed += 1
            idx += 1

        # Free-space floor, checked last and independently of the budget. In S3
        # mode this cache is the only thing that can still fill the disk, and
        # nothing else watches it — the 60 GB uploads watermark is a DB counter
        # and does not see these files at all.
        if self.min_free_bytes:
            try:
                free = shutil.disk_usage(self.root).free
            except OSError:
                free = None
            while free is not None and free < self.min_free_bytes and idx < len(live):
                _, size, path = live[idx]
                self._drop(path)
                removed += 1
                idx += 1
                free += size

        if removed:
            logger.debug(f"[ObjCache] Evicted {removed} entries; {total / 1024**2:.1f}MB retained")
        return removed

    def sweep_startup(self) -> int:
        """
        Clear leftovers from a previous process.

        A crash leaves .part files that no longer have an owner and a tree that
        may be over budget if the limits were lowered. Called once at boot.
        """
        removed = 0
        for path in self.root.rglob(f"*{_PART_SUFFIX}"):
            if path.is_file():
                path.unlink(missing_ok=True)
                removed += 1
        removed += self.evict()
        if removed:
            logger.info(f"[ObjCache] Startup sweep removed {removed} stale entries")
        return removed

    def invalidate_prefix(self, prefix: str) -> int:
        """
        Drop cached bytes for a storage prefix.

        Retention deletes a session with delete_prefix(); without this its
        cached originals would keep serving from local disk afterwards. Slots
        are content-addressed so the prefix cannot be derived from the path —
        hence the sidecar index below.
        """
        removed = 0
        for path, _ in list(self._entries()):
            sidecar = path.with_name(path.name + ".key")
            try:
                if sidecar.is_file() and sidecar.read_text(encoding="utf-8").startswith(prefix):
                    self._drop(path)
                    removed += 1
            except OSError:
                continue
        return removed

    def record_key(self, key: str, etag: Optional[str]) -> None:
        """Write the sidecar that invalidate_prefix() reads."""
        slot = self._slot(key, etag)
        try:
            slot.with_name(slot.name + ".key").write_text(key, encoding="utf-8")
        except OSError:
            pass

    def total_bytes(self) -> int:
        return sum(stat.st_size for _, stat in self._entries())
