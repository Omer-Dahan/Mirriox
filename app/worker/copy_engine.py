"""Core copy logic using Telethon. Executes a single job end-to-end."""
# pylint: disable=too-many-branches,too-many-statements,too-many-locals
from __future__ import annotations

import logging
import random
from datetime import datetime
from typing import AsyncIterator, Optional

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    ChatWriteForbiddenError,
    ChannelPrivateError,
    ChatForwardsRestrictedError,
)
from telethon.tl.functions.messages import ForwardMessagesRequest
from telethon.tl.types import (
    Message,
    MessageMediaUnsupported,
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
        group_media: bool = job.group_media

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
            from app.worker.telegram_utils import get_entity_safe
            src_entity = await get_entity_safe(
                self._client, str(src_rec.resolved_id or src_rec.channel_ref)
            )
            dst_entity = await get_entity_safe(
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
            except Exception:  # nosec B110 — best-effort cache update, non-fatal
                pass

        if not dst_rec.resolved_id:
            try:
                source_repo.update_destination_resolved(
                    dst_rec.id,
                    getattr(dst_entity, "title", dst_rec.channel_ref),
                    dst_entity.id,
                )
            except Exception:  # nosec B110 — best-effort cache update, non-fatal
                pass

        # Build dedup set from DB
        already_done: set[int] = job_repo.get_copied_source_ids(job.id)
        logger.info(
            "Job #%d: resuming — %d already done, checkpoint=#%s",
            job.id, len(already_done), job.last_processed_id,
        )

        # Detected once per job: if True, skip ForwardMessagesRequest entirely
        src_is_protected: bool = False

        job_repo.mark_started(job.id)

        copied = job.copied_count
        skipped = job.skipped_count
        failed = job.failed_count
        _last_progress_log = copied
        _msgs_since_pause_check = 0  # check for pause every 25 messages

        # Buffer for collecting media-group messages before forwarding them together
        pending_group: list[Message] = []
        current_group_id: Optional[int] = None

        # Buffer for grouping individually-sent photos/videos into albums (group_media feature)
        solo_media_buffer: list[Message] = []

        async def flush_solo_media() -> bool:
            """Flush solo media buffer. Returns True if job is now paused (caller must stop)."""
            nonlocal copied, skipped, failed, solo_media_buffer, src_is_protected
            if not solo_media_buffer:
                return False
            buffer = solo_media_buffer[:]
            solo_media_buffer = []
            last_id = buffer[-1].id

            # Apply per-message filters; collect messages that should be sent
            allowed_types: set[str] = set((job.content_types or "text,image,video").split(","))
            to_send: list[Message] = []
            for m in buffer:
                if not job.copy_text and (not m.media or isinstance(m.media, MessageMediaUnsupported)):
                    job_repo.record_copied_message(job.id, m.id, None, "skipped", "text_stripped_empty")
                    already_done.add(m.id)
                    skipped += 1
                    continue
                if blocked_words and self._is_blocked(m, blocked_words):
                    job_repo.record_copied_message(job.id, m.id, None, "skipped", "blocked_word")
                    already_done.add(m.id)
                    skipped += 1
                    continue
                if allowed_types != {"image", "text", "video"}:
                    msg_type = self._get_content_type(m)
                    if msg_type != "other" and msg_type not in allowed_types:
                        job_repo.record_copied_message(job.id, m.id, None, "skipped", f"content_type:{msg_type}")
                        already_done.add(m.id)
                        skipped += 1
                        continue
                to_send.append(m)

            if not to_send:
                job_repo.update_progress(job.id, copied, skipped, failed, last_id)
                return False

            async def _send_single(m: Message) -> tuple[str, str | None]:
                """Forward one message; returns (status, reason). Updates src_is_protected."""
                nonlocal src_is_protected
                try:
                    if src_is_protected:
                        await self._send_as_copy(m, dst_entity, copy_text=job.copy_text)
                    else:
                        if job.copy_text:
                            await self._client(ForwardMessagesRequest(
                                from_peer=src_entity,
                                id=[m.id],
                                to_peer=dst_entity,
                                drop_author=True,
                                random_id=[random.randint(0, 2**63)],  # nosec B311
                            ))
                        else:
                            await self._client.send_file(dst_entity, m.media, caption="")
                    return "copied", None
                except ChatForwardsRestrictedError:
                    src_is_protected = True
                    try:
                        await self._send_as_copy(m, dst_entity, copy_text=job.copy_text)
                        return "copied", None
                    except FloodWaitError:
                        raise
                    except Exception as e:
                        return "failed", str(e)[:200]
                except FloodWaitError:
                    raise
                except Exception as e:
                    return "failed", str(e)[:200]

            if len(to_send) == 1:
                st, reason = await _send_single(to_send[0])
                if st == "copied":
                    copied += 1
                else:
                    failed += 1
                job_repo.record_copied_message(job.id, to_send[0].id, None, st, reason)
                already_done.add(to_send[0].id)
            else:
                # Try fast album send via file refs; fall back to individual forwards (not download)
                album_ok = False
                try:
                    await self._send_group_by_ref(to_send, dst_entity, copy_text=job.copy_text)
                    album_ok = True
                    logger.info(
                        "Job #%d: grouped %d solo media into album (ids=%s)",
                        job.id, len(to_send), [m.id for m in to_send],
                    )
                except FloodWaitError:
                    raise
                except Exception as ref_err:
                    logger.warning(
                        "Job #%d: album ref-send failed (%s) — falling back to %d individual sends",
                        job.id, ref_err, len(to_send),
                    )

                if album_ok:
                    for m in to_send:
                        job_repo.record_copied_message(job.id, m.id, None, "copied", None)
                        already_done.add(m.id)
                        copied += 1
                else:
                    for m in to_send:
                        st, reason = await _send_single(m)
                        if st == "copied":
                            copied += 1
                        else:
                            failed += 1
                            logger.warning(
                                "Job #%d: failed to send msg #%d individually: %s",
                                job.id, m.id, reason,
                            )
                        job_repo.record_copied_message(job.id, m.id, None, st, reason)
                        already_done.add(m.id)

            job_repo.update_progress(job.id, copied, skipped, failed, last_id)
            if job_repo.is_paused(job.id):
                logger.info("Job #%d: pause requested after media flush at #%d", job.id, last_id)
                return True
            await self._rate_limiter.wait()
            return False

        async def flush_group() -> bool:
            """Flush pending album group. Returns True if job is now paused (caller must stop)."""
            nonlocal copied, skipped, failed, pending_group, current_group_id, src_is_protected
            if not pending_group:
                return False
            group = pending_group
            pending_group = []
            current_group_id = None

            # Skip group if the first message was already processed
            if group[0].id in already_done:
                return False

            statuses, src_is_protected = await self._process_group(
                job, group, blocked_words, src_entity, dst_entity, src_is_protected
            )

            last_id = group[-1].id
            for msg, (status, skip_reason) in zip(group, statuses):
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

            job_repo.update_progress(job.id, copied, skipped, failed, last_id)
            if job_repo.is_paused(job.id):
                logger.info("Job #%d: pause requested after album flush at #%d", job.id, last_id)
                return True
            await self._rate_limiter.wait()
            return False

        try:
            async for msg in self._fetch_messages(job, src_entity):
                if msg is None or not hasattr(msg, "id"):
                    continue

                if msg.grouped_id:
                    # Existing album: flush solo buffer first, then accumulate
                    if group_media:
                        if await flush_solo_media():
                            return
                    if msg.grouped_id == current_group_id:
                        pending_group.append(msg)
                    else:
                        if await flush_group():
                            return
                        current_group_id = msg.grouped_id
                        pending_group = [msg]
                else:
                    # Individual message: flush any pending album group first
                    if await flush_group():
                        return

                    if group_media and self._is_groupable(msg):
                        # Add to solo buffer (skip if already done)
                        if msg.id not in already_done:
                            solo_media_buffer.append(msg)
                        if len(solo_media_buffer) >= 10:
                            if await flush_solo_media():
                                return
                    else:
                        # Non-groupable: flush solo buffer, then process normally
                        if group_media:
                            if await flush_solo_media():
                                return

                        if msg.id in already_done:
                            continue

                        status, skip_reason, src_is_protected = await self._process_message(
                            job, msg, blocked_words, src_entity, dst_entity, src_is_protected
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
                        if copied - _last_progress_log >= 50:
                            _last_progress_log = copied
                            logger.info(
                                "Job #%d progress: copied=%d skipped=%d failed=%d last_id=#%d",
                                job.id, copied, skipped, failed, msg.id,
                            )
                        _msgs_since_pause_check += 1
                        if _msgs_since_pause_check >= 25:
                            _msgs_since_pause_check = 0
                            if job_repo.is_paused(job.id):
                                logger.info("Job #%d: pause requested — stopping at msg #%d", job.id, msg.id)
                                job_repo.update_progress(job.id, copied, skipped, failed, msg.id)
                                return
                        await self._rate_limiter.wait()

            # Flush any remaining buffers at end of stream
            if await flush_group():
                return
            if group_media:
                if await flush_solo_media():
                    return

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

        # Generate Telegraph report for notable (failed / unexpected-skipped) messages
        report_msgs = job_repo.get_report_messages(job.id)
        if not report_msgs:
            logger.info("Job #%d: no notable messages — Telegraph report skipped", job.id)
        if report_msgs:
            from app.services import telegraph_service
            url = await telegraph_service.create_report(
                job.id, report_msgs, src_rec.resolved_id, src_rec.channel_ref
            )
            if url:
                job_repo.save_report_url(job.id, url)
                logger.info("Job #%d Telegraph report: %s", job.id, url)

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

    async def _process_group(
        self,
        job: Job,
        group: list[Message],
        blocked_words: list[str],
        src_entity,
        dst_entity,
        src_is_protected: bool,
    ) -> tuple[list[tuple[str, Optional[str]]], bool]:
        """
        Forward a media-group (album) as a single batch.
        Returns (statuses, src_is_protected) — one status per message.
        src_is_protected is updated to True if the channel turns out to be protected.
        """
        # Check filter: if ANY message triggers a blocked word, skip the whole group
        if blocked_words and any(self._is_blocked(m, blocked_words) for m in group):
            logger.debug("Job #%d: group %d blocked by filter", job.id, group[0].grouped_id)
            return [("skipped", "blocked_word")] * len(group), src_is_protected

        # Content type filter for album (albums are photos → image type)
        allowed_types: set[str] = set((job.content_types or "text,image,video").split(","))
        if allowed_types != {"image", "text", "video"}:
            group_type = self._get_content_type(group[0])
            if group_type != "other" and group_type not in allowed_types:
                logger.debug("Job #%d: album group=%s skipped (type=%s)", job.id, group[0].grouped_id, group_type)
                return [("skipped", f"content_type:{group_type}")] * len(group), src_is_protected

        if src_is_protected:
            # Channel already known to be protected — skip straight to download+upload
            try:
                await self._send_group_as_copy(group, dst_entity, copy_text=job.copy_text)
                return [("copied", None)] * len(group), src_is_protected
            except FloodWaitError:
                raise
            except Exception as e:
                logger.warning("Job #%d: download+upload album failed: %s", job.id, e)
                return [("failed", str(e)[:200])] * len(group), src_is_protected

        ids = [m.id for m in group]
        try:
            if job.copy_text:
                await self._client(ForwardMessagesRequest(
                    from_peer=src_entity,
                    id=ids,
                    to_peer=dst_entity,
                    drop_author=True,
                    random_id=[random.randint(0, 2**63) for _ in ids],  # nosec B311
                ))
            else:
                await self._send_group_by_ref(group, dst_entity, copy_text=False)
            logger.info(
                "Job #%d: forwarded album of %d items (ids=%s)",
                job.id, len(ids), ids,
            )
            return [("copied", None)] * len(group), src_is_protected

        except ChatForwardsRestrictedError:
            src_is_protected = True
            logger.info(
                "Job #%d: source channel is protected — switching to download+upload for all remaining messages",
                job.id,
            )
            try:
                await self._send_group_as_copy(group, dst_entity)
                return [("copied", None)] * len(group), src_is_protected
            except FloodWaitError:
                raise
            except Exception as e:
                logger.warning("Job #%d: download+upload album failed: %s", job.id, e)
                return [("failed", str(e)[:200])] * len(group), src_is_protected

        except FloodWaitError:
            raise

        except Exception as e:
            logger.warning(
                "Job #%d: failed to forward album (ids=%s): %s",
                job.id, [m.id for m in group], e,
            )
            return [("failed", str(e)[:200])] * len(group), src_is_protected

    async def _process_message(
        self,
        job: Job,
        msg: Message,
        blocked_words: list[str],
        src_entity,
        dst_entity,
        src_is_protected: bool,
    ) -> tuple[str, Optional[str], bool]:
        """Copy one message. Returns (status, skip_reason, src_is_protected)."""

        # Filter check
        if blocked_words and self._is_blocked(msg, blocked_words):
            logger.debug("Job #%d: msg #%d blocked by filter", job.id, msg.id)
            return "skipped", "blocked_word", src_is_protected

        # Content type filter
        allowed_types: set[str] = set((job.content_types or "text,image,video").split(","))
        if allowed_types != {"image", "text", "video"}:
            msg_type = self._get_content_type(msg)
            if msg_type != "other" and msg_type not in allowed_types:
                logger.debug("Job #%d: msg #%d skipped (type=%s not in %s)", job.id, msg.id, msg_type, allowed_types)
                return "skipped", f"content_type:{msg_type}", src_is_protected

        # Supported type check
        if not self._is_supported_type(msg):
            logger.debug("Job #%d: msg #%d unsupported type", job.id, msg.id)
            return "skipped", "unsupported_type", src_is_protected

        # Skip empty service messages
        if not msg.text and not msg.media:
            return "skipped", "empty_message", src_is_protected

        if not job.copy_text and (not msg.media or isinstance(msg.media, MessageMediaUnsupported)):
            return "skipped", "text_stripped_empty", src_is_protected

        if src_is_protected:
            # Channel already known to be protected — skip straight to download+upload
            try:
                await self._send_as_copy(msg, dst_entity, copy_text=job.copy_text)
                return "copied", None, src_is_protected
            except FloodWaitError:
                raise
            except Exception as e:
                logger.warning("Job #%d: failed to copy msg #%d: %s", job.id, msg.id, e)
                return "failed", str(e)[:200], src_is_protected

        try:
            if job.copy_text:
                await self._client(ForwardMessagesRequest(
                    from_peer=src_entity,
                    id=[msg.id],
                    to_peer=dst_entity,
                    drop_author=True,
                    random_id=[random.randint(0, 2**63)],  # nosec B311
                ))
            else:
                await self._client.send_file(dst_entity, msg.media, caption="")
            return "copied", None, src_is_protected

        except ChatForwardsRestrictedError:
            src_is_protected = True
            logger.info(
                "Job #%d: source channel is protected — switching to download+upload for all remaining messages",
                job.id,
            )
            try:
                await self._send_as_copy(msg, dst_entity, copy_text=job.copy_text)
                return "copied", None, src_is_protected
            except FloodWaitError:
                raise
            except Exception as e:
                logger.warning("Job #%d: failed to copy msg #%d: %s", job.id, msg.id, e)
                return "failed", str(e)[:200], src_is_protected

        except FloodWaitError:
            raise

        except Exception as e:
            logger.warning("Job #%d: failed to copy msg #%d: %s", job.id, msg.id, e)
            return "failed", str(e)[:200], src_is_protected

    async def _forward_without_credit(
        self, msg: Message, src_entity, dst_entity
    ) -> None:
        """Forward a single message without attribution (only used externally)."""
        await self._client(ForwardMessagesRequest(
            from_peer=src_entity,
            id=[msg.id],
            to_peer=dst_entity,
            drop_author=True,
            random_id=[random.randint(0, 2**63)],  # nosec B311
        ))

    async def _send_as_copy(self, msg: Message, dst_entity, copy_text: bool = True) -> None:
        """Download and re-upload a single message (used when forwarding is blocked)."""
        text = msg.text if copy_text else ""

        if not msg.media or isinstance(msg.media, MessageMediaUnsupported):
            if text:
                await self._client.send_message(dst_entity, text)
            return

        file_bytes: Optional[bytes] = await self._client.download_media(msg, file=bytes)
        if file_bytes is None:
            if text:
                await self._client.send_message(dst_entity, text)
            return

        await self._client.send_file(dst_entity, file_bytes, caption=text or None)

    async def _send_group_by_ref(self, group: list[Message], dst_entity, copy_text: bool = True) -> None:
        """
        Send a media album using existing Telegram file references — no download needed.
        Falls back to _send_group_as_copy if references are expired or inaccessible.
        """
        from telethon.tl.functions.messages import SendMultiMediaRequest
        from telethon.tl.types import (
            InputSingleMedia, InputMediaPhoto, InputMediaDocument,
            InputPhoto, InputDocument,
        )

        multi: list = []
        for m in group:
            if not m.media or isinstance(m.media, MessageMediaUnsupported):
                continue
            type_name = m.media.__class__.__name__
            caption = m.text or ""
            if type_name == "MessageMediaPhoto":
                p = m.media.photo
                input_media = InputMediaPhoto(
                    id=InputPhoto(id=p.id, access_hash=p.access_hash, file_reference=p.file_reference)
                )
            elif type_name == "MessageMediaDocument":
                d = m.media.document
                if not d:
                    continue
                # Only regular videos in albums — skip GIFs, round notes, plain docs
                is_regular_video = any(
                    attr.__class__.__name__ == "DocumentAttributeVideo"
                    and not getattr(attr, "round_message", False)
                    for attr in d.attributes
                )
                if not is_regular_video:
                    continue
                input_media = InputMediaDocument(
                    id=InputDocument(id=d.id, access_hash=d.access_hash, file_reference=d.file_reference)
                )
            else:
                continue
            multi.append(InputSingleMedia(
                media=input_media,
                random_id=random.randint(0, 2**63),  # nosec B311
                message=caption if copy_text else "",
            ))

        if not multi:
            return

        await self._client(SendMultiMediaRequest(peer=dst_entity, multi_media=multi))

    async def _send_group_as_copy(self, group: list[Message], dst_entity, copy_text: bool = True) -> None:
        """
        Send a media group by trying file references first (fast), then
        falling back to download+reupload (slow, used when refs are expired).
        """
        try:
            await self._send_group_by_ref(group, dst_entity, copy_text=copy_text)
            return
        except FloodWaitError:
            raise
        except Exception as e:
            logger.warning("Job: send_group_by_ref failed (%s) — falling back to download+upload", e)

        # Fallback: download and re-upload
        files: list[bytes] = []
        captions: list[str] = []
        for m in group:
            if m.media and not isinstance(m.media, MessageMediaUnsupported):
                data: Optional[bytes] = await self._client.download_media(m, file=bytes)
                if data:
                    files.append(data)
                    captions.append(m.text if copy_text else "")

        if not files:
            text = next((m.text for m in group if m.text), None) if copy_text else None
            if text:
                await self._client.send_message(dst_entity, text)
            return

        await self._client.send_file(dst_entity, files, caption=captions)

    def _is_blocked(self, msg: Message, blocked_words: list[str]) -> bool:
        text = (msg.text or "").lower()
        return any(word in text for word in blocked_words)

    @staticmethod
    def _is_groupable(msg: Message) -> bool:
        """True if this message can be added to a Telegram media album.
        Only photos and regular videos — NOT GIFs/animations or round-video notes,
        which cause MEDIA_INVALID in SendMultiMediaRequest."""
        if not msg.media or isinstance(msg.media, MessageMediaUnsupported):
            return False
        type_name = msg.media.__class__.__name__
        if type_name == "MessageMediaPhoto":
            return True
        if type_name == "MessageMediaDocument":
            doc = msg.media.document
            if doc:
                for attr in doc.attributes:
                    if attr.__class__.__name__ == "DocumentAttributeVideo":
                        # Exclude round-video notes (video_note=True / round_message=True)
                        if not getattr(attr, "round_message", False):
                            return True
        return False

    @staticmethod
    def _get_content_type(msg: Message) -> str:
        """Classify message as 'text', 'image', 'video', or 'other'."""
        if not msg.media or isinstance(msg.media, MessageMediaUnsupported):
            return "text"
        type_name = msg.media.__class__.__name__
        if type_name == "MessageMediaPhoto":
            return "image"
        if type_name == "MessageMediaDocument":
            doc = msg.media.document
            if doc:
                for attr in doc.attributes:
                    cls = attr.__class__.__name__
                    if cls == "DocumentAttributeSticker":
                        return "image"
                    if cls in ("DocumentAttributeVideo", "DocumentAttributeAnimated"):
                        return "video"
        return "other"

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
