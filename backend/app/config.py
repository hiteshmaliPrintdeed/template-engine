import os
import shutil
import sys
import time
from pathlib import Path
from dotenv import load_dotenv
from loguru import logger

# Base Directories
BASE_DIR = Path(__file__).resolve().parent.parent
ROOT_ENV = BASE_DIR.parent.parent / ".env" # Check root workspace .env
LOCAL_ENV = BASE_DIR / ".env"              # Check local backend .env

# Load environment variables
if LOCAL_ENV.exists():
    load_dotenv(LOCAL_ENV)
elif ROOT_ENV.exists():
    load_dotenv(ROOT_ENV)
else:
    load_dotenv()

# ----------------------------------------------------------------------
# Quiet logs (local development)
# ----------------------------------------------------------------------
# PIXOVO_QUIET_LOGS=1 in a local backend/.env keeps the console readable for
# print() debugging: loguru's console drops to WARNING+ and uvicorn's
# per-request access log goes quiet. The log files are unaffected. Off by
# default, so servers and CI log exactly as before.
#
# Not covered: MediaPipe's three native lines at startup ("Created TensorFlow
# Lite XNNPACK delegate", "Logging before InitGoogle()", "W0000 ...
# inference_feedback_manager"). This build logs through C++ absl, which ignores
# GLOG_minloglevel and TF_CPP_MIN_LOG_LEVEL -- both were tried and verified to
# change nothing -- and they bypass Python entirely.
_quiet_raw = os.environ.get("PIXOVO_QUIET_LOGS", "")
QUIET_LOGS = _quiet_raw.strip().lower() in ("1", "true", "yes", "on")

# Upload Directories (Unified Dual-Asset Pipeline: Originals vs Thumbnails)
# [PRODUCTION SPEC]:
# - Originals: 300 DPI Print production assets
# - Thumbnails: 512px downsampled AI filtering & UI previews
# Overridable so tests write into a throwaway directory instead of the real
# uploads tree. Read at import time, which is when the mkdir calls below run.
UPLOADS_DIR = Path(os.environ.get("PIXOVO_UPLOADS_DIR") or (BASE_DIR / "app" / "uploads"))
UPLOADS_ORIGINALS_DIR = UPLOADS_DIR / "originals"
UPLOADS_THUMBNAILS_DIR = UPLOADS_DIR / "thumbnails"
UPLOADS_PREVIEWS_DIR = UPLOADS_DIR / "previews"
EXPORTS_DIR = Path(os.environ.get("PIXOVO_EXPORTS_DIR") or (BASE_DIR / "app" / "exports"))

# Centralized Face & Filter Models
FILTER_MODELS_DIR = BASE_DIR / "app" / "engine" / "filter" / "face_detector" / "models"
MODEL_BLAZEFACE = FILTER_MODELS_DIR / "blaze_face_short_range.tflite"
MODEL_YUNET = FILTER_MODELS_DIR / "face_detection_yunet_2023mar.onnx"
MODEL_HAARCASCADE = FILTER_MODELS_DIR / "haarcascade_frontalface_default.xml"

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_ORIGINALS_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Stage 1.6: `ensure_sample_placeholders()` used to be defined here and called
# at import time, writing 15 placeholder JPEGs (sample1-4 + sample_placeholder,
# in three directories) on every process start and every test collection.
#
# It existed to back fallbacks that have all been removed:
#   - process_async_job's four `sample_N` photos (deleted in Stage 1.4)
#   - solver.py's `photos[0] or sample_placeholder` cover (Stage 1.5)
#   - pdf_exporter's unresolvable-photo placeholder (Stage 1.6)
#
# Nothing reads these files now, and generating them was both an import-time
# side effect and a way for a placeholder to reach a paid print.

# Session Logs Directory
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

SESSION_TIMESTAMP = time.strftime("%Y-%m-%d_%H-%M-%S")
SESSION_LOG_FILE = LOGS_DIR / f"session_{SESSION_TIMESTAMP}.log"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")


