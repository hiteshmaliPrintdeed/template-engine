"""
Storage abstraction for photo bytes.

Stage 1.3: every read and write of photo bytes goes through a StorageBackend
rather than touching UPLOADS_* paths directly. Today that is LocalDiskBackend;
swapping in S3 later is a config change plus one new subclass, with no caller
edits — which is the whole point of introducing the seam while there are only
a handful of call sites.
"""

from app.storage.base import ObjectInfo, PresignedUpload, StorageBackend
from app.storage.keys import StorageUnsupported, validate_key
from app.storage.local import LocalDiskBackend

__all__ = [
    "StorageBackend",
    "LocalDiskBackend",
    "ObjectInfo",
    "PresignedUpload",
    "StorageUnsupported",
    "storage_key",
    "validate_key",
]


def storage_key(kind: str, session_id: str, name: str) -> str:
    """
    Builds the one canonical key shape used everywhere:

        thumbnails/{session_id}/{photo_id}.jpg
        originals/{session_id}/{photo_id}.{ext}
        exports/{session_id}/{variation_id}.pdf

    Keeping this in one function means a session's assets are always reachable
    by prefix, so retention is `delete_prefix(f"originals/{session_id}")`.
    """
    if kind not in ("thumbnails", "originals", "exports", "previews"):
        raise ValueError(f"Unknown storage kind: {kind}")
    return f"{kind}/{session_id}/{name}"
