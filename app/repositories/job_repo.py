"""CRUD and lifecycle operations for the jobs table."""
from __future__ import annotations

from typing import Optional
from app import db
from app.models import Job


def create(
    name: str,
    source_id: int,
    destination_id: int,
    mode: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    id_from: Optional[int] = None,
    id_to: Optional[int] = None,
    single_message_id: Optional[int] = None,
    use_blocked_words: bool = True,
    group_media: bool = True,
    copy_text: bool = True,
    content_types: str = "text,image,video",
) -> Job:
    conn = db.get_connection()
    cur = conn.execute(
        """INSERT INTO jobs
           (name, source_id, destination_id, mode,
            date_from, date_to, id_from, id_to, single_message_id,
            use_blocked_words, group_media, copy_text, content_types)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            name, source_id, destination_id, mode,
            date_from, date_to, id_from, id_to, single_message_id,
            1 if use_blocked_words else 0,
            1 if group_media else 0,
            1 if copy_text else 0,
            content_types,
        ),
    )
    conn.commit()
    return get_by_id(cur.lastrowid)  # type: ignore[arg-type]


def get_by_id(job_id: int) -> Optional[Job]:
    conn = db.get_connection()
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return Job.from_row(row) if row else None


def get_all(status_filter: Optional[list[str]] = None) -> list[Job]:
    conn = db.get_connection()
    if status_filter:
        placeholders = ",".join("?" * len(status_filter))
        query = f"SELECT * FROM jobs WHERE status IN ({placeholders}) ORDER BY id DESC"  # nosec B608
        rows = conn.execute(query, status_filter).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY id DESC"
        ).fetchall()
    return [Job.from_row(r) for r in rows]


def get_pending_job() -> Optional[Job]:
    """Return the oldest pending job (FIFO)."""
    conn = db.get_connection()
    row = conn.execute(
        "SELECT * FROM jobs WHERE status = 'pending' ORDER BY id ASC LIMIT 1"
    ).fetchone()
    return Job.from_row(row) if row else None


def get_resumable_job() -> Optional[Job]:
    """Return a waiting_retry job whose retry time has passed."""
    conn = db.get_connection()
    row = conn.execute(
        """SELECT * FROM jobs
           WHERE status = 'waiting_retry'
             AND (next_retry_at IS NULL OR next_retry_at <= datetime('now'))
           ORDER BY id ASC LIMIT 1"""
    ).fetchone()
    return Job.from_row(row) if row else None


def get_active_job() -> Optional[Job]:
    """Return any job that is currently in an active state."""
    conn = db.get_connection()
    row = conn.execute(
        "SELECT * FROM jobs WHERE status IN ('pending','running','waiting_retry') LIMIT 1"
    ).fetchone()
    return Job.from_row(row) if row else None


def update_status(
    job_id: int,
    status: str,
    error: Optional[str] = None,
    next_retry_at: Optional[str] = None,
) -> None:
    conn = db.get_connection()
    conn.execute(
        """UPDATE jobs SET
             status = ?,
             error_message = COALESCE(?, error_message),
             next_retry_at = ?,
             last_updated_at = datetime('now')
           WHERE id = ?""",
        (status, error, next_retry_at, job_id),
    )
    conn.commit()


def mark_started(job_id: int) -> None:
    conn = db.get_connection()
    conn.execute(
        """UPDATE jobs SET
             status = 'running',
             started_at = COALESCE(started_at, datetime('now')),
             last_updated_at = datetime('now')
           WHERE id = ?""",
        (job_id,),
    )
    conn.commit()


def mark_completed(job_id: int) -> None:
    conn = db.get_connection()
    conn.execute(
        """UPDATE jobs SET
             status = 'completed',
             completed_at = datetime('now'),
             last_updated_at = datetime('now')
           WHERE id = ?""",
        (job_id,),
    )
    conn.commit()


def update_progress(
    job_id: int,
    copied: int,
    skipped: int,
    failed: int,
    last_processed_id: int,
) -> None:
    conn = db.get_connection()
    conn.execute(
        """UPDATE jobs SET
             copied_count = ?,
             skipped_count = ?,
             failed_count = ?,
             last_processed_id = ?,
             last_updated_at = datetime('now')
           WHERE id = ?""",
        (copied, skipped, failed, last_processed_id, job_id),
    )
    conn.commit()


def increment_retry(job_id: int) -> int:
    """Increment retry counter and return the new count."""
    conn = db.get_connection()
    conn.execute(
        "UPDATE jobs SET retry_count = retry_count + 1 WHERE id = ?", (job_id,)
    )
    conn.commit()
    row = conn.execute(
        "SELECT retry_count FROM jobs WHERE id = ?", (job_id,)
    ).fetchone()
    return row["retry_count"] if row else 0


def pause_job(job_id: int) -> None:
    conn = db.get_connection()
    conn.execute(
        "UPDATE jobs SET status='paused', last_updated_at=datetime('now') WHERE id=? AND status IN ('running','pending','waiting_retry')",
        (job_id,),
    )
    conn.commit()


def resume_job(job_id: int) -> None:
    conn = db.get_connection()
    conn.execute(
        "UPDATE jobs SET status='pending', last_updated_at=datetime('now') WHERE id=? AND status='paused'",
        (job_id,),
    )
    conn.commit()


def is_paused(job_id: int) -> bool:
    conn = db.get_connection()
    row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
    return bool(row and row["status"] == "paused")


def delete(job_id: int) -> bool:
    conn = db.get_connection()
    cur = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    conn.commit()
    return cur.rowcount > 0


def get_queue_position(job_id: int) -> int:
    """Return 1-based position of this pending job in the queue (1 = next to run)."""
    conn = db.get_connection()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM jobs WHERE status = 'pending' AND id <= ?",
        (job_id,),
    ).fetchone()
    return row["cnt"] if row else 1


def count_by_status() -> dict[str, int]:
    conn = db.get_connection()
    rows = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM jobs GROUP BY status"
    ).fetchall()
    return {r["status"]: r["cnt"] for r in rows}


# ── Copied messages helpers ────────────────────────────────────────────────────

def save_report_url(job_id: int, url: str) -> None:
    conn = db.get_connection()
    conn.execute(
        "UPDATE jobs SET report_url = ? WHERE id = ?", (url, job_id)
    )
    conn.commit()


def get_report_messages(job_id: int) -> list[dict]:
    """
    Return failed + non-routine-skipped messages for report generation.
    Excludes: blocked_word, empty_message, content_type:* — all expected behavior.
    """
    conn = db.get_connection()
    rows = conn.execute(
        """SELECT source_message_id, status, skip_reason
           FROM copied_messages
           WHERE job_id = ?
             AND (
               status = 'failed'
               OR (
                 status = 'skipped'
                 AND (skip_reason IS NULL
                      OR (skip_reason NOT IN ('blocked_word', 'empty_message')
                          AND skip_reason NOT LIKE 'content_type:%'))
               )
             )
           ORDER BY source_message_id
           LIMIT 1000""",
        (job_id,),
    ).fetchall()
    return [
        {"msg_id": r["source_message_id"], "status": r["status"], "reason": r["skip_reason"]}
        for r in rows
    ]


def get_transfer_stats() -> dict[str, int]:
    """Return copied-message counts for the last hour, since midnight Israel time, and last 24h.

    processed_at is stored as UTC in SQLite. Cutoffs are computed in Python using the
    real Israel timezone (Asia/Jerusalem) so DST transitions are handled correctly.
    """
    from datetime import datetime, timezone, timedelta
    from zoneinfo import ZoneInfo
    _IL = ZoneInfo("Asia/Jerusalem")

    now_utc = datetime.now(timezone.utc)
    # Midnight today in Israel time, converted back to UTC
    now_il = now_utc.astimezone(_IL)
    midnight_il = now_il.replace(hour=0, minute=0, second=0, microsecond=0)
    midnight_utc = midnight_il.astimezone(timezone.utc)

    fmt = "%Y-%m-%d %H:%M:%S"
    cutoff_hour     = (now_utc - timedelta(hours=1)).strftime(fmt)
    cutoff_midnight = midnight_utc.strftime(fmt)
    cutoff_24h      = (now_utc - timedelta(hours=24)).strftime(fmt)

    conn = db.get_connection()
    row = conn.execute(
        """SELECT
             COUNT(CASE WHEN processed_at >= ? THEN 1 END) AS last_hour,
             COUNT(CASE WHEN processed_at >= ? THEN 1 END) AS since_midnight,
             COUNT(CASE WHEN processed_at >= ? THEN 1 END) AS last_24h
           FROM copied_messages
           WHERE status = 'copied'""",
        (cutoff_hour, cutoff_midnight, cutoff_24h),
    ).fetchone()
    if not row:
        return {"last_hour": 0, "since_midnight": 0, "last_24h": 0}
    return {
        "last_hour":      row["last_hour"] or 0,
        "since_midnight": row["since_midnight"] or 0,
        "last_24h":       row["last_24h"] or 0,
    }


def get_copied_source_ids(job_id: int) -> set[int]:
    """Return all source_message_ids already processed for this job."""
    conn = db.get_connection()
    rows = conn.execute(
        "SELECT source_message_id FROM copied_messages WHERE job_id = ?", (job_id,)
    ).fetchall()
    return {r["source_message_id"] for r in rows}


def record_copied_message(
    job_id: int,
    source_message_id: int,
    dest_message_id: Optional[int],
    status: str,
    skip_reason: Optional[str] = None,
) -> None:
    conn = db.get_connection()
    conn.execute(
        """INSERT OR IGNORE INTO copied_messages
           (job_id, source_message_id, dest_message_id, status, skip_reason)
           VALUES (?,?,?,?,?)""",
        (job_id, source_message_id, dest_message_id, status, skip_reason),
    )
    conn.commit()
