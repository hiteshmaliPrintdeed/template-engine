"""
Shared pytest fixtures.

Isolation strategy: the database path, the uploads tree and the exports tree are
all redirected to a temporary location *before* `app.*` is imported, because both
`app.config` and `app.db.session_store` do work at import time
(`ensure_sample_placeholders()` / directory creation, and `init_db()`).

All three redirects are required. Redirecting only the database still lets the
suite write session directories into the real `backend/app/uploads/` tree, which
accumulates silently across runs.

A fuller harness — synthetic photo corpus generator, load fixtures, per-test DB
rollback — lands in Stage 1.7 (docs/plans/M1-1.7-load-proof.md).
"""

import os
import tempfile
from pathlib import Path

import pytest

_TMP_ROOT = Path(tempfile.mkdtemp(prefix="pixovo_test_"))
os.environ.setdefault("PIXOVO_DB_PATH", str(_TMP_ROOT / "test_session.db"))
os.environ.setdefault("PIXOVO_UPLOADS_DIR", str(_TMP_ROOT / "uploads"))
os.environ.setdefault("PIXOVO_EXPORTS_DIR", str(_TMP_ROOT / "exports"))
# Pin the storage backend for the whole suite. Without this a developer who has
# PIXOVO_STORAGE=s3 exported in their shell runs every test against a real
# bucket — writing test photos into production storage.
os.environ.setdefault("PIXOVO_STORAGE", "local")

import cv2  # noqa: E402
import numpy as np  # noqa: E402


@pytest.fixture(scope="session")
def tmp_root() -> Path:
    return _TMP_ROOT


@pytest.fixture(scope="session")
def client():
    """FastAPI TestClient bound to the throwaway database."""
    from fastapi.testclient import TestClient
    from app.main import app

    return TestClient(app)


@pytest.fixture(scope="session")
def store():
    from app.db.session_store import SessionStore

    return SessionStore


def make_thumbnail_bytes(seed: int = 0) -> bytes:
    """
    A sharp, well-exposed, non-junk 512px JPEG that survives Phase 1 filtering.

    The grid lines matter: the sharpness gate uses Tenengrad + Laplacian, and
    pure noise alone does not reliably clear the threshold.

    CAVEAT for anyone writing size assertions: dense noise plus hard edges is
    close to worst-case for JPEG, so these come out around 160 KB each versus
    ~30-40 KB for a real 512px photo thumbnail. Assert size *ratios*, never
    absolute byte counts, or you are measuring the fixture. Stage 1.7's corpus
    generator should produce photo-realistic images with representative sizes.
    """
    rng = np.random.default_rng(seed)
    img = rng.integers(60, 200, (384, 512, 3), dtype=np.uint8)
    for i in range(0, 512, 24):
        cv2.line(img, (i, 0), (i, 384), (255, 255, 255), 2)
    for j in range(0, 384, 24):
        cv2.line(img, (0, j), (512, j), (0, 0, 0), 2)
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    assert ok, "failed to encode test thumbnail"
    return buf.tobytes()


@pytest.fixture
def thumbnail_factory():
    return make_thumbnail_bytes


@pytest.fixture
def s3_app(tmp_path):
    """
    A (TestClient, backend) pair for an app constructed in S3 mode on moto.

    Reimporting app.* under patched environment is necessary rather than lazy:
    the media route is registered at import time behind
    `if STORAGE.supports_presigned_get`, and `app.main` does
    `from app.config import STORAGE`, which binds the name at import. A
    monkeypatch of app.config.STORAGE after the fact changes neither.

    The module table is saved and restored so the session-scoped local-mode
    `client` fixture keeps working for every other test in the run.
    """
    import importlib
    import sys

    import pytest as _pytest

    boto3 = _pytest.importorskip("boto3")
    moto = _pytest.importorskip("moto")
    from fastapi.testclient import TestClient

    bucket = "pixovo-s3-app-test"
    region = "us-east-1"
    env_keys = (
        "PIXOVO_STORAGE", "PIXOVO_S3_BUCKET", "PIXOVO_S3_REGION",
        "PIXOVO_S3_STARTUP_CHECK", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
    )
    saved_env = {k: os.environ.get(k) for k in env_keys}
    saved_modules = {
        name: sys.modules.pop(name)
        for name in list(sys.modules)
        if name == "app" or name.startswith("app.")
    }

    os.environ.update({
        "PIXOVO_STORAGE": "s3",
        "PIXOVO_S3_BUCKET": bucket,
        "PIXOVO_S3_REGION": region,
        "PIXOVO_S3_STARTUP_CHECK": "0",
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
    })

    try:
        with moto.mock_aws():
            boto3.client("s3", region_name=region).create_bucket(Bucket=bucket)
            main = importlib.import_module("app.main")
            yield TestClient(main.app), main.STORAGE
    finally:
        for name in [n for n in list(sys.modules) if n == "app" or n.startswith("app.")]:
            sys.modules.pop(name, None)
        sys.modules.update(saved_modules)
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