# ----------------------------------------------------------------------
# Environment parsing helpers
# ----------------------------------------------------------------------
# `VAR=` in a .env file sets the variable to an EMPTY STRING, not to nothing.
# os.environ.get(name, default) therefore returns "" rather than the default,
# and int("") raises — so a commented-out-looking line in an otherwise valid
# .env would crash the process at import, before any logging is configured.
# That is a trap for anyone who copies .env.example and blanks a value to mean
# "use the default", which is the natural reading.
#
# These helpers treat empty and whitespace-only as absent.


def _env_str(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        # Naming the variable matters: the bare ValueError from int() surfaces
        # as an opaque traceback out of an import, with no clue which of the
        # ~20 numeric settings was at fault.
        raise RuntimeError(
            f"{name} must be an integer, got {raw!r}. "
            f"Leave it empty to use the default ({default})."
        ) from None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError:
        raise RuntimeError(
            f"{name} must be a number, got {raw!r}. "
            f"Leave it empty to use the default ({default})."
        ) from None

# ----------------------------------------------------------------------
# Story AI (Gemini)
# ----------------------------------------------------------------------
# Per-request HTTP timeouts, enforced by the SDK itself rather than by a thread
# wrapper -- a wrapper can report a timeout but cannot stop the call it is
# waiting on. The book call backs the interactive chat widget, so it is short;
# the chapter call runs inside the async generate job, which already shows a
# progress bar, and asks for far more output.
GEMINI_TIMEOUT_SEC = _env_float("PIXOVO_GEMINI_TIMEOUT_SEC", 8.0)
GEMINI_CHAPTER_TIMEOUT_SEC = _env_float("PIXOVO_GEMINI_CHAPTER_TIMEOUT_SEC", 20.0)

# Per-chapter captions from Gemini. Off restores book-level captions (one pool
# per variation) without a redeploy. Has no effect when GEMINI_API_KEY is unset.
CHAPTER_CAPTIONS_ENABLED = _env_bool("PIXOVO_CHAPTER_CAPTIONS", True)

# ----------------------------------------------------------------------
# Ingestion limits (Stage 1.1)
# ----------------------------------------------------------------------
# Hard ceiling per session. Enforced at POST /api/sessions so an oversized
# batch is rejected before any bytes are uploaded.
MAX_PHOTOS_PER_SESSION = _env_int("MAX_PHOTOS_PER_SESSION", 1000)

# Thumbnails per ingest chunk. Kept in config so the client can fetch it and
# the two sides cannot drift. 40 x ~35KB thumbnails is a ~1.5MB request.
INGEST_CHUNK_SIZE = _env_int("INGEST_CHUNK_SIZE", 40)

# ----------------------------------------------------------------------
# Concurrency sizing (Stage 1.4)
# ----------------------------------------------------------------------
# Previously ThreadPoolExecutor(max_workers=4) and Semaphore(4) were hardcoded
# regardless of the host, AND filter_engine constructed its own inner pool of 4
# per call — so 4 outer x 4 inner threads competed for however many cores the
# machine actually had, while OpenCV separately fanned out per operation.
CPU_COUNT = os.cpu_count() or 4

# Reserve a core for the event loop. A fully saturated pool starves request
# handling, and the symptom looks like a network problem rather than CPU
# exhaustion.
FILTER_WORKERS = _env_int("PIXOVO_FILTER_WORKERS", max(2, CPU_COUNT - 1))
JOB_CONCURRENCY = _env_int("PIXOVO_JOB_CONCURRENCY", max(2, CPU_COUNT // 2))

# thread | process — settled by measurement in Stage 1.7, not by argument.
# OpenCV releases the GIL; PIL and imagehash largely do not.
POOL_KIND = _env_str("PIXOVO_POOL", "thread")

# Bounded working caches. Both have SQLite fallbacks, so a miss is correct and
# merely slower. Unbounded dicts leaked for the life of the process.
PHOTO_CACHE_SIZE = _env_int("PIXOVO_PHOTO_CACHE", 8000)
JOB_CACHE_SIZE = _env_int("PIXOVO_JOB_CACHE", 500)
CACHE_TTL_SECONDS = _env_int("PIXOVO_CACHE_TTL", 3600)

# We parallelise across photos, so OpenCV must not also fan out within each
# operation — otherwise FILTER_WORKERS x CPU_COUNT threads thrash the machine.
try:
    import cv2 as _cv2

    _cv2.setNumThreads(1)
    logger_cv_note = f"cv2.setNumThreads(1) applied (was {CPU_COUNT} default)"
except Exception as _e:  # pragma: no cover
    logger_cv_note = f"cv2 thread limit not applied: {_e}"

# ----------------------------------------------------------------------
# Disk guards (Stage 1.3)
# ----------------------------------------------------------------------
# At the load target (20 users x 1000 photos) eager original upload would need
# ~160 GB. Demand-driven upload brings it to ~40 GB, but the machine still needs
# a hard stop: a demo that dies from a full disk is worse than one that says
# "at capacity".
MAX_BYTES_PER_SESSION = _env_int("MAX_BYTES_PER_SESSION", 3 * 1024**3)    # 3 GB

# Was GLOBAL_DISK_WATERMARK. It has always been a DB counter
# (SessionStore.total_bytes_all_sessions), never a filesystem probe, so it is
# already storage-agnostic — in S3 mode it is a billing guard rather than a disk
# guard. The old name stays as an alias so no existing .env breaks.
GLOBAL_STORAGE_BUDGET = _env_int(
    "GLOBAL_STORAGE_BUDGET",
    _env_int("GLOBAL_DISK_WATERMARK", 60 * 1024**3),
)
GLOBAL_DISK_WATERMARK = GLOBAL_STORAGE_BUDGET  # deprecated alias

# Hard per-file ceiling. Lives here rather than in main.py because the presign
# path needs it and importing from main would be circular.
MAX_FILE_SIZE = _env_int("MAX_FILE_SIZE", 20 * 1024 * 1024)  # 20 MB

# ----------------------------------------------------------------------
# Storage backend (Stage 1.3 seam; S3 direct upload)
# ----------------------------------------------------------------------
# Single instance shared by every caller. Which backend is built is the only
# thing that changes between local-disk and S3 deployments; no call site
# branches on it.
from app.storage import LocalDiskBackend, StorageBackend, storage_key  # noqa: E402
from app.storage.objcache import LocalObjectCache  # noqa: E402

STORAGE_KIND = _env_str("PIXOVO_STORAGE", "local").lower()

# Master switch for browser-direct uploads. Off by default even in S3 mode, so
# the two halves of the migration can be rolled out — and rolled back —
# independently: PIXOVO_STORAGE=s3 alone keeps the server in the byte path with
# the size and quota enforcement that has been running for months.
DIRECT_UPLOAD_ENABLED = _env_bool("PIXOVO_DIRECT_UPLOAD", False)

PRESIGN_TTL = _env_int("PIXOVO_S3_PRESIGN_TTL", 900)        # 15 min
MEDIA_GET_TTL = _env_int("PIXOVO_S3_MEDIA_GET_TTL", 3600)   # 1 hour
PRESIGN_RATE_PER_MIN = _env_int("PIXOVO_PRESIGN_RATE_PER_MIN", 120)

# Scratch: staging area for bytes on their way to or from remote storage.
# Distinct from UPLOADS_DIR, which in S3 mode holds nothing at all.
SCRATCH_DIR = Path(os.environ.get("PIXOVO_SCRATCH_DIR") or (BASE_DIR / ".scratch"))
SCRATCH_MAX_BYTES = _env_int("PIXOVO_SCRATCH_MAX_BYTES", 8 * 1024**3)     # 8 GB
SCRATCH_TTL_SECONDS = _env_int("PIXOVO_SCRATCH_TTL_SECONDS", 3600)
SCRATCH_MIN_FREE_BYTES = _env_int("PIXOVO_SCRATCH_MIN_FREE_BYTES", 5 * 1024**3)
SCRATCH_DIR.mkdir(parents=True, exist_ok=True)

OBJECT_CACHE = LocalObjectCache(
    root=SCRATCH_DIR / "objcache",
    max_bytes=SCRATCH_MAX_BYTES,
    ttl_seconds=SCRATCH_TTL_SECONDS,
    min_free_bytes=SCRATCH_MIN_FREE_BYTES,
)


def _build_storage() -> StorageBackend:
    """
    Construct the one shared StorageBackend, or refuse to start.

    Misconfigured S3 raises rather than falling back to local disk. That is the
    deliberate choice: url_for() returns the same "/uploads/{key}" string in
    both modes, so a silent fallback is indistinguishable in the logs, the
    database and the UI. The container would boot, accept uploads, write them to
    a layer that vanishes on the next deploy, and the failure would surface as a
    customer's paid print returning 404. Worse, a session spanning both modes
    has half its originals in each place under identical URLs — unrecoverable
    without a manual object inventory. A crash loop at boot is loud, immediate,
    and costs nobody a photo.
    """
    if STORAGE_KIND == "local":
        return LocalDiskBackend(root=UPLOADS_DIR, url_prefix="/uploads")

    if STORAGE_KIND != "s3":
        raise RuntimeError(
            f"PIXOVO_STORAGE must be 'local' or 's3', got {STORAGE_KIND!r}"
        )

    missing = [v for v in ("PIXOVO_S3_BUCKET", "PIXOVO_S3_REGION") if not os.environ.get(v)]
    if missing:
        raise RuntimeError(
            f"PIXOVO_STORAGE=s3 but {', '.join(missing)} is unset. Refusing to "
            f"start: falling back to local disk would write user photos to "
            f"storage that looks identical in every log and URL, and disappears "
            f"on the next deploy."
        )

    from app.storage.s3 import S3Backend

    backend = S3Backend(
        bucket=os.environ["PIXOVO_S3_BUCKET"],
        region=os.environ["PIXOVO_S3_REGION"],
        endpoint_url=os.environ.get("PIXOVO_S3_ENDPOINT_URL") or None,
        key_prefix=os.environ.get("PIXOVO_S3_KEY_PREFIX", ""),
        url_prefix="/uploads",
        presign_mode=_env_str("PIXOVO_S3_PRESIGN_MODE", "post").lower(),
        presign_ttl=PRESIGN_TTL,
        get_ttl=MEDIA_GET_TTL,
        sse=os.environ.get("PIXOVO_S3_SSE") or None,
        sse_kms_key=os.environ.get("PIXOVO_S3_SSE_KMS_KEY_ID") or None,
        storage_class=os.environ.get("PIXOVO_S3_STORAGE_CLASS") or None,
        cache=OBJECT_CACHE,
        max_pool_connections=_env_int("PIXOVO_S3_MAX_POOL", max(32, FILTER_WORKERS * 4)),
    )

    if _env_bool("PIXOVO_S3_STARTUP_CHECK", True):
        backend.startup_check()
    return backend


STORAGE: StorageBackend = _build_storage()
OBJECT_CACHE.sweep_startup()


def publish_export(staging_path: Path, session_id: str, filename: str) -> str:
    """
    Move a finished PDF from scratch into durable storage. Returns its URL.

    reportlab has to write to a real local path, so the export is always built
    in scratch and published afterwards. In local mode this is an os.replace
    into EXPORTS_DIR returning exactly the "/exports/{filename}" URL the engine
    has always returned, so nothing downstream can tell the difference.
    """
    staging_path = Path(staging_path)
    if STORAGE_KIND == "local":
        destination = EXPORTS_DIR / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(staging_path, destination)
        except OSError:
            # os.replace is atomic but cannot cross a filesystem, and scratch
            # and exports are frequently on different volumes (a scratch SSD, a
            # mounted exports volume, or simply different drives on Windows).
            # Copy into the destination DIRECTORY and rename within it, so the
            # publish stays atomic — a reader never sees a truncated PDF.
            staging_copy = destination.with_name(f"{destination.name}.{os.getpid()}.part")
            try:
                shutil.copyfile(staging_path, staging_copy)
                os.replace(staging_copy, destination)
            finally:
                staging_copy.unlink(missing_ok=True)
                staging_path.unlink(missing_ok=True)
        return f"/exports/{filename}"

    key = storage_key("exports", session_id or "unscoped", filename)
    STORAGE.put_path(key, str(staging_path), "application/pdf")
    staging_path.unlink(missing_ok=True)
    # Deliberately NOT STORAGE.url_for(), whose prefix is /uploads. Exports have
    # their own route, and the key is recoverable from this path.
    return f"/exports/{session_id or 'unscoped'}/{filename}"


# Configure Loguru Logger for metrics, stats, and session logging
logger.remove() # Remove default handler

_LOG_LEVELS = ("TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL", "OFF")


def _console_log_level() -> str:
    """
    PIXOVO_LOG_CONSOLE_LEVEL wins when set; otherwise WARNING in quiet mode and
    DEBUG (the long-standing default) otherwise. OFF removes the console sink.
    Only the console is affected -- the file sinks below always record DEBUG.
    """
    raw = _env_str("PIXOVO_LOG_CONSOLE_LEVEL", "").upper()
    if raw and raw not in _LOG_LEVELS:
        raise RuntimeError(
            f"PIXOVO_LOG_CONSOLE_LEVEL must be one of {', '.join(_LOG_LEVELS)}, got {raw!r}. "
            f"Leave it empty for the default."
        )
    return raw or ("WARNING" if QUIET_LOGS else "DEBUG")


CONSOLE_LOG_LEVEL = _console_log_level()

# 1. Console Output (Colorized; DEBUG unless quieted)
if CONSOLE_LOG_LEVEL != "OFF":
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level:7}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level=CONSOLE_LOG_LEVEL,
        colorize=True
    )

# 2. Cumulative Rotating Log File
CUMULATIVE_LOG_FILE = LOGS_DIR / "backend_metrics.log"
logger.add(
    str(CUMULATIVE_LOG_FILE),
    rotation="10 MB",
    retention="7 days",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:7} | {name}:{function}:{line} - {message}",
    level="DEBUG"
)

