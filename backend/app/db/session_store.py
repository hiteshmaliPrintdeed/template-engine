"""
SQLite-backed persistent store for Pixovo Sessions, Photos, and Async Jobs.
Provides thread-safe operations, automatic table creation, and crash-resilience.
"""

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import List, Optional, Dict, Any
from app.schemas.photobook import (
    PhotoMeta, JobStatusResponse, PhotobookVariation, GenerateVariationsResponse
)
from app.config import logger

# Overridable so tests can point at a throwaway file instead of the dev database.
# Read at import time, which is when init_db() runs.
DB_PATH = Path(
    os.environ.get("PIXOVO_DB_PATH")
    or Path(__file__).resolve().parent.parent.parent / "pixovo_session.db"
)

_local = threading.local()

_PRAGMAS = (
    "journal_mode=WAL",      # non-blocking concurrent reads
    "synchronous=NORMAL",
    "busy_timeout=30000",
    "temp_store=MEMORY",
)


def get_db_connection() -> sqlite3.Connection:
    """
    Returns this thread's SQLite connection, creating it on first use.

    Stage 1.4: previously every call opened a fresh connection and executed four
    PRAGMAs. At the load target that is thousands of connection setups per
    second across the worker pool, and `journal_mode=WAL` in particular is not
    free. One connection per thread is both correct (SQLite connections are not
    safe to share across threads) and far cheaper.

    Callers must NOT close the returned connection — it is reused. `with conn:`
    is still correct: it manages the transaction, not the connection.
    """
    conn = getattr(_local, "conn", None)
    if conn is not None:
        # Reading total_changes is a C-level attribute access (effectively free)
        # that raises if the connection has been closed. Without this probe, a
        # single stray close() anywhere poisons every later call on this thread
        # with "Cannot operate on a closed database" far from the real cause.
        try:
            conn.total_changes
            return conn
        except sqlite3.ProgrammingError:
            logger.warning("[DB] Thread-local connection was closed; reopening.")
            _local.conn = None

    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=30.0)
    for pragma in _PRAGMAS:
        conn.execute(f"PRAGMA {pragma};")
    conn.row_factory = sqlite3.Row
    _local.conn = conn
    return conn


