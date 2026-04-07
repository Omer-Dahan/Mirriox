"""SQLite connection management and schema initialization."""
from __future__ import annotations

import sqlite3
import logging
import os

logger = logging.getLogger(__name__)

_connection: sqlite3.Connection | None = None
_db_path: str = "mirriox.db"

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS admins (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL UNIQUE,
    username    TEXT,
    added_at    TEXT NOT NULL DEFAULT (datetime('now')),
    added_by    INTEGER
);

CREATE TABLE IF NOT EXISTS sources (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    channel_ref TEXT NOT NULL UNIQUE,
    title       TEXT,
    resolved_id INTEGER,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS destinations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    channel_ref TEXT NOT NULL UNIQUE,
    title       TEXT,
    resolved_id INTEGER,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS blocked_words (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    word     TEXT NOT NULL UNIQUE COLLATE NOCASE,
    added_at TEXT NOT NULL DEFAULT (datetime('now')),
    added_by INTEGER
);

CREATE TABLE IF NOT EXISTS jobs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL,
    source_id         INTEGER NOT NULL REFERENCES sources(id),
    destination_id    INTEGER NOT NULL REFERENCES destinations(id),
    mode              TEXT NOT NULL CHECK(mode IN ('all','date_range','id_range','single_id')),
    date_from         TEXT,
    date_to           TEXT,
    id_from           INTEGER,
    id_to             INTEGER,
    single_message_id INTEGER,
    use_blocked_words INTEGER NOT NULL DEFAULT 1,
    status            TEXT NOT NULL DEFAULT 'draft'
                      CHECK(status IN ('draft','pending','running','paused',
                                       'completed','cancelled','failed','waiting_retry')),
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    started_at        TEXT,
    completed_at      TEXT,
    last_updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
    total_messages    INTEGER DEFAULT 0,
    copied_count      INTEGER DEFAULT 0,
    skipped_count     INTEGER DEFAULT 0,
    failed_count      INTEGER DEFAULT 0,
    last_processed_id INTEGER,
    retry_count       INTEGER NOT NULL DEFAULT 0,
    max_retries       INTEGER NOT NULL DEFAULT 3,
    next_retry_at     TEXT,
    error_message     TEXT
);

CREATE TABLE IF NOT EXISTS copied_messages (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id            INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    source_message_id INTEGER NOT NULL,
    dest_message_id   INTEGER,
    status            TEXT NOT NULL CHECK(status IN ('copied','skipped','failed')),
    skip_reason       TEXT,
    processed_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(job_id, source_message_id)
);

CREATE TABLE IF NOT EXISTS worker_state (
    id             INTEGER PRIMARY KEY CHECK(id = 1),
    status         TEXT NOT NULL DEFAULT 'idle'
                   CHECK(status IN ('idle','running','stopped','error')),
    current_job_id INTEGER REFERENCES jobs(id),
    last_heartbeat TEXT,
    error_message  TEXT
);

CREATE TABLE IF NOT EXISTS app_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_jobs_status        ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_copied_msg_job     ON copied_messages(job_id);
CREATE INDEX IF NOT EXISTS idx_copied_src_id      ON copied_messages(job_id, source_message_id);

INSERT OR IGNORE INTO worker_state(id) VALUES(1);

INSERT OR IGNORE INTO app_settings(key,value) VALUES
    ('min_delay_ms',        '2000'),
    ('max_delay_ms',        '5000'),
    ('flood_buffer_min_s',  '5'),
    ('flood_buffer_max_s',  '10'),
    ('batch_size_min',      '50'),
    ('batch_size_max',      '100'),
    ('batch_pause_min_s',   '60'),
    ('batch_pause_max_s',   '120'),
    ('max_retries',         '5'),
    ('heartbeat_interval_s','30'),
    ('main_chat_id',        ''),
    ('main_message_id',     '');
"""


def init(db_path: str) -> None:
    """Set the database path. Must be called before get_connection()."""
    global _db_path
    _db_path = db_path
    # Ensure parent directory exists
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def get_connection() -> sqlite3.Connection:
    """Return (or create) the module-level SQLite connection."""
    global _connection
    if _connection is None:
        _connection = sqlite3.connect(_db_path, check_same_thread=False)
        _connection.row_factory = sqlite3.Row
        _connection.execute("PRAGMA journal_mode=WAL")
        _connection.execute("PRAGMA foreign_keys=ON")
        logger.debug("SQLite connection opened: %s", _db_path)
    return _connection


def init_schema() -> None:
    """Create all tables and seed default rows. Idempotent."""
    conn = get_connection()
    conn.executescript(SCHEMA_SQL)
    _run_migrations(conn)
    conn.commit()
    logger.info("Database schema initialized")


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Add columns that were introduced after initial schema. Safe to re-run."""
    _add_column_if_missing(conn, "sources",       "validation_error", "TEXT")
    _add_column_if_missing(conn, "destinations",  "validation_error", "TEXT")
    _add_column_if_missing(conn, "jobs",          "content_types",    "TEXT DEFAULT 'text,image,video'")
    _add_column_if_missing(conn, "jobs",          "report_url",       "TEXT")
    _seed_missing_settings(conn, {
        "flood_buffer_min_s": "5",
        "flood_buffer_max_s": "10",
        "batch_size_min":     "50",
        "batch_size_max":     "100",
        "batch_pause_min_s":  "60",
        "batch_pause_max_s":  "120",
        "group_media":        "1",
    })


def _add_column_if_missing(
    conn: sqlite3.Connection, table: str, column: str, col_type: str
) -> None:
    existing = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        logger.debug("Migration: added column %s.%s", table, column)


def _seed_missing_settings(conn: sqlite3.Connection, defaults: dict[str, str]) -> None:
    """Insert app_settings rows that don't exist yet (idempotent)."""
    for key, value in defaults.items():
        conn.execute(
            "INSERT OR IGNORE INTO app_settings(key, value) VALUES (?, ?)",
            (key, value),
        )
        logger.debug("Migration: seeded setting %s=%s (if missing)", key, value)


def close() -> None:
    """Close the database connection on graceful shutdown."""
    global _connection
    if _connection is not None:
        _connection.close()
        _connection = None
        logger.debug("SQLite connection closed")
