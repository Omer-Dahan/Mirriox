"""Repository for duplicate scan and bulk-delete operations."""
from __future__ import annotations

import logging
from typing import Any

from app.db import get_connection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Duplicate scans
# ---------------------------------------------------------------------------

def create_scan(channel_ref: str, channel_title: str, dest_id: int | None = None) -> int:
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO duplicate_scans(channel_ref, channel_title, dest_id) VALUES (?,?,?)",
        (channel_ref, channel_title, dest_id),
    )
    conn.commit()
    return cur.lastrowid


def start_scan(scan_id: int) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE duplicate_scans SET status='running' WHERE id=?", (scan_id,)
    )
    conn.commit()


def update_progress(scan_id: int, scanned: int, total: int) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE duplicate_scans SET messages_scanned=?, total_messages=? WHERE id=?",
        (scanned, total, scan_id),
    )
    conn.commit()


def finish_scan(scan_id: int, groups: int, wasted_count: int, report_url: str | None = None) -> None:
    conn = get_connection()
    conn.execute(
        """UPDATE duplicate_scans
           SET status='done', duplicate_groups=?, wasted_count=?,
               report_url=?, completed_at=datetime('now')
           WHERE id=?""",
        (groups, wasted_count, report_url, scan_id),
    )
    conn.commit()


def fail_scan(scan_id: int, error_msg: str) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE duplicate_scans SET status='failed', error_msg=? WHERE id=?",
        (error_msg, scan_id),
    )
    conn.commit()


def cancel_scan(scan_id: int) -> None:
    """Mark a pending/running scan as failed (user-initiated stop)."""
    conn = get_connection()
    conn.execute(
        "UPDATE duplicate_scans SET status='failed', error_msg='בוטל על ידי המשתמש' WHERE id=? AND status IN ('pending','running')",
        (scan_id,),
    )
    conn.commit()


def delete_scans_for_channel(channel_ref: str) -> int:
    """Delete ALL scan records (and their items/delete-jobs via CASCADE) for a channel. Returns count deleted."""
    conn = get_connection()
    # delete_scan_jobs references duplicate_scans — delete them first
    conn.execute(
        "DELETE FROM delete_scan_jobs WHERE scan_id IN (SELECT id FROM duplicate_scans WHERE channel_ref=?)",
        (channel_ref,),
    )
    conn.execute(
        "DELETE FROM duplicate_scan_items WHERE scan_id IN (SELECT id FROM duplicate_scans WHERE channel_ref=?)",
        (channel_ref,),
    )
    cur = conn.execute(
        "DELETE FROM duplicate_scans WHERE channel_ref=?",
        (channel_ref,),
    )
    conn.commit()
    return cur.rowcount


def insert_item(
    scan_id: int,
    message_id: int,
    media_id: int,
    media_type: str,
    file_size: int | None,
    mime_type: str | None,
    msg_date: str,
) -> None:
    conn = get_connection()
    conn.execute(
        """INSERT INTO duplicate_scan_items
           (scan_id, message_id, media_id, media_type, file_size, mime_type, msg_date)
           VALUES (?,?,?,?,?,?,?)""",
        (scan_id, message_id, media_id, media_type, file_size, mime_type, msg_date),
    )
    # Caller commits in batches for performance


def get_duplicate_groups(scan_id: int) -> list[dict[str, Any]]:
    """Return groups where the same media_id appears more than once, sorted by count desc."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT media_id, media_type, mime_type,
                  MAX(file_size) AS file_size,
                  COUNT(*) AS total_count,
                  MIN(message_id) AS oldest_msg_id
           FROM duplicate_scan_items
           WHERE scan_id=?
           GROUP BY media_id
           HAVING COUNT(*) > 1
           ORDER BY COUNT(*) DESC""",
        (scan_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_items_for_media(scan_id: int, media_id: int) -> list[dict[str, Any]]:
    """Return all scan items for a specific media_id, ordered by date asc."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT message_id, msg_date
           FROM duplicate_scan_items
           WHERE scan_id=? AND media_id=?
           ORDER BY msg_date ASC""",
        (scan_id, media_id),
    ).fetchall()
    return [dict(r) for r in rows]


def reset_running_scans_to_pending() -> int:
    """Reset any scans stuck in 'running' back to 'pending' (used on startup and after network drops)."""
    conn = get_connection()
    cur = conn.execute(
        "UPDATE duplicate_scans SET status='pending' WHERE status='running'"
    )
    conn.commit()
    return cur.rowcount


def get_pending_scan() -> dict[str, Any] | None:
    conn = get_connection()
    row = conn.execute(
        """SELECT id AS scan_id, channel_ref, channel_title, dest_id
           FROM duplicate_scans
           WHERE status='pending'
           ORDER BY created_at ASC
           LIMIT 1"""
    ).fetchone()
    return dict(row) if row else None


def get_scan_by_id(scan_id: int) -> dict[str, Any] | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM duplicate_scans WHERE id=?", (scan_id,)
    ).fetchone()
    return dict(row) if row else None


def get_latest_scan_for_channel(channel_ref: str) -> dict[str, Any] | None:
    conn = get_connection()
    row = conn.execute(
        """SELECT * FROM duplicate_scans
           WHERE channel_ref=?
           ORDER BY created_at DESC
           LIMIT 1""",
        (channel_ref,),
    ).fetchone()
    return dict(row) if row else None


def get_all_scans(limit: int = 20) -> list[dict[str, Any]]:
    """Return recent scans for the scan list screen."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM duplicate_scans
           ORDER BY created_at DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Delete scan jobs
# ---------------------------------------------------------------------------

def create_delete_job(scan_id: int) -> int:
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO delete_scan_jobs(scan_id) VALUES (?)", (scan_id,)
    )
    conn.commit()
    return cur.lastrowid


def get_pending_delete_job() -> dict[str, Any] | None:
    conn = get_connection()
    row = conn.execute(
        """SELECT dsj.id, dsj.scan_id,
                  ds.channel_ref, ds.channel_title
           FROM delete_scan_jobs dsj
           JOIN duplicate_scans ds ON ds.id = dsj.scan_id
           WHERE dsj.status='pending'
           ORDER BY dsj.created_at ASC
           LIMIT 1"""
    ).fetchone()
    return dict(row) if row else None


def start_delete_job(job_id: int) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE delete_scan_jobs SET status='running' WHERE id=?", (job_id,)
    )
    conn.commit()


def finish_delete_job(job_id: int, deleted_count: int) -> None:
    conn = get_connection()
    conn.execute(
        """UPDATE delete_scan_jobs
           SET status='done', deleted_count=?, completed_at=datetime('now')
           WHERE id=?""",
        (deleted_count, job_id),
    )
    conn.commit()


def fail_delete_job(job_id: int, error_msg: str) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE delete_scan_jobs SET status='failed', error_msg=? WHERE id=?",
        (error_msg, job_id),
    )
    conn.commit()


def get_latest_delete_job(scan_id: int) -> dict[str, Any] | None:
    conn = get_connection()
    row = conn.execute(
        """SELECT * FROM delete_scan_jobs
           WHERE scan_id=?
           ORDER BY created_at DESC
           LIMIT 1""",
        (scan_id,),
    ).fetchone()
    return dict(row) if row else None