def close_thread_connection() -> None:
    """Closes this thread's connection, if any. Used by tests and shutdown."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        finally:
            _local.conn = None

def init_db():
    """Initializes the database schema if it doesn't already exist."""
    conn = get_db_connection()
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS photos (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                filename TEXT,
                url TEXT,
                preview_url TEXT,
                original_url TEXT,
                thumbnail_url TEXT,
                original_synced INTEGER DEFAULT 0,
                width INTEGER DEFAULT 1200,
                height INTEGER DEFAULT 900,
                aspect_ratio REAL DEFAULT 1.33,
                dominant_colors_json TEXT,
                score REAL DEFAULT 0.8,
                blur_score REAL,
                face_count INTEGER DEFAULT 0,
                shell_phash TEXT,
                core_phash TEXT,
                is_hero_candidate INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                -- Stage 1.2: the filter engine's output, previously discarded
                timestamp_epoch REAL DEFAULT 0,
                latitude REAL,
                longitude REAL,
                hero_score REAL DEFAULT 0,
                layout_role TEXT DEFAULT 'STANDARD_FRAME',
                is_event_cover_hero INTEGER DEFAULT 0,
                tenengrad_score REAL,
                contrast_score REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                session_id TEXT,
                status TEXT,
                progress INTEGER DEFAULT 0,
                message TEXT,
                variations_json TEXT,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Stage 1.1: Explicit session lifecycle. A session is created BEFORE any
        # upload begins, so every ingest chunk lands under one stable session_id.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expected_photo_count INTEGER DEFAULT 0,
                received_photo_count INTEGER DEFAULT 0,
                survived_photo_count INTEGER DEFAULT 0,
                total_bytes INTEGER DEFAULT 0,
                status TEXT DEFAULT 'ingesting'
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_photos_session ON photos(session_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_jobs_session ON jobs(session_id)
        """)
        _ensure_photo_columns(conn)
        _ensure_session_columns(conn)
        _ensure_job_columns(conn)
    # NOTE: no conn.close() — the connection is thread-local and reused.
    logger.info(f"[DB] Initialized persistent SQLite database at: {DB_PATH}")


# Columns added after the original `photos` table shipped. CREATE TABLE IF NOT
# EXISTS will not add columns to a table that already exists, so an existing
# database needs an explicit, idempotent ALTER.
_PHOTO_COLUMN_MIGRATIONS = [
    ("timestamp_epoch", "REAL DEFAULT 0"),
    ("latitude", "REAL"),
    ("longitude", "REAL"),
    ("hero_score", "REAL DEFAULT 0"),
    ("layout_role", "TEXT DEFAULT 'STANDARD_FRAME'"),
    ("is_event_cover_hero", "INTEGER DEFAULT 0"),
    ("tenengrad_score", "REAL"),
    ("contrast_score", "REAL"),
    # --- S3 direct upload ---------------------------------------------------
    ("thumbnail_key", "TEXT"),
    ("original_key", "TEXT"),
    ("original_bytes", "INTEGER DEFAULT 0"),
    ("original_etag", "TEXT"),
    ("declared_bytes", "INTEGER DEFAULT 0"),
    ("presigned_at", "TIMESTAMP"),
]

# Same idempotent-ALTER treatment for `sessions` and `jobs`.
_SESSION_COLUMN_MIGRATIONS = [
    ("presign_count", "INTEGER DEFAULT 0"),
    ("last_presign_at", "TIMESTAMP"),
    # Stage 3.2: Guided Story Studio content preferences & cached title brainstorm
    ("custom_title", "TEXT"),
    ("include_text", "INTEGER DEFAULT 1"),
    ("subtitle", "TEXT"),
    ("suggested_titles_json", "TEXT"),
]

_JOB_COLUMN_MIGRATIONS = [
    ("custom_title", "TEXT"),
    ("include_text", "INTEGER DEFAULT 1"),
    ("subtitle", "TEXT"),
]


def _ensure_photo_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(photos)")}
    added = []
    for column, ddl in _PHOTO_COLUMN_MIGRATIONS:
        if column not in existing:
            conn.execute(f"ALTER TABLE photos ADD COLUMN {column} {ddl}")
            added.append(column)
    if added:
        logger.info(f"[DB] Migrated photos table: added {', '.join(added)}")


def _ensure_session_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)")}
    added = []
    for column, ddl in _SESSION_COLUMN_MIGRATIONS:
        if column not in existing:
            conn.execute(f"ALTER TABLE sessions ADD COLUMN {column} {ddl}")
            added.append(column)
    if added:
        logger.info(f"[DB] Migrated sessions table: added {', '.join(added)}")


def _ensure_job_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
    added = []
    for column, ddl in _JOB_COLUMN_MIGRATIONS:
        if column not in existing:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} {ddl}")
            added.append(column)
    if added:
        logger.info(f"[DB] Migrated jobs table: added {', '.join(added)}")


def _row_to_photo_meta(row: sqlite3.Row) -> PhotoMeta:
    """
    Single source of truth for row -> PhotoMeta.

    get_photo(), get_photos() and get_session_photos() each hand-built this
    object from ~20 identical lines. Adding the Stage 1.2 fields would have made
    that ~28 lines in three places, and the classic failure is updating two of
    the three — leaving photos correct via one endpoint and null via another.
    """
    keys = row.keys()

    def opt(name, default=None):
        """Tolerate rows read from a database that predates a column."""
        return row[name] if name in keys else default

    return PhotoMeta(
        id=row["id"],
        filename=row["filename"],
        url=row["url"],
        preview_url=row["preview_url"],
        original_url=row["original_url"],
        thumbnail_url=row["thumbnail_url"],
        original_synced=bool(row["original_synced"]),
        width=row["width"],
        height=row["height"],
        aspect_ratio=row["aspect_ratio"],
        dominant_colors=json.loads(row["dominant_colors_json"] or "[]"),
        score=row["score"],
        blur_score=row["blur_score"],
        face_count=row["face_count"],
        shell_phash=row["shell_phash"],
        core_phash=row["core_phash"],
        is_hero_candidate=bool(row["is_hero_candidate"]),
        # Stage 1.2 fields
        timestamp_epoch=opt("timestamp_epoch", 0.0) or 0.0,
        latitude=opt("latitude"),
        longitude=opt("longitude"),
        hero_score=opt("hero_score", 0.0) or 0.0,
        layout_role=opt("layout_role", "STANDARD_FRAME") or "STANDARD_FRAME",
        is_event_cover_hero=bool(opt("is_event_cover_hero", 0)),
        tenengrad_score=opt("tenengrad_score"),
        contrast_score=opt("contrast_score"),
        # S3 direct upload — server-side keys, None on pre-migration rows.
        thumbnail_key=opt("thumbnail_key"),
        original_key=opt("original_key"),
        declared_bytes=opt("declared_bytes", 0) or 0,
    )


# Column list shared by save_photo() and save_photos_batch() so the two INSERTs
# cannot drift apart.
_PHOTO_INSERT_COLUMNS = (
    "id, session_id, filename, url, preview_url, original_url, thumbnail_url, "
    "original_synced, width, height, aspect_ratio, dominant_colors_json, "
    "score, blur_score, face_count, shell_phash, core_phash, is_hero_candidate, "
    "timestamp_epoch, latitude, longitude, hero_score, layout_role, "
    "is_event_cover_hero, tenengrad_score, contrast_score, "
    "thumbnail_key, original_key, declared_bytes"
)
# NOTE: original_bytes, original_etag and presigned_at are deliberately absent.
# They are written only by the confirm/presign UPDATEs, and this INSERT is an
# INSERT OR REPLACE — listing them here would let a replayed ingest chunk reset
# a verified byte count back to zero.
_PHOTO_INSERT_PLACEHOLDERS = ", ".join(["?"] * len(_PHOTO_INSERT_COLUMNS.split(",")))


def _photo_to_row(photo: PhotoMeta, session_id: Optional[str]) -> tuple:
    """Flattens a PhotoMeta into the tuple order declared by _PHOTO_INSERT_COLUMNS."""
    return (
        photo.id,
        session_id,
        photo.filename,
        photo.url,
        photo.preview_url or photo.url,
        photo.original_url,
        photo.thumbnail_url,
        1 if photo.original_synced else 0,
        photo.width,
        photo.height,
        photo.aspect_ratio,
        json.dumps(photo.dominant_colors or []),
        photo.score,
        photo.blur_score,
        photo.face_count,
        photo.shell_phash,
        photo.core_phash,
        1 if photo.is_hero_candidate else 0,
        photo.timestamp_epoch or 0.0,
        photo.latitude,
        photo.longitude,
        photo.hero_score or 0.0,
        photo.layout_role or "STANDARD_FRAME",
        1 if photo.is_event_cover_hero else 0,
        photo.tenengrad_score,
        photo.contrast_score,
        photo.thumbnail_key,
        photo.original_key,
        int(photo.declared_bytes or 0),
    )


# Initialize on module import
init_db()

class SessionStore:
    """Thread-safe CRUD operations for Sessions, Photos and Jobs."""

    @staticmethod
    def ping() -> bool:
        """Cheapest possible liveness check on the database, for /ready."""
        conn = get_db_connection()
        conn.execute("SELECT 1").fetchone()
        return True

    # ------------------------------------------------------------------
    # Sessions (Stage 1.1)
    # ------------------------------------------------------------------

    @staticmethod
    def create_session(session_id: str, expected_photo_count: int = 0) -> None:
        """Registers a new upload session before any ingest chunk arrives."""
        conn = get_db_connection()
        with conn:
            conn.execute(
                """
                INSERT INTO sessions (session_id, expected_photo_count, status)
                VALUES (?, ?, 'ingesting')
                """,
                (session_id, expected_photo_count),
            )

    @staticmethod
    def get_session(session_id: str) -> Optional[Dict[str, Any]]:
        if not session_id:
            return None
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    @staticmethod
    def touch_session(session_id: str) -> None:
        """Bumps last_accessed_at so the retention sweep can identify live sessions."""
        conn = get_db_connection()
        with conn:
            conn.execute(
                "UPDATE sessions SET last_accessed_at = CURRENT_TIMESTAMP WHERE session_id = ?",
                (session_id,),
            )

    @staticmethod
    def set_session_status(session_id: str, status: str) -> None:
        conn = get_db_connection()
        with conn:
            conn.execute(
                "UPDATE sessions SET status = ?, last_accessed_at = CURRENT_TIMESTAMP WHERE session_id = ?",
                (status, session_id),
            )

    @staticmethod
    def recount_session(session_id: str, received_delta: int = 0) -> Dict[str, int]:
        """
        Recomputes session counters from the photos table rather than incrementing
        a running total. A replayed ingest chunk therefore converges instead of
        inflating the counts (chunk idempotency, Stage 1.1 Task 6).

        `received_delta` is added to the stored received count, which cannot be
        derived from `photos` because rejected photos are never persisted there.
        """
        conn = get_db_connection()
        with conn:
            if received_delta:
                conn.execute(
                    """
                    UPDATE sessions
                    SET received_photo_count = received_photo_count + ?
                    WHERE session_id = ?
                    """,
                    (received_delta, session_id),
                )
            conn.execute(
                """
                UPDATE sessions
                SET survived_photo_count = (
                        SELECT COUNT(*) FROM photos WHERE session_id = ?
                    ),
                    last_accessed_at = CURRENT_TIMESTAMP
                WHERE session_id = ?
                """,
                (session_id, session_id),
            )
        cur = conn.cursor()
        cur.execute(
            "SELECT received_photo_count, survived_photo_count FROM sessions WHERE session_id = ?",
            (session_id,),
        )
        row = cur.fetchone()
        if not row:
            return {"received_photo_count": 0, "survived_photo_count": 0}
        return {
            "received_photo_count": row["received_photo_count"],
            "survived_photo_count": row["survived_photo_count"],
        }

    @staticmethod
    def add_session_bytes(session_id: str, delta: int) -> int:
        """
        Adds to a session's running byte total and returns the new value.

        Stage 1.3: a running counter, not a filesystem walk. StorageBackend
        .total_bytes() rglobs the tree, which is far too slow to call on every
        upload at 20 concurrent sessions.
        """
        if not delta:
            return int((SessionStore.get_session(session_id) or {}).get("total_bytes") or 0)
        conn = get_db_connection()
        with conn:
            conn.execute(
                """
                UPDATE sessions
                SET total_bytes = COALESCE(total_bytes, 0) + ?,
                    last_accessed_at = CURRENT_TIMESTAMP
                WHERE session_id = ?
                """,
                (int(delta), session_id),
            )
        cur = conn.cursor()
        cur.execute("SELECT total_bytes FROM sessions WHERE session_id = ?", (session_id,))
        row = cur.fetchone()
        return int(row["total_bytes"]) if row else 0

    @staticmethod
    def total_bytes_all_sessions() -> int:
        """Sum of every session's running byte total — for the global watermark."""
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(SUM(total_bytes), 0) AS total FROM sessions")
        return int(cur.fetchone()["total"])

    @staticmethod
    def get_photo_session(photo_id: str) -> Optional[str]:
        """Returns the session_id owning a photo, for cross-session access checks."""
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT session_id FROM photos WHERE id = ?", (photo_id,))
        row = cur.fetchone()
        return row["session_id"] if row else None

    # ------------------------------------------------------------------
    # Photos
    # ------------------------------------------------------------------

    @staticmethod
    def save_photo(photo: PhotoMeta, session_id: Optional[str] = None) -> None:
        conn = get_db_connection()
        with conn:
            conn.execute(
                f"INSERT OR REPLACE INTO photos ({_PHOTO_INSERT_COLUMNS}) "
                f"VALUES ({_PHOTO_INSERT_PLACEHOLDERS})",
                _photo_to_row(photo, session_id),
            )

    @staticmethod
    def save_photos_batch(photos: List[PhotoMeta], session_id: Optional[str] = None) -> None:
        """Atomic batch insert using executemany for high performance with up to 1000+ photos."""
        if not photos:
            return
        conn = get_db_connection()
        records = [_photo_to_row(photo, session_id) for photo in photos]
        with conn:
            conn.executemany(
                f"INSERT OR REPLACE INTO photos ({_PHOTO_INSERT_COLUMNS}) "
                f"VALUES ({_PHOTO_INSERT_PLACEHOLDERS})",
                records,
            )

    @staticmethod
    def get_photo(photo_id: str) -> Optional[PhotoMeta]:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM photos WHERE id = ?", (photo_id,))
        row = cur.fetchone()
        return _row_to_photo_meta(row) if row else None

    @staticmethod
    def get_photos(photo_ids: List[str]) -> List[PhotoMeta]:
        """
        Retrieves photos in safe batches of 500 to prevent SQLite 999 parameter placeholder limits
        when fetching large sessions (e.g. 1000 photos).
        """
        if not photo_ids:
            return []
        conn = get_db_connection()
        results = {}
        chunk_size = 500
        cur = conn.cursor()
        for i in range(0, len(photo_ids), chunk_size):
            chunk = photo_ids[i:i + chunk_size]
            placeholders = ",".join(["?"] * len(chunk))
            cur.execute(f"SELECT * FROM photos WHERE id IN ({placeholders})", chunk)
            for row in cur.fetchall():
                results[row["id"]] = _row_to_photo_meta(row)
        return [results[pid] for pid in photo_ids if pid in results]

    @staticmethod
    def get_session_photos(session_id: str) -> List[PhotoMeta]:
        """Retrieves all photos persisted under a given session_id."""
        if not session_id:
            return []
        conn = get_db_connection()
        cur = conn.cursor()
        # Ordered by capture time so downstream chaptering receives a
        # chronological list. created_at is insertion order, which after
        # chunked ingest is upload order, not photo order.
        cur.execute(
            """
            SELECT * FROM photos
            WHERE session_id = ?
            ORDER BY
                CASE WHEN COALESCE(timestamp_epoch, 0) > 0 THEN 0 ELSE 1 END,
                timestamp_epoch ASC,
                created_at ASC
            """,
            (session_id,),
        )
        return [_row_to_photo_meta(row) for row in cur.fetchall()]

    @staticmethod
    def mark_original_synced(photo_id: str, original_url: str) -> None:
        conn = get_db_connection()
        with conn:
            conn.execute("""
                UPDATE photos
                SET original_url = ?, original_synced = 1
                WHERE id = ?
            """, (original_url, photo_id))

    @staticmethod
    def mark_original_synced_verified(
        photo_id: str,
        *,
        url: str,
        key: str,
        size: int,
        etag: Optional[str],
    ) -> bool:
        """
        Record a direct-upload original whose bytes were verified by head_object.

        Returns True only when the stored byte count actually changed, which is
        what makes a replayed confirm free: the client retries aggressively (on
        reconnect, on the `online` event, on every resume), and without this
        guard each retry would add the file's size to sessions.total_bytes
        again and walk a session into a spurious quota rejection.

        `size` must come from storage, never from the request body.
        """
        conn = get_db_connection()
        with conn:
            cur = conn.execute("""
                UPDATE photos
                   SET original_url = ?, original_key = ?, original_bytes = ?,
                       original_etag = ?, original_synced = 1
                 WHERE id = ?
                   AND (original_synced = 0 OR COALESCE(original_bytes, 0) <> ?)
            """, (url, key, int(size), etag, photo_id, int(size)))
        return cur.rowcount > 0

    @staticmethod
    def get_original_bytes(photo_id: str) -> int:
        """Bytes already counted for this photo, so confirm can apply a delta."""
        conn = get_db_connection()
        cur = conn.execute(
            "SELECT COALESCE(original_bytes, 0) AS n FROM photos WHERE id = ?",
            (photo_id,),
        )
        row = cur.fetchone()
        return int(row["n"]) if row else 0

    @staticmethod
    def mark_presigned(photo_id: str, declared_bytes: int = 0) -> None:
        """
        Stamp a photo as having an outstanding presigned upload.

        `presigned_at` is what lets presign-time admission control see bytes
        that are in flight but not yet confirmed, and what lets a reconciler
        later find objects that landed in storage but whose confirm never
        arrived.
        """
        conn = get_db_connection()
        with conn:
            conn.execute("""
                UPDATE photos
                   SET presigned_at = CURRENT_TIMESTAMP,
                       declared_bytes = CASE WHEN ? > 0 THEN ?
                                             ELSE COALESCE(declared_bytes, 0) END
                 WHERE id = ?
            """, (int(declared_bytes), int(declared_bytes), photo_id))

    @staticmethod
    def reserved_bytes(session_id: str) -> int:
        """
        Client-declared size of this session's presigned-but-unconfirmed photos.

        With direct upload the server never sees the bytes, so between presign
        and confirm the true usage is unknown. This is an admission hint only —
        a lying client can under-declare, and confirm's head_object remains the
        authority. It bounds the overshoot to (in-flight presigns x MAX_FILE_SIZE)
        rather than letting 150 concurrent presigns sail past the quota.
        """
        conn = get_db_connection()
        cur = conn.execute("""
            SELECT COALESCE(SUM(declared_bytes), 0) AS n
              FROM photos
             WHERE session_id = ?
               AND original_synced = 0
               AND presigned_at IS NOT NULL
        """, (session_id,))
        row = cur.fetchone()
        return int(row["n"]) if row else 0

    @staticmethod
    def bump_presign_count(session_id: str) -> int:
        """Increment and return the session's lifetime presign count."""
        conn = get_db_connection()
        with conn:
            conn.execute("""
                UPDATE sessions
                   SET presign_count = COALESCE(presign_count, 0) + 1,
                       last_presign_at = CURRENT_TIMESTAMP
                 WHERE session_id = ?
            """, (session_id,))
        cur = conn.execute(
            "SELECT COALESCE(presign_count, 0) AS n FROM sessions WHERE session_id = ?",
            (session_id,),
        )
        row = cur.fetchone()
        return int(row["n"]) if row else 0

    @staticmethod
    def count_photos() -> int:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as count FROM photos")
        return cur.fetchone()["count"]

    @staticmethod
    def save_title_suggestions(session_id: Optional[str], suggestions: Dict[str, Any]) -> None:
        """Persists suggest-titles output against session_id so a session only calls AI once."""
        if not session_id or not suggestions:
            return
        conn = get_db_connection()
        payload = json.dumps(suggestions)
        with conn:
            conn.execute(
                """
                INSERT INTO sessions (session_id, suggested_titles_json, last_accessed_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(session_id) DO UPDATE SET
                    suggested_titles_json = excluded.suggested_titles_json,
                    last_accessed_at = CURRENT_TIMESTAMP
                """,
                (session_id, payload),
            )

    @staticmethod
    def get_title_suggestions(session_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """Reads cached suggest-titles output for session_id, if any."""
        if not session_id:
            return None
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT suggested_titles_json FROM sessions WHERE session_id = ?",
            (session_id,),
        )
        row = cur.fetchone()
        if not row or not row["suggested_titles_json"]:
            return None
        try:
            return json.loads(row["suggested_titles_json"])
        except Exception:
            return None

    @staticmethod
    def save_session_preferences(
        session_id: Optional[str],
        custom_title: Optional[str] = None,
        include_text: bool = True,
        subtitle: Optional[str] = None,
        job_id: Optional[str] = None,
    ) -> None:
        """Persists Studio content preferences against session_id (and job_id) for reshuffle."""
        conn = get_db_connection()
        inc_int = 1 if include_text else 0
        with conn:
            if session_id:
                conn.execute(
                    """
                    INSERT INTO sessions (session_id, custom_title, include_text, subtitle, last_accessed_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(session_id) DO UPDATE SET
                        custom_title = excluded.custom_title,
                        include_text = excluded.include_text,
                        subtitle = excluded.subtitle,
                        last_accessed_at = CURRENT_TIMESTAMP
                    """,
                    (session_id, custom_title, inc_int, subtitle),
                )
            if job_id:
                conn.execute(
                    """
                    UPDATE jobs
                       SET custom_title = ?, include_text = ?, subtitle = ?, updated_at = CURRENT_TIMESTAMP
                     WHERE job_id = ?
                    """,
                    (custom_title, inc_int, subtitle, job_id),
                )

    @staticmethod
    def get_session_preferences(
        session_id: Optional[str] = None,
        job_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Reads persisted custom_title/include_text/subtitle from sessions or jobs."""
        conn = get_db_connection()
        cur = conn.cursor()
        if session_id:
            cur.execute(
                "SELECT custom_title, include_text, subtitle FROM sessions WHERE session_id = ?",
                (session_id,),
            )
            row = cur.fetchone()
            if row and row["include_text"] is not None:
                return {
                    "custom_title": row["custom_title"],
                    "include_text": bool(row["include_text"]),
                    "subtitle": row["subtitle"],
                }
        if job_id:
            cur.execute(
                "SELECT session_id, custom_title, include_text, subtitle FROM jobs WHERE job_id = ?",
                (job_id,),
            )
            jrow = cur.fetchone()
            if jrow:
                if jrow["include_text"] is not None:
                    return {
                        "custom_title": jrow["custom_title"],
                        "include_text": bool(jrow["include_text"]),
                        "subtitle": jrow["subtitle"],
                    }
                if jrow["session_id"] and jrow["session_id"] != session_id:
                    return SessionStore.get_session_preferences(session_id=jrow["session_id"])
        return {
            "custom_title": None,
            "include_text": True,
            "subtitle": None,
        }

    @staticmethod
    def save_job(
        job: JobStatusResponse,
        session_id: Optional[str] = None,
        custom_title: Optional[str] = None,
        include_text: Optional[bool] = None,
        subtitle: Optional[str] = None,
    ) -> None:
        conn = get_db_connection()
        result_json = None
        if job.result and job.result.variations:
            result_json = json.dumps({
                "theme_name": job.result.theme_name,
                "variations": [v.dict() for v in job.result.variations]
            })

        # Preserve existing preferences on the job row if not explicitly overridden
        cur = conn.cursor()
        cur.execute(
            "SELECT session_id, custom_title, include_text, subtitle FROM jobs WHERE job_id = ?",
            (job.job_id,),
        )
        existing = cur.fetchone()
        eff_session = session_id or (existing["session_id"] if existing else None)
        eff_title = custom_title if custom_title is not None else (existing["custom_title"] if existing else None)
        if include_text is not None:
            eff_inc = 1 if include_text else 0
        elif existing and existing["include_text"] is not None:
            eff_inc = int(existing["include_text"])
        else:
            eff_inc = 1
        eff_sub = subtitle if subtitle is not None else (existing["subtitle"] if existing else None)

        with conn:
            conn.execute("""
                INSERT OR REPLACE INTO jobs (
                    job_id, session_id, status, progress, message, variations_json, error_message,
                    custom_title, include_text, subtitle, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                job.job_id,
                eff_session,
                job.status,
                job.progress,
                job.message,
                result_json,
                getattr(job, "error", None),
                eff_title,
                eff_inc,
                eff_sub,
            ))
            if eff_session and (custom_title is not None or include_text is not None or subtitle is not None):
                conn.execute(
                    """
                    INSERT INTO sessions (session_id, custom_title, include_text, subtitle, last_accessed_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(session_id) DO UPDATE SET
                        custom_title = excluded.custom_title,
                        include_text = excluded.include_text,
                        subtitle = excluded.subtitle,
                        last_accessed_at = CURRENT_TIMESTAMP
                    """,
                    (eff_session, eff_title, eff_inc, eff_sub),
                )

    @staticmethod
    def get_job(job_id: str) -> Optional[JobStatusResponse]:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
        row = cur.fetchone()
        if not row:
            return None

        result_obj = None
        if row["variations_json"]:
            raw_data = json.loads(row["variations_json"])
            variations = [PhotobookVariation(**v) for v in raw_data.get("variations", [])]
            result_obj = GenerateVariationsResponse(
                theme_name=raw_data.get("theme_name", "Warm"),
                variations=variations
            )

        return JobStatusResponse(
            job_id=row["job_id"],
            status=row["status"],
            progress=row["progress"],
            message=row["message"],
            result=result_obj
        )

    @staticmethod
    def count_jobs() -> int:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as count FROM jobs")
        return cur.fetchone()["count"]

