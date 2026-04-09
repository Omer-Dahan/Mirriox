"""
Duplicate scan engine: scans a channel for duplicate media files
and optionally deletes duplicate messages via the userbot.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.functions.messages import GetHistoryRequest

from app.repositories import scan_repo
from app.worker.telegram_utils import get_entity_safe

logger = logging.getLogger(__name__)

_PROGRESS_INTERVAL  = 100  # update DB progress every N messages
_DELETE_BATCH_SIZE  = 100  # Telegram allows up to 100 deletions per call
_DELETE_SLEEP_S     = 1.5  # pause between delete batches
_MSG_SLEEP_S        = 0.5  # pause between each fetched message
_BATCH_SLEEP_S      = 10.0 # longer pause every _BATCH_EVERY messages
_BATCH_EVERY        = 50   # messages between batch pauses


class ScanEngine:
    def __init__(self, client: TelegramClient) -> None:
        self._client = client

    # -----------------------------------------------------------------------
    # Public entry points
    # -----------------------------------------------------------------------

    async def run_scan(self, scan_id: int, source_id: int, channel_ref: str) -> None:
        """Iterate all messages in the channel and record media IDs for dedup analysis."""
        scan_repo.start_scan(scan_id)
        logger.info("Scan #%d: starting for source_id=%d ref=%s", scan_id, source_id, channel_ref)

        try:
            entity = await get_entity_safe(self._client, channel_ref)
            if entity is None:
                scan_repo.fail_scan(scan_id, f"Could not resolve channel: {channel_ref}")
                return

            # Get total message count for progress tracking
            total = await self._get_total_messages(entity)
            scan_repo.update_progress(scan_id, 0, total)

            scanned = 0
            from app.db import get_connection
            conn = get_connection()

            iter_obj = self._client.iter_messages(entity, reverse=True)
            while True:
                try:
                    msg = await iter_obj.__anext__()
                except StopAsyncIteration:
                    break
                except FloodWaitError as e:
                    wait_s = e.seconds + 5
                    logger.warning("Scan #%d: FloodWait %ds — sleeping", scan_id, wait_s)
                    await asyncio.sleep(wait_s)
                    continue

                if not msg or not msg.media:
                    scanned += 1
                    await asyncio.sleep(_MSG_SLEEP_S)
                    if scanned % _BATCH_EVERY == 0:
                        scan_repo.update_progress(scan_id, scanned, total)
                        await asyncio.sleep(_BATCH_SLEEP_S)
                    continue

                media_id, media_type, file_size, mime_type = self._extract_media_info(msg)
                if media_id is None:
                    scanned += 1
                    await asyncio.sleep(_MSG_SLEEP_S)
                    if scanned % _BATCH_EVERY == 0:
                        scan_repo.update_progress(scan_id, scanned, total)
                        await asyncio.sleep(_BATCH_SLEEP_S)
                    continue

                msg_date = msg.date.strftime("%Y-%m-%d %H:%M:%S") if msg.date else ""
                scan_repo.insert_item(
                    scan_id=scan_id,
                    message_id=msg.id,
                    media_id=media_id,
                    media_type=media_type,
                    file_size=file_size,
                    mime_type=mime_type,
                    msg_date=msg_date,
                )

                scanned += 1
                await asyncio.sleep(_MSG_SLEEP_S)
                if scanned % _BATCH_EVERY == 0:
                    conn.commit()
                    scan_repo.update_progress(scan_id, scanned, total)
                    await asyncio.sleep(_BATCH_SLEEP_S)

            # Final commit for any remaining inserts
            conn.commit()
            scan_repo.update_progress(scan_id, scanned, total)

            # Compute duplicate groups
            groups = scan_repo.get_duplicate_groups(scan_id)
            wasted = sum(g["total_count"] - 1 for g in groups)

            # Build Telegraph report if there are duplicates
            report_url: str | None = None
            if groups:
                report_url = await self._build_report(scan_id, groups, channel_ref)

            scan_repo.finish_scan(scan_id, len(groups), wasted, report_url)
            logger.info(
                "Scan #%d done: scanned=%d groups=%d wasted=%d",
                scan_id, scanned, len(groups), wasted,
            )

        except asyncio.CancelledError:
            scan_repo.fail_scan(scan_id, "Scan cancelled")
            raise
        except Exception as exc:
            logger.exception("Scan #%d failed: %s", scan_id, exc)
            scan_repo.fail_scan(scan_id, str(exc)[:500])

    async def run_delete(self, delete_job_id: int, scan_id: int, channel_ref: str) -> None:
        """Delete all duplicate messages (keeping the oldest in each group)."""
        scan_repo.start_delete_job(delete_job_id)
        logger.info("Delete job #%d: starting (scan_id=%d)", delete_job_id, scan_id)

        try:
            entity = await get_entity_safe(self._client, channel_ref)
            if entity is None:
                scan_repo.fail_delete_job(delete_job_id, f"Could not resolve channel: {channel_ref}")
                return

            groups = scan_repo.get_duplicate_groups(scan_id)
            if not groups:
                scan_repo.finish_delete_job(delete_job_id, 0)
                return

            # Collect message IDs to delete (skip oldest per group)
            ids_to_delete: list[int] = []
            for group in groups:
                items = scan_repo.get_items_for_media(scan_id, group["media_id"])
                # items are sorted by msg_date ASC — keep first, delete rest
                for item in items[1:]:
                    ids_to_delete.append(item["message_id"])

            # Delete in batches
            total_deleted = 0
            for i in range(0, len(ids_to_delete), _DELETE_BATCH_SIZE):
                batch = ids_to_delete[i : i + _DELETE_BATCH_SIZE]
                try:
                    await self._client.delete_messages(entity, batch)
                    total_deleted += len(batch)
                    logger.info(
                        "Delete job #%d: deleted batch %d-%d (%d total)",
                        delete_job_id, i, i + len(batch), total_deleted,
                    )
                except Exception as exc:
                    logger.warning("Delete job #%d: batch error: %s", delete_job_id, exc)
                await asyncio.sleep(_DELETE_SLEEP_S)

            scan_repo.finish_delete_job(delete_job_id, total_deleted)
            logger.info("Delete job #%d done: deleted %d messages", delete_job_id, total_deleted)

        except asyncio.CancelledError:
            scan_repo.fail_delete_job(delete_job_id, "Delete cancelled")
            raise
        except Exception as exc:
            logger.exception("Delete job #%d failed: %s", delete_job_id, exc)
            scan_repo.fail_delete_job(delete_job_id, str(exc)[:500])

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    async def _get_total_messages(self, entity: Any) -> int:
        """Return the total number of messages in the channel (best-effort)."""
        for attempt in range(3):
            try:
                result = await self._client(GetHistoryRequest(
                    peer=entity,
                    offset_id=0,
                    offset_date=None,
                    add_offset=0,
                    limit=1,
                    max_id=0,
                    min_id=0,
                    hash=0,
                ))
                return getattr(result, "count", 0) or 0
            except FloodWaitError as e:
                wait_s = e.seconds + 5
                logger.warning("_get_total_messages: FloodWait %ds (attempt %d)", wait_s, attempt + 1)
                await asyncio.sleep(wait_s)
            except Exception as exc:
                logger.warning("Could not fetch total message count: %s", exc)
                return 0
        return 0

    @staticmethod
    def _extract_media_info(msg: Any) -> tuple[int | None, str, int | None, str | None]:
        """
        Return (media_id, media_type, file_size, mime_type) for a message, or
        (None, '', None, None) if the message has no trackable media.
        """
        media = msg.media
        type_name = type(media).__name__

        if type_name == "MessageMediaDocument":
            doc = getattr(media, "document", None)
            if doc is None:
                return None, "", None, None
            return doc.id, "document", getattr(doc, "size", None), getattr(doc, "mime_type", None)

        if type_name == "MessageMediaPhoto":
            photo = getattr(media, "photo", None)
            if photo is None:
                return None, "", None, None
            # Estimate size from largest PhotoSize
            size = None
            for s in getattr(photo, "sizes", []):
                sz = getattr(s, "size", None)
                if sz and (size is None or sz > size):
                    size = sz
            return photo.id, "photo", size, "image/jpeg"

        return None, "", None, None

    async def _build_report(
        self,
        scan_id: int,
        groups: list[dict[str, Any]],
        channel_ref: str,
    ) -> str | None:
        """Build a Telegraph report with links to duplicate messages."""
        from app.services import telegraph_service
        from app.repositories.scan_repo import get_items_for_media

        # Resolve channel username for t.me links
        from app.db import get_connection
        conn = get_connection()
        row = conn.execute(
            "SELECT username, resolved_id FROM sources WHERE channel_ref=? LIMIT 1",
            (channel_ref,),
        ).fetchone()
        username = row["username"] if row else None
        resolved_id = row["resolved_id"] if row else None

        return await telegraph_service.create_duplicates_report(
            scan_id=scan_id,
            groups=groups,
            get_items_fn=lambda media_id: get_items_for_media(scan_id, media_id),
            username=username,
            resolved_id=resolved_id,
        )
