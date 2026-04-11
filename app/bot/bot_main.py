"""Management bot: builds the Application, wires all handlers, starts polling."""
from __future__ import annotations

import asyncio
import logging
import socket

# ── DNS bypass ─────────────────────────────────────────────────────────────────
# The system DNS is broken (IPv6 router DNS, no response).
# Telethon uses hardcoded DC IPs and works fine; we do the same for the Bot API.
# We patch socket.getaddrinfo to return Telegram's known IPs directly,
# so no DNS resolution is attempted for api.telegram.org at all.
# IPs sourced from Telegram's official DC list — stable for years.
_TELEGRAM_API_IPS = ["149.154.167.220", "149.154.167.221", "91.108.4.1"]
_orig_getaddrinfo = socket.getaddrinfo

def _bypass_dns(host, port, *args, **kwargs):
    if host == "api.telegram.org":
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))
            for ip in _TELEGRAM_API_IPS
        ]
    return _orig_getaddrinfo(host, port, *args, **kwargs)

socket.getaddrinfo = _bypass_dns
# ──────────────────────────────────────────────────────────────────────────────

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from telegram.request import HTTPXRequest

from app.config import Config
from app.repositories import admin_repo
from app.bot.handlers import (
    start_handler,
    job_handlers,
    source_handlers,
    filter_handlers,
    admin_handlers,
    scan_handlers,
)
from app.ui import renderer
from app.bot.handlers._common import update_main_message, answer_callback

_AUTO_REFRESH_INTERVAL_S = 30

logger = logging.getLogger(__name__)

# Module-level bot reference — set once the Application is running.
# Used by the worker to send proactive notifications without Telethon.
_app: Application | None = None


async def send_notification(chat_id: int, text: str) -> None:
    """Send a message via the management bot (not the userbot).
    Safe to call from the worker — uses the shared Application instance."""
    if _app is None:
        logger.warning("send_notification called before bot Application is ready")
        return
    try:
        await _app.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
    except Exception as e:
        logger.warning("send_notification failed: %s", e)

# Suppress noisy APScheduler execution logs
logging.getLogger("apscheduler.executors.default").setLevel(logging.WARNING)


# ── Authorization guard ────────────────────────────────────────────────────────

def _is_authorized(user_id: int, bootstrap_ids: list[int]) -> bool:
    return user_id in bootstrap_ids or admin_repo.is_admin(user_id)


