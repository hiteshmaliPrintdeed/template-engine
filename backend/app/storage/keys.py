"""
Key validation shared by every StorageBackend.

Extracted from LocalDiskBackend._p() so that every backend enforces the same
syntactic invariant. This is not a stylistic refactor: the local backend gets a
second line of defence for free, because `Path.resolve()` plus a prefix check
catches anything the syntax check misses. S3 has no such fallback — there is no
filesystem to resolve against, and "originals/s/../../x.jpg" is a perfectly
legal S3 key that simply is not the key we intended to write. So for a remote
backend this function is the ONLY guard, and keys are built from client-minted
photo ids.
"""

from pathlib import PurePosixPath


class StorageUnsupported(RuntimeError):
    """
    Raised when a backend cannot satisfy an optional capability.

    Callers should prefer probing the `supports_*` class attributes over
    catching this — the probe lets an endpoint degrade to a supported path,
    whereas the exception only says it was asked too late.
    """


def validate_key(key: str) -> str:
    """
    Rejects any key that is not a relative, forward-slash separated path.

    Returns the key unchanged so it can be used inline:  `self._k(validate_key(key))`
    Raises ValueError, which is what the pre-existing callers already expect.
    """
    if not key:
        raise ValueError(f"Unsafe storage key: {key!r}")

    # Absolute in either separator convention, or a Windows drive letter. A
    # drive-relative key like "C:foo" is also rejected: os.path.join would treat
    # it as absolute on Windows and silently escape the root.
    if key.startswith("/") or key.startswith("\\") or (len(key) > 1 and key[1] == ":"):
        raise ValueError(f"Unsafe storage key: {key!r}")

    # Backslashes are never a separator in a storage key. Allowing them would
    # mean "a\..\b" passes the '..' check below on POSIX but escapes on
    # Windows — the two backends would disagree about the same string.
    if "\\" in key:
        raise ValueError(f"Unsafe storage key: {key!r}")

    if ".." in PurePosixPath(key).parts:
        raise ValueError(f"Unsafe storage key: {key!r}")

    return key
