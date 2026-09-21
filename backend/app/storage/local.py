"""Local filesystem StorageBackend."""

import mimetypes
import shutil
from pathlib import Path
from typing import BinaryIO, Iterable, Optional

from app.storage.base import ObjectInfo, StorageBackend
from app.storage.keys import validate_key

_COPY_CHUNK = 1024 * 1024  # 1 MB — constant memory regardless of file size

_EXTENDED_PREFIX = "\\\\?\\"
_EXTENDED_UNC_PREFIX = "\\\\?\\UNC\\"


def _strip_extended_prefix(path: Path) -> Path:
    """
    Remove Windows' \\\\?\\ extended-length prefix, if present.

    Path.resolve() returns the extended form non-deterministically on Windows:
    it appears when the path is in a transient state, notably while a parent
    directory is being created by another thread. Ingest uploads a whole chunk
    concurrently into one session directory, so this happens routinely there.

    Without normalisation the containment check below compares a \\\\?\\-prefixed
    child against an unprefixed root, the prefix test fails, and a perfectly
    legitimate key is rejected as a traversal attempt — intermittently, under
    load, which is the worst way to find out.

    Case is not handled here because pathlib already compares Windows paths
    case-insensitively.
    """
    text = str(path)
    if text.startswith(_EXTENDED_UNC_PREFIX):
        return Path("\\\\" + text[len(_EXTENDED_UNC_PREFIX):])
    if text.startswith(_EXTENDED_PREFIX):
        return Path(text[len(_EXTENDED_PREFIX):])
    return path


class LocalDiskBackend(StorageBackend):
    def __init__(self, root: Path, url_prefix: str = "/uploads"):
        self.root = Path(root)
        self.url_prefix = url_prefix.rstrip("/")

    # ------------------------------------------------------------------ paths

    def _p(self, key: str) -> Path:
        """
        Resolves a key to a path inside the storage root.

        The traversal guard is load-bearing: keys embed client-supplied photo
        ids, so without it a photo_id of "../../etc/x" would write outside the
        uploads root. Checked both syntactically and by resolved prefix, because
        a symlink inside the tree could otherwise escape it.

        The syntactic half lives in app.storage.keys.validate_key so that remote
        backends — which have no filesystem to resolve against, and for which it
        is therefore the only guard — enforce the identical invariant.
        """
        validate_key(key)

        # Both sides go through the same normalisation, or the comparison is
        # only valid when resolve() happens to pick the same spelling twice.
        full = _strip_extended_prefix((self.root / Path(key)).resolve())
        root = _strip_extended_prefix(self.root.resolve())
        if root != full and root not in full.parents:
            raise ValueError(f"Storage key escapes root: {key!r}")
        return full

    # ------------------------------------------------------------------ write

    def put_stream(self, key: str, stream: BinaryIO, content_type: str = "image/jpeg") -> str:
        path = self._p(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "wb") as dest:
                shutil.copyfileobj(stream, dest, length=_COPY_CHUNK)
        except Exception:
            path.unlink(missing_ok=True)  # never leave a truncated file behind
            raise
        return self.url_for(key)

    def put_stream_iter(self, key: str, chunks: Iterable[bytes], content_type: str = "image/jpeg") -> str:
        path = self._p(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "wb") as dest:
                for chunk in chunks:
                    dest.write(chunk)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return self.url_for(key)

    def put_path(self, key: str, path: str, content_type: str = "image/jpeg") -> str:
        """
        Copy an existing local file to `key`, preserving its mtime.

        copy2 rather than the base class's open()+put_stream() specifically for
        the mtime: the ingest handler stamps a staged thumbnail with the client's
        reported capture time before handing it over, because canvas
        downsampling strips EXIF and the filter engine falls back to the file's
        mtime. Losing it here would silently disable event clustering and the
        45-minute chapter rule — see the Stage 1.2 notes in the ingest handler.
        """
        dest = self._p(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(path, dest)
        except Exception:
            dest.unlink(missing_ok=True)  # never leave a truncated file behind
            raise
        return self.url_for(key)

    # ------------------------------------------------------------------- read

    def get_path(self, key: str) -> Optional[str]:
        try:
            path = self._p(key)
        except ValueError:
            return None
        return str(path) if path.is_file() else None

    def url_for(self, key: str) -> str:
        return f"{self.url_prefix}/{key}"

    def key_for_url(self, url: str) -> Optional[str]:
        if not url:
            return None
        clean = url.split("?")[0]
        prefix = self.url_prefix + "/"
        if not clean.startswith(prefix):
            return None
        return clean[len(prefix):]

    def exists(self, key: str) -> bool:
        try:
            return self._p(key).is_file()
        except ValueError:
            return False

    def head(self, key: str) -> Optional[ObjectInfo]:
        """
        Size and type without reading the file.

        Implemented so the storage contract test suite — and any future caller
        that verifies an upload landed — runs identically against both backends.
        There is no etag concept on local disk; None is correct rather than a
        fabricated hash, since callers use it only for cache invalidation.
        """
        try:
            path = self._p(key)
        except ValueError:
            return None
        if not path.is_file():
            return None
        return ObjectInfo(
            size=path.stat().st_size,
            content_type=mimetypes.guess_type(path.name)[0],
            etag=None,
        )

    # ----------------------------------------------------------------- delete

    def delete(self, key: str) -> None:
        try:
            self._p(key).unlink(missing_ok=True)
        except ValueError:
            pass

    def delete_prefix(self, prefix: str) -> int:
        try:
            directory = self._p(prefix)
        except ValueError:
            return 0
        if not directory.is_dir():
            return 0
        count = sum(1 for f in directory.rglob("*") if f.is_file())
        shutil.rmtree(directory, ignore_errors=True)
        return count

    # ------------------------------------------------------------ accounting

    def total_bytes(self, prefix: str = "") -> int:
        directory = self._p(prefix) if prefix else self.root
        if not directory.is_dir():
            return 0
        return sum(f.stat().st_size for f in directory.rglob("*") if f.is_file())