# 3. Dedicated Per-Session Log File
logger.add(
    str(SESSION_LOG_FILE),
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:7} | {name}:{function}:{line} - {message}",
    level="DEBUG"
)

if QUIET_LOGS:
    import logging
    # Uvicorn configures its loggers before importing the app -- in the --reload
    # worker process too -- so raising the level here, at app import, sticks.
    # Doing it in the app rather than with --no-access-log makes it work however
    # the server is launched. uvicorn.error (startup, reloads, crashed-request
    # tracebacks) is left alone: that is the channel that reports failures.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    # One line, so a quiet terminal is explained rather than mysterious. Not a
    # logger call: it is not a warning, and the console filters out anything less.
    print(
        f"[Pixovo] Quiet logs: console shows {CONSOLE_LOG_LEVEL}+ only. "
        f"Full log: logs/{SESSION_LOG_FILE.name}",
        file=sys.stderr,
        flush=True,
    )

logger.info(f"[Config] New backend session started. Log file: logs/{SESSION_LOG_FILE.name}")
logger.info(f"[Config] Environment loaded. GEMINI_API_KEY present: {bool(GEMINI_API_KEY)}")
logger.info(
    f"[Config] Concurrency: {CPU_COUNT} cores | filter workers {FILTER_WORKERS} "
    f"({POOL_KIND} pool) | job concurrency {JOB_CONCURRENCY} | {logger_cv_note}"
)
