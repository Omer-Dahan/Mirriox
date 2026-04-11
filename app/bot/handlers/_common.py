"""Shared helpers for all bot handlers."""
from __future__ import annotations

import logging
from datetime import datetime
from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from telegram.error import TelegramError, BadRequest

from app.repositories import state_repo

logger = logging.getLogger(__name__)

# Tracks the start time of the current connectivity gap (None = connected)
_disconnected_since: datetime | None = None


async def update_main_message(
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    keyboard: InlineKeyboardMarkup,
) -> None:
    """Edit the stored main control message with new text + keyboard."""
    global _disconnected_since

    chat_id_str = state_repo.get_setting("main_chat_id")
    msg_id_str = state_repo.get_setting("main_message_id")

    if not chat_id_str or not msg_id_str:
        logger.warning("No main message stored yet — cannot update")
        return

    try:
        await context.bot.edit_message_text(
            chat_id=int(chat_id_str),
            message_id=int(msg_id_str),
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        # Log recovery if we were previously disconnected
        if _disconnected_since is not None:
            downtime_s = (datetime.utcnow() - _disconnected_since).total_seconds()
            logger.info("Bot reconnected successfully after %.0fs", downtime_s)
            _disconnected_since = None
    except BadRequest as e:
        if "message is not modified" in str(e).lower():
            pass  # Already showing this content, not an error
        else:
            logger.warning("Failed to edit main message: %s", e)
    except TelegramError as e:
        if _disconnected_since is None:
            _disconnected_since = datetime.utcnow()
            logger.warning("Bot lost connectivity at %s: %s", _disconnected_since.strftime("%H:%M:%S"), e)
        else:
            downtime_s = (datetime.utcnow() - _disconnected_since).total_seconds()
            logger.warning("Bot still disconnected (%.0fs so far): %s", downtime_s, e)


async def answer_callback(update: Update, text: str = "") -> None:
    """Silently acknowledge a callback query."""
    if update.callback_query:
        try:
            await update.callback_query.answer(text)
        except TelegramError:
            pass


async def delete_user_message(update: Update) -> None:
    """Delete the incoming user message (used after text-input steps)."""
    if update.message:
        try:
            await update.message.delete()
        except TelegramError:
            pass
