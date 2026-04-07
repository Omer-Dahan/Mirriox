"""Domain model dataclasses. Each has a from_row() classmethod for SQLite rows."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional


@dataclass
class Admin:
    id: int
    telegram_id: int
    username: Optional[str]
    added_at: str
    added_by: Optional[int]

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Admin":
        return cls(
            id=row["id"],
            telegram_id=row["telegram_id"],
            username=row["username"],
            added_at=row["added_at"],
            added_by=row["added_by"],
        )


@dataclass
class Source:
    id: int
    name: str
    channel_ref: str
    title: Optional[str]
    resolved_id: Optional[int]
    created_at: str
    validation_error: Optional[str] = None
    username: Optional[str] = None
    participants_count: Optional[int] = None
    about: Optional[str] = None
    verified: bool = False
    channel_type: Optional[str] = None
    total_messages: Optional[int] = None
    photos_count: Optional[int] = None
    videos_count: Optional[int] = None
    docs_count: Optional[int] = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Source":
        keys = row.keys()
        return cls(
            id=row["id"],
            name=row["name"],
            channel_ref=row["channel_ref"],
            title=row["title"],
            resolved_id=row["resolved_id"],
            created_at=row["created_at"],
            validation_error=row["validation_error"] if "validation_error" in keys else None,
            username=row["username"] if "username" in keys else None,
            participants_count=row["participants_count"] if "participants_count" in keys else None,
            about=row["about"] if "about" in keys else None,
            verified=bool(row["verified"]) if "verified" in keys else False,
            channel_type=row["channel_type"] if "channel_type" in keys else None,
            total_messages=row["total_messages"] if "total_messages" in keys else None,
            photos_count=row["photos_count"] if "photos_count" in keys else None,
            videos_count=row["videos_count"] if "videos_count" in keys else None,
            docs_count=row["docs_count"] if "docs_count" in keys else None,
        )

    def display(self) -> str:
        label = self.title or self.channel_ref
        if label == self.name:
            return self.name
        return f"{self.name} ({label})"


@dataclass
class Destination:
    id: int
    name: str
    channel_ref: str
    title: Optional[str]
    resolved_id: Optional[int]
    created_at: str
    validation_error: Optional[str] = None
    username: Optional[str] = None
    participants_count: Optional[int] = None
    about: Optional[str] = None
    verified: bool = False
    channel_type: Optional[str] = None
    total_messages: Optional[int] = None
    photos_count: Optional[int] = None
    videos_count: Optional[int] = None
    docs_count: Optional[int] = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Destination":
        keys = row.keys()
        return cls(
            id=row["id"],
            name=row["name"],
            channel_ref=row["channel_ref"],
            title=row["title"],
            resolved_id=row["resolved_id"],
            created_at=row["created_at"],
            validation_error=row["validation_error"] if "validation_error" in keys else None,
            username=row["username"] if "username" in keys else None,
            participants_count=row["participants_count"] if "participants_count" in keys else None,
            about=row["about"] if "about" in keys else None,
            verified=bool(row["verified"]) if "verified" in keys else False,
            channel_type=row["channel_type"] if "channel_type" in keys else None,
            total_messages=row["total_messages"] if "total_messages" in keys else None,
            photos_count=row["photos_count"] if "photos_count" in keys else None,
            videos_count=row["videos_count"] if "videos_count" in keys else None,
            docs_count=row["docs_count"] if "docs_count" in keys else None,
        )

    def display(self) -> str:
        label = self.title or self.channel_ref
        if label == self.name:
            return self.name
        return f"{self.name} ({label})"


@dataclass
class BlockedWord:
    id: int
    word: str
    added_at: str
    added_by: Optional[int]

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "BlockedWord":
        return cls(
            id=row["id"],
            word=row["word"],
            added_at=row["added_at"],
            added_by=row["added_by"],
        )


@dataclass
class Job:
    id: int
    name: str
    source_id: int
    destination_id: int
    mode: str  # all | date_range | id_range | single_id
    date_from: Optional[str]
    date_to: Optional[str]
    id_from: Optional[int]
    id_to: Optional[int]
    single_message_id: Optional[int]
    use_blocked_words: bool
    content_types: str  # comma-separated: text,image,video
    report_url: Optional[str]
    status: str
    created_at: str
    started_at: Optional[str]
    completed_at: Optional[str]
    last_updated_at: str
    total_messages: int
    copied_count: int
    skipped_count: int
    failed_count: int
    last_processed_id: Optional[int]
    retry_count: int
    max_retries: int
    next_retry_at: Optional[str]
    error_message: Optional[str]

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Job":
        return cls(
            id=row["id"],
            name=row["name"],
            source_id=row["source_id"],
            destination_id=row["destination_id"],
            mode=row["mode"],
            date_from=row["date_from"],
            date_to=row["date_to"],
            id_from=row["id_from"],
            id_to=row["id_to"],
            single_message_id=row["single_message_id"],
            use_blocked_words=bool(row["use_blocked_words"]),
            content_types=row["content_types"] if "content_types" in row.keys() else "text,image,video",
            report_url=row["report_url"] if "report_url" in row.keys() else None,
            status=row["status"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            last_updated_at=row["last_updated_at"],
            total_messages=row["total_messages"] or 0,
            copied_count=row["copied_count"] or 0,
            skipped_count=row["skipped_count"] or 0,
            failed_count=row["failed_count"] or 0,
            last_processed_id=row["last_processed_id"],
            retry_count=row["retry_count"] or 0,
            max_retries=row["max_retries"] or 3,
            next_retry_at=row["next_retry_at"],
            error_message=row["error_message"],
        )

    def is_active(self) -> bool:
        return self.status in ("pending", "running", "waiting_retry")

    def is_terminal(self) -> bool:
        return self.status in ("completed", "cancelled", "failed")


@dataclass
class CopiedMessage:
    id: int
    job_id: int
    source_message_id: int
    dest_message_id: Optional[int]
    status: str  # copied | skipped | failed
    skip_reason: Optional[str]
    processed_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "CopiedMessage":
        return cls(
            id=row["id"],
            job_id=row["job_id"],
            source_message_id=row["source_message_id"],
            dest_message_id=row["dest_message_id"],
            status=row["status"],
            skip_reason=row["skip_reason"],
            processed_at=row["processed_at"],
        )


@dataclass
class WorkerState:
    id: int
    status: str  # idle | running | stopped | error
    current_job_id: Optional[int]
    last_heartbeat: Optional[str]
    error_message: Optional[str]

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "WorkerState":
        return cls(
            id=row["id"],
            status=row["status"],
            current_job_id=row["current_job_id"],
            last_heartbeat=row["last_heartbeat"],
            error_message=row["error_message"],
        )


class MirrioxError(Exception):
    """Base exception for business logic errors."""


class ValidationError(MirrioxError):
    """Input validation failed. Message should be Hebrew-ready."""


class JobError(MirrioxError):
    """Job lifecycle rule violated."""
