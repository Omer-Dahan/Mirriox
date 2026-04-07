"""Management bot: builds the Application, wires all handlers, starts polling."""
from __future__ import annotations

import asyncio
import logging
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from app.config import Config
from app.repositories import admin_repo, state_repo
from app.bot.handlers import (
    start_handler,
    job_handlers,
    source_handlers,
    filter_handlers,
    admin_handlers,
)
from app.ui import renderer
from app.bot.handlers._common import update_main_message, answer_callback

logger = logging.getLogger(__name__)


# ── Authorization guard ────────────────────────────────────────────────────────

def _is_authorized(user_id: int, bootstrap_ids: list[int]) -> bool:
    return user_id in bootstrap_ids or admin_repo.is_admin(user_id)


def _auth_filter(config: Config):
    """Return a check function for the given user."""
    async def _check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
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

        else:
            await update.callback_query.answer()
            logger.warning("Unhandled callback data: %s", data)

    except Exception as e:
        logger.exception("Error handling callback %s: %s", data, e)
        try:
            text, kb = renderer.render_error(f"שגיאה פנימית: {e}")
            await update_main_message(context, text, kb)
        except Exception:
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
        except Exception:
            pass
        return

    _DISPATCH: dict[str, object] = {
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
        "setting_value": admin_handlers.handle_setting_value,
    }

    handler_fn = _DISPATCH.get(awaiting)
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
        except Exception:
            pass


# ── Unauthorized command handler ───────────────────────────────────────────────

async def handle_unauthorized(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    pass  # silent — act as if offline


# ── Application factory ────────────────────────────────────────────────────────

def build_application(config: Config) -> Application:
    app = Application.builder().token(config.BOT_TOKEN).build()

    # Store bootstrap admin IDs for handlers to access
    app.bot_data["admin_ids"] = config.ADMIN_IDS

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

    return app


def _make_auth_command(handler_fn, config: Config):
    async def _wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user is None:
            return
        if not _is_authorized(update.effective_user.id, config.ADMIN_IDS):
            return  # silent — act as if offline
        await handler_fn(update, context)
    return _wrapped


def run(config: Config) -> None:
    """Build and start the management bot (blocking)."""
    logger.info("Starting management bot...")
    app = build_application(config)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


async def run_async(config: Config) -> None:
    """Run the bot inside an existing event loop (used when combined with worker)."""
    app = build_application(config)
    async with app:
        await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)  # type: ignore[union-attr]
        logger.info("Management bot started")
        # Keep running until cancelled
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass
        finally:
            await app.updater.stop()  # type: ignore[union-attr]
            await app.stop()
