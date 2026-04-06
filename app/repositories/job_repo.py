"""CRUD and lifecycle operations for the jobs table."""
from __future__ import annotations

from typing import Optional
import app.db as db
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
) -> Job:
    conn = db.get_connection()
    cur = conn.execute(
        """INSERT INTO jobs
           (name, source_id, destination_id, mode,
            date_from, date_to, id_from, id_to, single_message_id, use_blocked_words)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            name, source_id, destination_id, mode,
            date_from, date_to, id_from, id_to, single_message_id,
            1 if use_blocked_words else 0,
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
        rows = conn.execute(
            f"SELECT * FROM jobs WHERE status IN ({placeholders}) ORDER BY id DESC",
            status_filter,
        ).fetchall()
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


def delete(job_id: int) -> bool:
    conn = db.get_connection()
    cur = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    conn.commit()
    return cur.rowcount > 0


def count_by_status() -> dict[str, int]:
    conn = db.get_connection()
    rows = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM jobs GROUP BY status"
    ).fetchall()
    return {r["status"]: r["cnt"] for r in rows}


# ── Copied messages helpers ────────────────────────────────────────────────────

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