def _auth_filter(config: Config):
    """Return a check function for the given user."""
    async def _check(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> bool:
        if update.effective_user is None:
            return False
        return _is_authorized(update.effective_user.id, config.ADMIN_IDS)
    return _check


# ── Central callback router ────────────────────────────────────────────────────

async def _handle_paging(
    update: Update, context: ContextTypes.DEFAULT_TYPE, data: str
) -> None:
    await answer_callback(update)
    parts = data.split(":")
    if len(parts) != 3:
        return
    _, screen, page_str = parts
    try:
        page = int(page_str)
    except ValueError:
        return

    if screen == "jobs":
        text, kb = renderer.render_job_list(page=page)
    elif screen == "sources":
        text, kb = renderer.render_source_list(page=page)
    elif screen == "destinations":
        text, kb = renderer.render_dest_list(page=page)
    elif screen == "filters":
        text, kb = renderer.render_blocked_words(page=page)
    elif screen == "admins":
        bootstrap_ids: list[int] = context.bot_data.get("admin_ids", [])  # type: ignore[union-attr]
        text, kb = renderer.render_admin_list(bootstrap_ids, page=page)
    else:
        return
    await update_main_message(context, text, kb)


async def route_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return

    user = update.effective_user
    if user is None:
        return

    bootstrap_ids: list[int] = context.bot_data.get("admin_ids", [])  # type: ignore[union-attr]
    if not _is_authorized(user.id, bootstrap_ids):
        return  # silent — act as if offline

    data: str = update.callback_query.data or ""

    # Track whether the main menu is currently displayed
    context.bot_data["on_main_screen"] = data == "menu:main"

    try:
        if data == "menu:main":
            await answer_callback(update)
            text, kb = renderer.render_main_menu()
            await update_main_message(context, text, kb)

        elif data.startswith("page:"):
            await _handle_paging(update, context, data)

        elif data.startswith("job:") or data.startswith("wzd:") or data == "menu:jobs":
            await job_handlers.dispatch(update, context)

        elif data.startswith("src:") or data == "menu:sources":
            await source_handlers.dispatch_sources(update, context)

        elif data.startswith("dst:") or data == "menu:destinations":
            await source_handlers.dispatch_destinations(update, context)

        elif data.startswith("flt:") or data == "menu:filters":
            await filter_handlers.dispatch(update, context)

        elif data.startswith("adm:") or data == "menu:admins":
            await admin_handlers.dispatch_admins(update, context)

        elif data.startswith("cfg:") or data == "menu:settings":
            await admin_handlers.dispatch_settings(update, context)

        elif data == "menu:stats":
            await answer_callback(update)
            text, kb = renderer.render_transfer_stats()
            await update_main_message(context, text, kb)

        elif data.startswith("scan:") or data == "menu:scan":
            await scan_handlers.dispatch_scan(update, context)

        else:
            await update.callback_query.answer()
            logger.warning("Unhandled callback data: %s", data)

    except Exception as e:
        logger.exception("Error handling callback %s: %s", data, e)
        try:
            text, kb = renderer.render_error(f"שגיאה פנימית: {e}")
            await update_main_message(context, text, kb)
        except Exception:  # nosec B110 — best-effort error display, non-fatal
            pass


# ── Central text-input dispatcher ─────────────────────────────────────────────

async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return

    bootstrap_ids: list[int] = context.bot_data.get("admin_ids", [])  # type: ignore[union-attr]
    if not _is_authorized(update.effective_user.id, bootstrap_ids):
        return  # silent — act as if offline

    awaiting = context.user_data.get("awaiting_input")  # type: ignore[union-attr]
    if not awaiting:
        # No input expected — silently delete the message
        try:
            await update.message.delete()
        except Exception:  # nosec B110 — best-effort message cleanup, non-fatal
            pass
        return

    _dispatch: dict[str, object] = {
        "job_name":      job_handlers.handle_job_name,
        "job_date_from": job_handlers.handle_job_date_from,
        "job_date_to":   job_handlers.handle_job_date_to,
        "job_id_from":   job_handlers.handle_job_id_from,
        "job_id_to":     job_handlers.handle_job_id_to,
        "job_single_id": job_handlers.handle_job_single_id,
        "wzd_source_ref":  job_handlers.handle_wzd_source_ref,
        "wzd_dest_ref":    job_handlers.handle_wzd_dest_ref,
        "source_ref":    source_handlers.handle_source_ref,
        "dest_ref":      source_handlers.handle_dest_ref,
        "filter_word":   filter_handlers.handle_filter_word,
        "admin_id":      admin_handlers.handle_admin_id,
        "setting_value":    admin_handlers.handle_setting_value,
        "scan_channel_ref": scan_handlers.handle_scan_channel_ref,
    }

    handler_fn = _dispatch.get(awaiting)
    if handler_fn:
        try:
            await handler_fn(update, context)  # type: ignore[operator]
        except Exception as e:
            logger.exception("Error in text-input handler %s: %s", awaiting, e)
            context.user_data.pop("awaiting_input", None)  # type: ignore[union-attr]
    else:
        logger.warning("Unknown awaiting_input key: %s", awaiting)
        context.user_data.pop("awaiting_input", None)  # type: ignore[union-attr]
        try:
            await update.message.delete()
        except Exception:  # nosec B110 — best-effort message cleanup, non-fatal
            pass


# ── Unauthorized command handler ───────────────────────────────────────────────

async def handle_unauthorized(
    _update: Update, _context: ContextTypes.DEFAULT_TYPE
) -> None:
    pass  # silent — act as if offline


# ── Application factory ────────────────────────────────────────────────────────

async def _auto_refresh_main_menu(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Periodically refreshes the main control message — only when main menu is visible."""
    if not context.bot_data.get("on_main_screen", False):
        return
    from app.repositories import job_repo
    active = job_repo.get_active_job()
    if active is None:
        return
    text, kb = renderer.render_main_menu()
    await update_main_message(context, text, kb)


def build_application(config: Config) -> Application:
    # Use Google DNS (8.8.8.8) to bypass broken system/ISP DNS.
    # The worker (Telethon) uses hardcoded DC IPs, so it works without DNS.
    # But api.telegram.org (HTTP Bot API) needs DNS resolution.
    import httpx
    from telegram.request import HTTPXRequest

    request = HTTPXRequest(
        connection_pool_size=8,
        connect_timeout=30,
        read_timeout=30,
        write_timeout=30,
        http_version="1.1",
    )
    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .request(request)
        .build()
    )

    # Store bootstrap admin IDs for handlers to access
    app.bot_data["admin_ids"] = config.ADMIN_IDS

    # Auto-refresh main menu every 30s when a job is active
    if app.job_queue:
        app.job_queue.run_repeating(
            _auto_refresh_main_menu,
            interval=_AUTO_REFRESH_INTERVAL_S,
            first=_AUTO_REFRESH_INTERVAL_S,
        )

    # /start — always allowed; creates fresh main message
    app.add_handler(
        CommandHandler(
            "start",
            _make_auth_command(start_handler.start_command, config),
        )
    )

    # All callback queries routed through the central router
    app.add_handler(CallbackQueryHandler(route_callback))

    # Text input from authorized users
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
            handle_text_input,
        )
    )

    # Global error handler — logs ALL handler exceptions so nothing is hidden
    async def _global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.error("Handler error [update=%s]: %s", update, context.error, exc_info=context.error)

    app.add_error_handler(_global_error_handler)

    return app


def _make_auth_command(handler_fn, config: Config):
    async def _wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user is None:
            return
        uid = update.effective_user.id
        if not _is_authorized(uid, config.ADMIN_IDS):
            logger.warning("/start rejected: user %d not in ADMIN_IDS %s", uid, config.ADMIN_IDS)
            return
        logger.info("/start accepted for user %d", uid)
        await handler_fn(update, context)
    return _wrapped


def run(config: Config) -> None:
    """Build and start the management bot (blocking)."""
    global _app
    logger.info("Starting management bot...")
    app = build_application(config)
    _app = app
    app.run_polling(allowed_updates=Update.ALL_TYPES)


async def run_async(config: Config) -> None:
    """Run the bot inside an existing event loop (used when combined with worker)."""
    global _app
    app = build_application(config)
    _app = app

    # Retry initialize() until it succeeds — network may not be ready at startup.
    # We manage the lifecycle manually (instead of `async with app:`) so that
    # initialize() can be retried without recreating the whole Application.
    _INIT_RETRY_S = 5
    _attempt = 0
    while True:
        try:
            _attempt += 1
            await app.initialize()
            if _attempt > 1:
                logger.info("Bot init succeeded after %d attempt(s) 🔄✅", _attempt)
            break
        except Exception as exc:
            exc_type = type(exc).__name__
            hint = ""
            msg = str(exc)
            if "ConnectError" in exc_type or "Connect" in exc_type:
                hint = " (בדוק רשת / טוקן בוט)"
            elif "401" in msg or "Unauthorized" in msg:
                hint = " (טוקן בוט לא תקין — בדוק BOT_TOKEN ב-.env)"
            elif "ConnectionError" in exc_type or "Timeout" in exc_type:
                hint = " (timeout — בדוק אם שרתי טלגרם נגישים)"
            logger.warning("Bot init failed [%s]%s — retrying in %ds...", exc, hint, _INIT_RETRY_S)
            await asyncio.sleep(_INIT_RETRY_S)

    try:
        await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)  # type: ignore[union-attr]
        logger.info("✅ Management bot connected and polling")
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass
        finally:
            await app.updater.stop()  # type: ignore[union-attr]
            await app.stop()
    finally:
        await app.shutdown()
