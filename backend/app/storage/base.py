"""Abstract storage backend. LocalDisk today; S3/GCS later without caller changes."""

from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import BinaryIO, Dict, Iterable, Iterator, Optional

from app.storage.keys import StorageUnsupported


@dataclass(frozen=True)
class ObjectInfo:
    """
    Metadata about a stored object, fetched without transferring its bytes.

    A frozen dataclass rather than a dict on purpose: the confirm path is the
    one place where a typo like `info["sie"]` would silently disable the size
    check on a direct browser upload, and a dict would not catch it.
    """

    size: int
    content_type: Optional[str] = None
    etag: Optional[str] = None


@dataclass(frozen=True)
class PresignedUpload:
    """
    Everything a browser needs to upload one object directly to storage.

    One object covers both presigned POST and presigned PUT so the endpoint that
    hands it to the client does not branch on the provider — it forwards these
    fields verbatim and the client branches on `mode`.

    `max_bytes` is None when the chosen mode CANNOT constrain the upload size.
    That is the honest signal that confirm-time head() is the only defence: a
    presigned PUT's Content-Length is supplied by the client, so signing it
    enforces nothing. Only a POST policy's content-length-range is real.
    """

    mode: str                                    # "s3_post" | "s3_put"
    url: str
    key: str
    expires_in: int
    max_bytes: Optional[int] = None
    fields: Dict[str, str] = field(default_factory=dict)   # POST form fields
    headers: Dict[str, str] = field(default_factory=dict)  # required PUT headers


class StorageBackend(ABC):
    """
    Abstracts where photo bytes live.

    Keys are always relative, forward-slash separated, and of the shape
    "{kind}/{session_id}/{name}" — see app.storage.storage_key(). Implementations
    MUST reject absolute keys and any key containing '..', because keys are built
    from client-supplied photo ids and filenames. Use app.storage.keys.validate_key.

    Optional capabilities (presigning, head) are declared by the `supports_*`
    class attributes below and implemented as CONCRETE methods that raise
    StorageUnsupported by default. They are deliberately not abstract: adding an
    abstractmethod here would make every existing subclass un-instantiable, and a
    mixin would force callers back into isinstance() probes — which is exactly
    the branching this seam exists to remove. Callers read the flag and pick a
    supported path instead.
    """

    # ------------------------------------------------------------ capabilities
    supports_presigned_upload: bool = False
    supports_presigned_get: bool = False
    # True only when the backend can enforce a byte ceiling on a direct upload
    # (i.e. presigned POST with a content-length-range policy condition).
    enforces_upload_size: bool = False

    @abstractmethod
    def put_stream(self, key: str, stream: BinaryIO, content_type: str = "image/jpeg") -> str:
        """Write a file-like object to `key` in fixed chunks. Returns the public URL."""

    @abstractmethod
    def put_stream_iter(self, key: str, chunks: Iterable[bytes], content_type: str = "image/jpeg") -> str:
        """
        Write an iterator of byte chunks to `key`. Lets the caller enforce a size
        cap mid-copy so an oversized upload is rejected before it fully lands.
        A partial write MUST be cleaned up if the iterator raises.
        """

    @abstractmethod
    def get_path(self, key: str) -> Optional[str]:
        """
        Local filesystem path for reading, or None if absent.
        A remote backend downloads to a temp file and returns that path.
        """

    @abstractmethod
    def url_for(self, key: str) -> str:
        """
        Browser-facing URL for `key`.

        MUST be stable and durable. It is persisted in photos.url, embedded in
        jobs.variations_json by the solver, read back out by
        dsa_solver.reshuffle_single_spread_engine(), and held in a long-lived
        SPA. A presigned (expiring) URL here is a time bomb — remote backends
        return the same relative "/uploads/{key}" string the local backend does
        and let the media route presign per request.
        """

    @abstractmethod
    def exists(self, key: str) -> bool:
        ...

    @abstractmethod
    def delete(self, key: str) -> None:
        ...

    @abstractmethod
    def delete_prefix(self, prefix: str) -> int:
        """Delete everything under a prefix. Returns the count. Used by retention."""

    @abstractmethod
    def total_bytes(self, prefix: str = "") -> int:
        """
        Sum of stored bytes under a prefix.

        Walks storage, so it is too slow for a per-request check — use the
        running total on sessions.total_bytes for that. This is for sweeps,
        diagnostics and tests.
        """

    @abstractmethod
    def key_for_url(self, url: str) -> Optional[str]:
        """Inverse of url_for(). Returns None if the URL is not ours."""

    # ------------------------------------------------------------------ writes

    def put_path(self, key: str, path: str, content_type: str = "image/jpeg") -> str:
        """
        Upload an existing local file to `key`. Returns the public URL.

        Exists so a caller can stage bytes locally, do local-only work on them
        (see the capture-time mtime stamp in the ingest handler), and only then
        hand them to storage — instead of writing through storage and reading
        back, which for a remote backend is a needless round trip per photo.

        The default streams the file through put_stream(); a backend that can
        upload a path more efficiently should override.
        """
        with open(path, "rb") as fh:
            return self.put_stream(key, fh, content_type)

    # ------------------------------------------------------------------- reads

    @contextmanager
    def open_local(self, key: str) -> Iterator[Optional[str]]:
        """
        Scoped local path for `key`, valid for the duration of the block.

        Preferred over get_path() for new byte-consumers: it gives a remote
        backend a place to release whatever it materialised. The default
        delegates to get_path() and releases nothing, which is exactly right for
        a local backend where the path IS the storage.
        """
        yield self.get_path(key)

    def head(self, key: str) -> Optional[ObjectInfo]:
        """
        Object metadata without transferring bytes. None if absent.

        This is the authority for verifying a direct browser upload — never the
        size the client claims to have uploaded.
        """
        raise StorageUnsupported(f"{type(self).__name__} does not implement head()")

    # ----------------------------------------------------------------- presign

    def presigned_upload(
        self,
        key: str,
        *,
        content_type: str,
        max_bytes: int,
        expires_in: int,
    ) -> PresignedUpload:
        """Credentials for the browser to upload one object directly to `key`."""
        raise StorageUnsupported(f"{type(self).__name__} cannot presign uploads")

    def presigned_get_url(
        self,
        key: str,
        *,
        expires_in: int,
        download_filename: Optional[str] = None,
    ) -> str:
        """Short-lived read URL for `key`. Never persist the result."""
        raise StorageUnsupported(f"{type(self).__name__} cannot presign reads")
