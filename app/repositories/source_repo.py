"""CRUD for sources and destinations tables."""
from __future__ import annotations

from typing import Optional
import app.db as db
from app.models import Source, Destination


# ── Sources ────────────────────────────────────────────────────────────────────

def get_all_sources() -> list[Source]:
    conn = db.get_connection()
    rows = conn.execute(
        "SELECT * FROM sources ORDER BY name ASC"
    ).fetchall()
    return [Source.from_row(r) for r in rows]


def get_source_by_id(source_id: int) -> Optional[Source]:
    conn = db.get_connection()
    row = conn.execute(
        "SELECT * FROM sources WHERE id = ?", (source_id,)
    ).fetchone()
    return Source.from_row(row) if row else None


def get_source_by_ref(channel_ref: str) -> Optional[Source]:
    conn = db.get_connection()
    row = conn.execute(
        "SELECT * FROM sources WHERE channel_ref = ?", (channel_ref,)
    ).fetchone()
    return Source.from_row(row) if row else None


def add_source(name: str, channel_ref: str) -> Source:
    conn = db.get_connection()
    cur = conn.execute(
        "INSERT INTO sources(name, channel_ref) VALUES(?,?)",
        (name, channel_ref),
    )
    conn.commit()
    return get_source_by_id(cur.lastrowid)  # type: ignore[arg-type]


def update_source_name(source_id: int, name: str) -> None:
    conn = db.get_connection()
    conn.execute("UPDATE sources SET name = ? WHERE id = ?", (name, source_id))
    conn.commit()


def update_source_resolved(
    source_id: int, title: str, resolved_id: int
) -> None:
    conn = db.get_connection()
    conn.execute(
        "UPDATE sources SET title = ?, resolved_id = ? WHERE id = ?",
        (title, resolved_id, source_id),
    )
    conn.commit()


def update_destination_resolved(
    dest_id: int, title: str, resolved_id: int
) -> None:
    conn = db.get_connection()
    conn.execute(
        "UPDATE destinations SET title = ?, resolved_id = ? WHERE id = ?",
        (title, resolved_id, dest_id),
    )
    conn.commit()


def set_source_validation_error(source_id: int, error: Optional[str]) -> None:
    conn = db.get_connection()
    conn.execute(
        "UPDATE sources SET validation_error = ? WHERE id = ?",
        (error, source_id),
    )
    conn.commit()


def get_unresolved_sources() -> list[Source]:
    conn = db.get_connection()
    rows = conn.execute(
        "SELECT * FROM sources WHERE resolved_id IS NULL"
    ).fetchall()
    return [Source.from_row(r) for r in rows]


def is_source_in_use(source_id: int) -> bool:
    conn = db.get_connection()
    row = conn.execute(
        "SELECT 1 FROM jobs WHERE source_id = ? LIMIT 1", (source_id,)
    ).fetchone()
    return row is not None


def delete_source(source_id: int) -> bool:
    conn = db.get_connection()
    cur = conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    conn.commit()
    return cur.rowcount > 0


def update_destination_name(dest_id: int, name: str) -> None:
    conn = db.get_connection()
    conn.execute("UPDATE destinations SET name = ? WHERE id = ?", (name, dest_id))
    conn.commit()


# ── Destinations ───────────────────────────────────────────────────────────────

def get_all_destinations() -> list[Destination]:
    conn = db.get_connection()
    rows = conn.execute(
        "SELECT * FROM destinations ORDER BY name ASC"
    ).fetchall()
    return [Destination.from_row(r) for r in rows]


def get_destination_by_id(dest_id: int) -> Optional[Destination]:
    conn = db.get_connection()
    row = conn.execute(
        "SELECT * FROM destinations WHERE id = ?", (dest_id,)
    ).fetchone()
    return Destination.from_row(row) if row else None


def get_destination_by_ref(channel_ref: str) -> Optional[Destination]:
    conn = db.get_connection()
    row = conn.execute(
        "SELECT * FROM destinations WHERE channel_ref = ?", (channel_ref,)
    ).fetchone()
    return Destination.from_row(row) if row else None


def add_destination(name: str, channel_ref: str) -> Destination:
    conn = db.get_connection()
    cur = conn.execute(
        "INSERT INTO destinations(name, channel_ref) VALUES(?,?)",
        (name, channel_ref),
    )
    conn.commit()
    return get_destination_by_id(cur.lastrowid)  # type: ignore[arg-type]


def update_destination_resolved(
    dest_id: int, title: str, resolved_id: int
) -> None:
    conn = db.get_connection()
    conn.execute(
        "UPDATE destinations SET title = ?, resolved_id = ? WHERE id = ?",
        (title, resolved_id, dest_id),
    )
    conn.commit()


def set_dest_validation_error(dest_id: int, error: Optional[str]) -> None:
    conn = db.get_connection()
    conn.execute(
        "UPDATE destinations SET validation_error = ? WHERE id = ?",
        (error, dest_id),
    )
    conn.commit()


def get_unresolved_destinations() -> list[Destination]:
    conn = db.get_connection()
    rows = conn.execute(
        "SELECT * FROM destinations WHERE resolved_id IS NULL"
    ).fetchall()
    return [Destination.from_row(r) for r in rows]


def is_destination_in_use(dest_id: int) -> bool:
    conn = db.get_connection()
    row = conn.execute(
        "SELECT 1 FROM jobs WHERE destination_id = ? LIMIT 1", (dest_id,)
    ).fetchone()
    return row is not None


def delete_destination(dest_id: int) -> bool:
    conn = db.get_connection()
    cur = conn.execute(
        "DELETE FROM destinations WHERE id = ?", (dest_id,)
    )
    conn.commit()
    return cur.rowcount > 0
