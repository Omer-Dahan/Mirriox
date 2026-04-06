"""Core copy logic using Telethon. Executes a single job end-to-end."""
from __future__ import annotations

import logging
import random
from datetime import datetime
from typing import AsyncIterator, Optional

from telethon import TelegramClient
from telethon.errors import FloodWaitError, ChatWriteForbiddenError, ChannelPrivateError
from telethon.tl.functions.messages import ForwardMessagesRequest
from telethon.tl.types import (
    Message,
    MessageMediaUnsupported,
    DocumentAttributeFilename,
)

from app.models import Job
from app.repositories import job_repo, filter_repo, source_repo
from app.worker.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


class CopyEngine:
    """Executes a copy job using the provided Telethon client."""

    def __init__(self, client: TelegramClient) -> None:
        self._client = client
        self._rate_limiter = RateLimiter()

    async def run_job(self, job: Job) -> None:
        from app.repositories import state_repo
        settings = state_repo.get_settings_dict()
        self._rate_limiter.update_from_settings(settings)

        # Snapshot blocked words once at job start
        blocked_words: list[str] = []
        if job.use_blocked_words:
            blocked_words = filter_repo.get_word_strings()
            logger.info("Job #%d: %d blocked words loaded", job.id, len(blocked_words))

        src_rec = source_repo.get_source_by_id(job.source_id)
        dst_rec = source_repo.get_destination_by_id(job.destination_id)
        if not src_rec or not dst_rec:
            job_repo.update_status(job.id, "failed", error="מקור או יעד לא נמצאו")
            return

        try:
            from app.worker.worker_main import _get_entity_safe
            src_entity = await _get_entity_safe(
                self._client, str(src_rec.resolved_id or src_rec.channel_ref)
            )
            dst_entity = await _get_entity_safe(
                self._client, str(dst_rec.resolved_id or dst_rec.channel_ref)
            )
        except (ChannelPrivateError, ValueError) as e:
            job_repo.update_status(job.id, "failed", error=f"שגיאת גישה לערוץ: {e}")
            logger.error("Job #%d: entity resolution failed: %s", job.id, e)
            return

        # Save resolved IDs for future use
        if not src_rec.resolved_id:
            try:
                source_repo.update_source_resolved(
                    src_rec.id,
                    getattr(src_entity, "title", src_rec.channel_ref),
                    src_entity.id,
                )
            except Exception:
                pass

        if not dst_rec.resolved_id:
            try:
                source_repo.update_destination_resolved(
                    dst_rec.id,
                    getattr(dst_entity, "title", dst_rec.channel_ref),
                    dst_entity.id,
                )
            except Exception:
                pass

        # Build dedup set from DB
        already_done: set[int] = job_repo.get_copied_source_ids(job.id)
        logger.info(
            "Job #%d: resuming — %d already done, checkpoint=#%s",
            job.id, len(already_done), job.last_processed_id,
        )

        job_repo.mark_started(job.id)

        copied = job.copied_count
        skipped = job.skipped_count
        failed = job.failed_count

        try:
            async for msg in self._fetch_messages(job, src_entity):
                if msg is None or not hasattr(msg, "id"):
                    continue

                if msg.id in already_done:
                    continue

                status, skip_reason = await self._process_message(
                    job, msg, blocked_words, src_entity, dst_entity
                )

                job_repo.record_copied_message(
                    job_id=job.id,
                    source_message_id=msg.id,
                    dest_message_id=None,
                    status=status,
                    skip_reason=skip_reason,
                )
                already_done.add(msg.id)

                if status == "copied":
                    copied += 1
                elif status == "skipped":
                    skipped += 1
                else:
                    failed += 1

                job_repo.update_progress(job.id, copied, skipped, failed, msg.id)
                await self._rate_limiter.wait()

        except FloodWaitError:
            logger.warning("Job #%d: FloodWait encountered", job.id)
            job_repo.update_progress(job.id, copied, skipped, failed, job.last_processed_id or 0)
            raise

        except (ChatWriteForbiddenError, ChannelPrivateError) as e:
            logger.error("Job #%d: fatal access error: %s", job.id, e)
            job_repo.update_status(job.id, "failed", error=str(e))
            return

        except Exception as e:
            logger.exception("Job #%d: unexpected error: %s", job.id, e)
            raise

        job_repo.mark_completed(job.id)
        logger.info(
            "Job #%d completed: copied=%d skipped=%d failed=%d",
            job.id, copied, skipped, failed,
        )

    # ── Message fetching ───────────────────────────────────────────────────────

    async def _fetch_messages(
        self, job: Job, src_entity
    ) -> AsyncIterator[Message]:
        """Yield messages in ascending ID order (oldest first) for safe resume."""
        client = self._client
        min_id = job.last_processed_id or 0

        if job.mode == "all":
            async for msg in client.iter_messages(src_entity, reverse=True, min_id=min_id):
                yield msg

        elif job.mode == "id_range":
            id_from = max(job.id_from or 1, min_id + 1)
            id_to = job.id_to or 0
            async for msg in client.iter_messages(
                src_entity, reverse=True, min_id=id_from - 1, max_id=id_to + 1
            ):
                if id_from <= msg.id <= id_to:
                    yield msg

        elif job.mode == "date_range":
            date_from = _parse_date(job.date_from)
            date_to = _parse_date(job.date_to)
            async for msg in client.iter_messages(src_entity, reverse=True, min_id=min_id):
                if not msg.date:
                    continue
                msg_date = msg.date.replace(tzinfo=None)
                if date_from and msg_date < date_from:
                    continue
                if date_to and msg_date > date_to:
                    break
                yield msg

        elif job.mode == "single_id":
            if job.single_message_id and job.single_message_id > min_id:
                msg = await client.get_messages(src_entity, ids=job.single_message_id)
                if msg:
                    yield msg

    # ── Message processing ─────────────────────────────────────────────────────

    async def _process_message(
        self,
        job: Job,
        msg: Message,
        blocked_words: list[str],
        src_entity,
        dst_entity,
    ) -> tuple[str, Optional[str]]:
        """Copy one message. Returns (status, skip_reason)."""

        # Filter check
        if blocked_words and self._is_blocked(msg, blocked_words):
            logger.debug("Job #%d: msg #%d blocked by filter", job.id, msg.id)
            return "skipped", "blocked_word"

        # Supported type check
        if not self._is_supported_type(msg):
            logger.debug("Job #%d: msg #%d unsupported type", job.id, msg.id)
            return "skipped", "unsupported_type"

        # Skip empty service messages
        if not msg.text and not msg.media:
            return "skipped", "empty_message"

        try:
            await self._forward_without_credit(msg, src_entity, dst_entity)
            return "copied", None

        except FloodWaitError:
            raise

        except Exception as e:
            logger.warning("Job #%d: failed to copy msg #%d: %s", job.id, msg.id, e)
            return "failed", str(e)[:200]

    async def _forward_without_credit(
        self, msg: Message, src_entity, dst_entity
    ) -> None:
        """
        Forward a message to dst without 'Forwarded from' attribution.
        Uses ForwardMessagesRequest with drop_author=True — no download/upload needed.
        """
        await self._client(ForwardMessagesRequest(
            from_peer=src_entity,
            id=[msg.id],
            to_peer=dst_entity,
            drop_author=True,           # removes "Forwarded from X"
            random_id=[random.randint(0, 2**63)],
        ))

    def _is_blocked(self, msg: Message, blocked_words: list[str]) -> bool:
        text = (msg.text or "").lower()
        return any(word in text for word in blocked_words)

    def _is_supported_type(self, msg: Message) -> bool:
        if not msg.media:
            return True
        if isinstance(msg.media, MessageMediaUnsupported):
            return False
        type_name = msg.media.__class__.__name__
        if any(t in type_name for t in ("Poll", "Game", "Invoice", "GeoLive")):
            return False
        return True


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
    if not date_str:
        return None
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None
