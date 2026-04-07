"""Handles the /start command. Creates a fresh main control message."""
from __future__ import annotations

import logging
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import TelegramError

from app.repositories import state_repo
from app.ui import renderer

logger = logging.getLogger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a new main control message; delete the old one if possible."""
    if update.message is None:
        return

    chat_id = update.effective_chat.id  # type: ignore[union-attr]

    # Try to delete the previous main message
    old_msg_id_str = state_repo.get_setting("main_message_id")
    old_chat_id_str = state_repo.get_setting("main_chat_id")
    if old_msg_id_str and old_chat_id_str:
        try:
            await context.bot.delete_message(
                chat_id=int(old_chat_id_str),
                message_id=int(old_msg_id_str),
            )
        except TelegramError:
            pass  # Already gone or not accessible — that's fine

    # Clear any in-flight wizard state
    if context.user_data:
        context.user_data.clear()

    # Send a fresh main message
    text, keyboard = renderer.render_main_menu()
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )

    # Store the new message coordinates
    state_repo.set_setting("main_chat_id", str(chat_id))
    state_repo.set_setting("main_message_id", str(msg.message_id))

    logger.info("Main control message created: chat=%d msg=%d", chat_id, msg.message_id)
