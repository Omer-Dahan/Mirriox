"""
Userbot worker: startup recovery, polling loop, job execution.
Run as: python main.py worker
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import signal
from datetime import datetime, timedelta

from telethon import TelegramClient
from telethon.errors import FloodWaitError

from app.config import Config
from app.repositories import job_repo, state_repo
from app.worker.copy_engine import CopyEngine

logger = logging.getLogger(__name__)

_shutdown_event: asyncio.Event | None = None
_resolve_trigger: asyncio.Event | None = None


def signal_resolve_now() -> None:
    """Called from bot handlers to wake the worker for immediate channel resolution."""
    global _resolve_trigger
    if _resolve_trigger is not None:
        _resolve_trigger.set()


def run(config: Config) -> None:
    """Entry point for the worker process (blocking)."""
    asyncio.run(_async_run(config))


# Expose for combined mode in main.py
async def run_async(config: Config) -> None:
    await _async_run(config)


async def _async_run(config: Config) -> None:
    global _shutdown_event, _resolve_trigger
    _shutdown_event = asyncio.Event()
    _resolve_trigger = asyncio.Event()

    # Register signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_shutdown)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler for all signals
            pass

    # Ensure session directory exists
    session_dir = os.path.dirname(config.TELETHON_SESSION)
    if session_dir:
        os.makedirs(session_dir, exist_ok=True)

    client = TelegramClient(
        config.TELETHON_SESSION,
        config.TELETHON_API_ID,
        config.TELETHON_API_HASH,
        flood_sleep_threshold=0,  # Never auto-sleep — always raise FloodWaitError so we can log and requeue
    )

    logger.info("Connecting to Telegram as userbot...")
    await client.connect()

    if not await client.is_user_authorized():
        logger.error(
            "Userbot session is not authorized. "
            "Run: python main.py setup"
        )
        await client.disconnect()
        return

    me = await client.get_me()
    logger.info("Userbot authenticated as: %s (id=%s)", getattr(me, "username", "?"), getattr(me, "id", "?"))

    _startup_recovery()

    state_repo.set_worker_status("idle")
    logger.info("Worker ready. Polling for jobs every %ds...", config.WORKER_POLL_INTERVAL_S)

    engine = CopyEngine(client)

    try:
        await _poll_loop(config, engine, client)
    finally:
        state_repo.set_worker_status("stopped")
        try:
            await client.disconnect()
        except Exception:
            pass
        logger.info("Worker stopped cleanly")


async def _reconnect_client(client: TelegramClient) -> bool:
    """
    Attempt to reconnect Telethon with exponential backoff.
    Returns True on success, False if shutdown was requested.
    Max wait between attempts: 5 → 10 → 20 → 40 → 60s (then stays at 60s).
    """
    assert _shutdown_event is not None
    delay = 5
    max_delay = 60
    attempt = 0
    while not _shutdown_event.is_set():
        attempt += 1
        try:
            logger.warning("Telethon reconnect attempt #%d...", attempt)
            await client.connect()
            if await client.is_user_authorized():
                logger.info("Telethon reconnected successfully (attempt #%d)", attempt)
                return True
            logger.error("Session לא מאושר אחרי reconnect")
            # Authorization lost is a fatal error — do not loop on it
            return False
        except asyncio.CancelledError:
            return False
        except Exception as exc:
            logger.warning("Reconnect attempt #%d failed: %s — retrying in %ds", attempt, exc, delay)
            await _sleep_or_shutdown(delay)
            delay = min(delay * 2, max_delay)
    return False


async def _poll_loop(config: Config, engine: CopyEngine, client: TelegramClient) -> None:
    assert _shutdown_event is not None
    poll_interval = config.WORKER_POLL_INTERVAL_S

    while not _shutdown_event.is_set():
        try:
            # Ensure Telethon is still connected (auto-reconnect after network drops)
            if not client.is_connected():
                logger.warning("Telethon מנותק — מנסה להתחבר מחדש...")
                ok = await _reconnect_client(client)
                if not ok:
                    logger.error("Telethon reconnect נכשל לצמיתות — עוצר worker")
                    break

            # Check for resumable job first (waiting_retry with time elapsed)
            job = job_repo.get_resumable_job()
            if job is None:
                job = job_repo.get_pending_job()

            if job:
                logger.info(
                    "Picked up job #%d '%s' (status=%s)", job.id, job.name, job.status
                )
                state_repo.set_worker_status("running", job_id=job.id)
                job_repo.mark_started(job.id)

                # Resolve pending channels in background if bot triggered a refresh
                if _resolve_trigger is not None and _resolve_trigger.is_set():
                    _resolve_trigger.clear()
                    asyncio.ensure_future(_resolve_pending_channels(client))

                try:
                    await engine.run_job(job)
                    state_repo.set_worker_status("idle")
                    await _send_completion_notification(client, job.id)

                except FloodWaitError as e:
                    wait_s = e.seconds
                    buf_min = state_repo.get_int_setting("flood_buffer_min_s", 5)
                    buf_max = state_repo.get_int_setting("flood_buffer_max_s", 10)
                    buffer_s = random.uniform(buf_min, buf_max)
                    total_wait = wait_s + buffer_s
                    retry_at = (
                        datetime.utcnow() + timedelta(seconds=total_wait)
                    ).strftime("%Y-%m-%d %H:%M:%S")

                    new_count = job_repo.increment_retry(job.id)
                    max_retries = state_repo.get_int_setting("max_retries", 5)
                    logger.warning(
                        "Job #%d: FloodWait %ds (buffer=%.1fs) — retry #%d/%d after %s",
                        job.id, wait_s, buffer_s, new_count, max_retries, retry_at,
                    )

                    if new_count >= max_retries:
                        job_repo.update_status(
                            job.id,
                            "failed",
                            error=f"FloodWait: הגיע למקסימום ניסיונות ({max_retries})",
                        )
                        logger.error("Job #%d: max retries reached, marking failed", job.id)
                        await _send_network_disruption_notification(
                            client, job.id,
                            f"FloodWait — הגיע למקסימום ניסיונות ({max_retries})",
                            resumed=False,
                        )
                    else:
                        job_repo.update_status(
                            job.id,
                            "waiting_retry",
                            error=f"FloodWait {wait_s}s",
                            next_retry_at=retry_at,
                        )

                    state_repo.set_worker_status("idle")
                    await _sleep_or_shutdown(min(total_wait, 60))

                except Exception as e:
                    if _is_network_error(e):
                        # Network dropped mid-job: reconnect and resume automatically
                        logger.warning(
                            "Job #%d: network error mid-job (%s) — reconnecting and resuming...",
                            job.id, e,
                        )
                        # Re-queue as pending so it resumes from last checkpoint
                        job_repo.update_status(job.id, "pending")
                        state_repo.set_worker_status("idle")

                        # Notify user that a disruption occurred
                        await _send_network_disruption_notification(
                            client, job.id, str(e)[:200], reconnecting=True
                        )

                        # Reconnect loop
                        ok = await _reconnect_client(client)
                        if ok:
                            logger.info("Job #%d: reconnected — will resume on next poll cycle", job.id)
                            await _send_network_disruption_notification(
                                client, job.id, str(e)[:200], resumed=True
                            )
                        else:
                            logger.error("Job #%d: reconnect failed — job stays pending for next startup", job.id)
                        await _sleep_or_shutdown(3)
                    else:
                        logger.exception("Job #%d: unexpected error: %s", job.id, e)
                        new_count = job_repo.increment_retry(job.id)
                        max_retries = state_repo.get_int_setting("max_retries", 5)

                        if new_count >= max_retries:
                            job_repo.update_status(
                                job.id, "failed", error=str(e)[:500]
                            )
                            logger.error("Job #%d: max retries reached, marking failed", job.id)
                        else:
                            # Exponential backoff: 60s, 120s, 240s, 480s … capped at 10 min
                            backoff_s = min(60 * (2 ** (new_count - 1)), 600)
                            retry_at = (
                                datetime.utcnow() + timedelta(seconds=backoff_s)
                            ).strftime("%Y-%m-%d %H:%M:%S")
                            logger.warning(
                                "Job #%d: retry #%d/%d — backoff %ds, resumes at %s",
                                job.id, new_count, max_retries, backoff_s, retry_at,
                            )
                            job_repo.update_status(
                                job.id,
                                "waiting_retry",
                                error=str(e)[:500],
                                next_retry_at=retry_at,
                            )

                        state_repo.set_worker_status("idle")
                        await _sleep_or_shutdown(5)
            else:
                state_repo.heartbeat()
                if _resolve_trigger is not None:
                    _resolve_trigger.clear()
                await _resolve_pending_channels(client)
                await _sleep_or_shutdown(poll_interval)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Unexpected poll loop error: %s", e)
            state_repo.set_worker_status("error", error=str(e))
            await _sleep_or_shutdown(10)


async def _sleep_or_shutdown(seconds: float) -> None:
    """Sleep for the given duration, waking early if shutdown or resolve trigger fires."""
    assert _shutdown_event is not None
    waiters = {asyncio.ensure_future(_shutdown_event.wait())}
    if _resolve_trigger is not None:
        waiters.add(asyncio.ensure_future(_resolve_trigger.wait()))
    done, pending = await asyncio.wait(waiters, timeout=seconds, return_when=asyncio.FIRST_COMPLETED)
    for t in pending:
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass


def _request_shutdown() -> None:
    global _shutdown_event
    logger.info("Shutdown signal received")
    if _shutdown_event:
        _shutdown_event.set()


def _startup_recovery() -> None:
    """
    Inspect DB state on startup and recover safely.

    Recovery cases:
    1. worker_state.status = 'running' with a current_job_id
       → The worker crashed mid-job. Re-queue the job as 'pending'.
       The copy engine will resume from last_processed_id using the
       copied_messages dedup table.

    2. Any jobs stuck in status='running' (orphaned from a previous crash
       where worker_state wasn't updated)
       → Re-queue them as 'pending'.

    3. Jobs in 'waiting_retry' are left as-is. The poll loop handles
       next_retry_at correctly.

    4. clean shutdown (idle/stopped) — just log and continue.
    """
    logger.info("Running startup recovery...")
    ws = state_repo.get_worker_state()
    recovered = 0

    if ws.status == "running" and ws.current_job_id:
        job = job_repo.get_by_id(ws.current_job_id)
        if job and job.status == "running":
            logger.warning(
                "Recovery: job #%d was running at shutdown. "
                "Checkpoint: msg_id=%s. Re-queuing as pending.",
                job.id, job.last_processed_id,
            )
            job_repo.update_status(job.id, "pending")
            recovered += 1
        elif job and job.status in ("completed", "cancelled", "failed"):
            logger.info(
                "Recovery: job #%d already in terminal state '%s' — no action needed",
                job.id, job.status,
            )
    elif ws.status in ("running",):
        logger.warning("Recovery: worker_state shows running but no job_id — resetting to idle")

    # Also catch any orphaned 'running' jobs (defensive)
    orphaned = job_repo.get_all(status_filter=["running"])
    for job in orphaned:
        logger.warning(
            "Recovery: orphaned job #%d '%s' in running state — re-queuing",
            job.id, job.name,
        )
        job_repo.update_status(job.id, "pending")
        recovered += 1

    if recovered:
        logger.info("Recovery: re-queued %d job(s)", recovered)
    else:
        logger.info("Recovery: no action needed")

    state_repo.set_worker_status("idle")


_NETWORK_ERROR_HINTS = (
    "getaddrinfo failed",
    "ConnectError",
    "ConnectionError",
    "ConnectionResetError",
    "ConnectionAbortedError",
    "RemoteProtocolError",
    "ReadError",
    "NetworkError",
    "TimeoutError",
    "WinError 1231",
    "WinError 1232",
    "WinError 1236",
    "WinError 10022",
    "WinError 10060",
    "WinError 10061",
    "Network is unreachable",
    "Connection refused",
    "Server disconnected",
    "OSError",
)


def _is_network_error(exc: BaseException) -> bool:
    msg = f"{type(exc).__name__}: {exc}"
    return any(hint in msg for hint in _NETWORK_ERROR_HINTS)


async def _send_network_disruption_notification(
    client: TelegramClient,
    job_id: int,
    error_msg: str,
    *,
    reconnecting: bool = False,
    resumed: bool = False,
) -> None:
    """
    Notify the admin chat about a network disruption mid-job.
    Called with reconnecting=True when the drop is first detected,
    and with resumed=True once the connection is restored.
    """
    from app.repositories import state_repo

    chat_id_str = state_repo.get_setting("main_chat_id")
    if not chat_id_str:
        return
    try:
        chat_id = int(chat_id_str)
    except (ValueError, TypeError):
        return

    job = job_repo.get_by_id(job_id)
    job_name = job.name if job else f"#{job_id}"

    if resumed:
        text = (
            f"✅ <b>ניתוק רשת — חובר מחדש</b>\n\n"
            f"📋 משימה: <b>{job_name}</b>\n"
            f"▶️ המשימה ממשיכה מנקודת ה-checkpoint האחרונה."
        )
    elif reconnecting:
        text = (
            f"⚠️ <b>ניתוק רשת במהלך משימה</b>\n\n"
            f"📋 משימה: <b>{job_name}</b>\n"
            f"🔌 הניתוק הופסק ב-checkpoint האחרון.\n"
            f"🔄 מנסה להתחבר מחדש אוטומטית..."
        )
    else:
        text = (
            f"❌ <b>ניתוק רשת — משימה נכשלה</b>\n\n"
            f"📋 משימה: <b>{job_name}</b>\n"
            f"💬 פרטים: {error_msg}"
        )

    try:
        await client.send_message(chat_id, text, parse_mode="html")
        logger.info("Job #%d: network disruption notification sent (resumed=%s)", job_id, resumed)
    except Exception as e:
        logger.warning("Job #%d: failed to send disruption notification: %s", job_id, e)


async def _send_completion_notification(client: TelegramClient, job_id: int) -> None:
    """Send job summary to the admin chat via userbot after a job ends."""
    from app.repositories import state_repo, source_repo

    chat_id_str = state_repo.get_setting("main_chat_id")
    if not chat_id_str:
        return
    try:
        chat_id = int(chat_id_str)
    except (ValueError, TypeError):
        return

    job = job_repo.get_by_id(job_id)
    if not job or job.status not in ("completed", "failed"):
        return

    src = source_repo.get_source_by_id(job.source_id)
    dst = source_repo.get_destination_by_id(job.destination_id)
    src_str = src.display() if src else f"#{job.source_id}"
    dst_str = dst.display() if dst else f"#{job.destination_id}"

    def _esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    status_emoji = "✅" if job.status == "completed" else "❌"
    status_word = "הושלמה" if job.status == "completed" else "נכשלה"

    report_line = ""
    if job.report_url:
        report_line = f'\n\n📋 <a href="{job.report_url}">דוח שגיאות / דילוגים</a>'

    text = (
        f"{status_emoji} <b>{_esc(job.name)}</b> — {status_word}\n\n"
        f"📡 מקור: {_esc(src_str)}\n"
        f"📤 יעד: {_esc(dst_str)}\n\n"
        f"📊 הועתקו: {job.copied_count:,} | דולגו: {job.skipped_count:,} | נכשלו: {job.failed_count:,}"
        f"{report_line}"
    )

    try:
        await client.send_message(chat_id, text, parse_mode="html")
        logger.info("Job #%d: completion notification sent to chat %d", job_id, chat_id)
    except Exception as e:
        logger.warning("Job #%d: completion notification failed: %s", job_id, e)


async def _resolve_pending_channels(client: TelegramClient) -> None:
    """
    When idle, resolve title and ID for any sources/destinations
    that haven't been verified yet. Updates the DB so the bot UI
    shows real channel names and marks access errors clearly.
    """
    from app.repositories import source_repo

    unresolved_sources = source_repo.get_unresolved_sources()
    unresolved_dests = source_repo.get_unresolved_destinations()

    if not unresolved_sources and not unresolved_dests:
        return

    for src in unresolved_sources:
        try:
            entity = await _get_entity_safe(client, src.channel_ref)
            title = getattr(entity, "title", src.channel_ref)
            source_repo.update_source_resolved(src.id, title, entity.id)
            source_repo.update_source_name(src.id, title)
            source_repo.set_source_validation_error(src.id, None)
            extra = await _fetch_channel_extra_info(client, entity)
            source_repo.update_source_extra_info(src.id, **extra)
            logger.info("Resolved source '%s': %s (id=%d)", src.name, title, entity.id)
        except Exception as e:
            source_repo.set_source_validation_error(src.id, str(e))
            logger.warning("Cannot access source '%s' (%s): %s", src.name, src.channel_ref, e)

    for dst in unresolved_dests:
        try:
            entity = await _get_entity_safe(client, dst.channel_ref)
            title = getattr(entity, "title", dst.channel_ref)
            source_repo.update_destination_resolved(dst.id, title, entity.id)
            source_repo.update_destination_name(dst.id, title)
            source_repo.set_dest_validation_error(dst.id, None)
            extra = await _fetch_channel_extra_info(client, entity)
            source_repo.update_destination_extra_info(dst.id, **extra)
            logger.info("Resolved destination '%s': %s (id=%d)", dst.name, title, entity.id)
        except Exception as e:
            source_repo.set_dest_validation_error(dst.id, str(e))
            logger.warning("Cannot access destination '%s' (%s): %s", dst.name, dst.channel_ref, e)


async def _fetch_channel_extra_info(client: TelegramClient, entity) -> dict:
    """Fetch additional channel metadata. Returns a dict ready for update_*_extra_info."""
    from telethon.tl.types import (
        InputMessagesFilterPhotos,
        InputMessagesFilterVideo,
        InputMessagesFilterDocument,
    )

    username = getattr(entity, "username", None)
    participants_count = getattr(entity, "participants_count", None)
    about = getattr(entity, "about", None)
    verified = bool(getattr(entity, "verified", False))

    if getattr(entity, "broadcast", False):
        channel_type = "ערוץ"
    elif getattr(entity, "megagroup", False):
        channel_type = "קבוצת-על"
    elif getattr(entity, "gigagroup", False):
        channel_type = "קהילה"
    else:
        channel_type = "קבוצה"

    total_messages = photos_count = videos_count = docs_count = None
    try:
        msgs = await client.get_messages(entity, limit=1)
        total_messages = msgs.total
    except Exception:
        pass
    try:
        msgs = await client.get_messages(entity, limit=1, filter=InputMessagesFilterPhotos)
        photos_count = msgs.total
    except Exception:
        pass
    try:
        msgs = await client.get_messages(entity, limit=1, filter=InputMessagesFilterVideo)
        videos_count = msgs.total
    except Exception:
        pass
    try:
        msgs = await client.get_messages(entity, limit=1, filter=InputMessagesFilterDocument)
        docs_count = msgs.total
    except Exception:
        pass

    return dict(
        username=username,
        participants_count=participants_count,
        about=about,
        verified=verified,
        channel_type=channel_type,
        total_messages=total_messages,
        photos_count=photos_count,
        videos_count=videos_count,
        docs_count=docs_count,
    )


async def _get_entity_safe(client: TelegramClient, ref: str):
    """
    Resolve a channel reference to a Telethon entity.
    Handles: @username, plain numeric ID, -100XXXXXXXXX (Bot API format).
    """
    import re
    from telethon.tl.types import PeerChannel, PeerChat

    ref = ref.strip()

    # Bot API format: -1001234567890 → PeerChannel(1234567890)
    if re.match(r"^-100\d+$", ref):
        channel_id = int(ref[4:])  # strip "-100"
        return await client.get_entity(PeerChannel(channel_id))

    # Negative group ID: -1234567890 → PeerChat
    if re.match(r"^-\d+$", ref):
        chat_id = int(ref[1:])
        return await client.get_entity(PeerChat(chat_id))

    # Plain positive integer — treat as channel ID (PeerChannel)
    if re.match(r"^\d+$", ref):
        try:
            return await client.get_entity(PeerChannel(int(ref)))
        except Exception:
            return await client.get_entity(int(ref))

    # @username or username
    return await client.get_entity(ref)
