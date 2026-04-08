"""Handlers for blocked words management."""
# pylint: disable=unused-argument  # PTB handler callbacks require (update, context) even when unused
from __future__ import annotations

import logging
from telegram import Update
from telegram.ext import ContextTypes

from app.models import ValidationError
from app.repositories import filter_repo
from app.services import validation_service
from app.ui import renderer, texts, keyboards
from app.bot.handlers._common import update_main_message, answer_callback, delete_user_message

logger = logging.getLogger(__name__)


async def dispatch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    data: str = update.callback_query.data  # type: ignore[union-attr]

    if data == "menu:filters":
        text, kb = renderer.render_blocked_words()
        await update_main_message(context, text, kb)
    elif data == "flt:new":
        await _add_word_start(update, context)
    elif data == "flt:confirm_clear":
        text = texts.CONFIRM_CLEAR_WORDS
        kb = keyboards.kb_confirm_clear_words()
        await update_main_message(context, text, kb)
    elif data == "flt:clear":
        count = filter_repo.clear_all()
        logger.info("Cleared %d blocked words", count)
        text, kb = renderer.render_blocked_words()
        await update_main_message(context, text, kb)
    elif data.startswith("flt:") and ":delete" in data:
        parts = data.split(":")
        word_id = int(parts[1])
        filter_repo.remove_by_id(word_id)
        text, kb = renderer.render_blocked_words()
        await update_main_message(context, text, kb)


async def _add_word_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["awaiting_input"] = "filter_word"  # type: ignore[index]
    text = texts.PROMPT_BLOCKED_WORD
    await update_main_message(context, text, keyboards.kb_filter_cancel())


async def handle_filter_word(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await delete_user_message(update)
    raw = (update.message.text or "").strip()  # type: ignore[union-attr]
    try:
        word = validation_service.validate_word(raw)
        admin_id = update.effective_user.id if update.effective_user else None  # type: ignore[union-attr]
        filter_repo.add_word(word, added_by=admin_id)
        context.user_data.pop("awaiting_input", None)  # type: ignore[union-attr]
        text, kb = renderer.render_blocked_words()
    except ValidationError as e:
        text = f"{texts.TITLE_BLOCKED_WORDS}\n\n⚠️ {e}\n\nהזן מילה לחסימה:"
        kb = keyboards.kb_filter_cancel()
    await update_main_message(context, text, kb)
