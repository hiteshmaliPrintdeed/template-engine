"""
Policy for browser-direct uploads.

With a presigned upload the PUT/POST bypasses FastAPI entirely — no middleware,
no handler, no validation runs when the bytes arrive. The presign call is
therefore the ONLY trust boundary, and everything in this module exists to be
decided there rather than inferred later.

The rules are deliberately paranoid about anything client-supplied, because a
storage key is built from a client-minted photo id and a client-supplied
filename, and a signed URL is a capability the browser holds for 15 minutes.
"""

import re
import threading
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

# Content types a browser may upload. Chosen by the server from this set — the
# client's request is a suggestion, not an instruction.
#
# Note what is absent: svg and html. Both are active content, and an object
# stored under an image content type but served inline is an XSS vector the day
# someone points a CDN at the bucket or makes an object public.
ALLOWED_UPLOAD_TYPES = frozenset({
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
    "image/tiff",
})

# Extensions we are willing to put in a storage key, mapped to the content type
# the server will sign for. Anything else collapses to .jpg rather than being
# rejected: the extension comes from a filename the user picked on their own
# device, and refusing the upload over an odd extension would be worse than
# storing it under a normalised one.
_EXT_TO_TYPE: Dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}

_DEFAULT_EXT = ".jpg"
_DEFAULT_TYPE = "image/jpeg"

# Both ids are server-minted in practice — session_id is
# `sess_` + secrets.token_urlsafe(24), photo_id is `px_<base36>_<base36>` from
# the client downsampler. The charset check is defence in depth: a photo_id that
# failed it could not be in the photos table at all, having had to survive
# ingest first. But S3 has no filesystem to resolve a path against, so the
# syntactic guard is the only one there and it must be explicit.
_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


def valid_identifier(value: str) -> bool:
    """True when `value` is safe to embed in a storage key."""
    return bool(value) and _IDENTIFIER_RE.fullmatch(value) is not None


def ext_and_type_for(filename: Optional[str]) -> Tuple[str, str]:
    """
    Derive the storage extension and content type from a persisted filename.

    Called with `photos.filename`, which was recorded at ingest — NEVER with a
    filename from the presign request. That is the point: taking the extension
    from the request would let `filename=../../../evil.html` shape the key, and
    would let a client choose the content type an object is served with.
    """
    suffix = Path(filename or "").suffix.lower()
    if suffix in _EXT_TO_TYPE:
        return suffix, _EXT_TO_TYPE[suffix]
    return _DEFAULT_EXT, _DEFAULT_TYPE


def resolve_content_type(requested: Optional[str], filename: Optional[str]) -> Optional[str]:
    """
    Pick the content type to sign for, or None if the request must be refused.

    The client's suggestion is honoured only when it is in the allowlist; when
    it is absent we fall back to the type implied by the stored filename. A
    suggestion outside the allowlist is an error rather than something to
    silently override, because it means the client and server disagree about
    what is being uploaded.
    """
    if requested:
        normalised = requested.split(";")[0].strip().lower()
        if normalised not in ALLOWED_UPLOAD_TYPES:
            return None
        return "image/jpeg" if normalised == "image/jpg" else normalised
    return ext_and_type_for(filename)[1]


class RateLimiter:
    """
    Per-key sliding-window limiter for presign requests.

    In-process, which is sufficient because the app runs a single uvicorn worker
    (see ROADMAP: Redis and a real task queue are the prerequisite for more).
    With `--workers N` the effective limit becomes N x the configured rate; the
    durable `sessions.presign_count` ceiling is what bounds abuse in that case.

    Returning 429 is safe for the client: it already treats non-permanent
    failures as retryable and backs off.
    """

    def __init__(self, per_minute: int):
        self.per_minute = max(1, int(per_minute))
        self._hits: Dict[str, list] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - 60.0
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if t > cutoff]
            if len(hits) >= self.per_minute:
                self._hits[key] = hits
                return False
            hits.append(now)
            self._hits[key] = hits

            # Opportunistic sweep so an abandoned session's window does not sit
            # in memory for the life of the process.
            if len(self._hits) > 512:
                for k in [k for k, v in self._hits.items() if not any(t > cutoff for t in v)]:
                    self._hits.pop(k, None)
            return True
