"""Handlers for source and destination management screens."""
from __future__ import annotations

import logging
from telegram import Update
from telegram.ext import ContextTypes

from app.models import ValidationError
from app.repositories import source_repo
from app.services import validation_service
from app.ui import renderer, texts, keyboards
from app.bot.handlers._common import update_main_message, answer_callback, delete_user_message

logger = logging.getLogger(__name__)


async def dispatch_sources(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    data: str = update.callback_query.data  # type: ignore[union-attr]

    if data == "menu:sources":
        text, kb = renderer.render_source_list()
        await update_main_message(context, text, kb)
    elif data == "src:new":
        await _src_add_start(update, context)
    elif ":" in data:
        parts = data.split(":")
        if len(parts) >= 3 and parts[0] == "src":
            src_id = int(parts[1])
            action = parts[2]
            await _dispatch_src_action(update, context, src_id, action)


async def _dispatch_src_action(
    update: Update, context: ContextTypes.DEFAULT_TYPE, src_id: int, action: str
) -> None:
    if action == "view":
        text, kb = renderer.render_source_detail(src_id)
        await update_main_message(context, text, kb)
    elif action == "confirm_delete":
        src = source_repo.get_source_by_id(src_id)
        if src:
            text = f"⚠️ <b>מחיקת מקור</b>\n\nהאם למחוק את <b>{src.name}</b>? פעולה זו אינה הפיכה."
            kb = keyboards.kb_confirm_delete_source(src_id)
        else:
            text, kb = renderer.render_error("מקור לא נמצא", "sources")
        await update_main_message(context, text, kb)
    elif action == "delete":
        if source_repo.is_source_in_use(src_id):
            text, kb = renderer.render_error(
                "לא ניתן למחוק מקור שמשויך למשימות קיימות.\n"
                "מחק את המשימות הקשורות תחילה.",
                back_target="sources",
            )
        else:
            source_repo.delete_source(src_id)
            text, kb = renderer.render_source_list()
        await update_main_message(context, text, kb)


async def _src_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["awaiting_input"] = "source_ref"  # type: ignore[index]
    text = f"{texts.TITLE_SOURCES}\n\nהזן @username, מזהה מספרי, או קישור t.me/:\n<i>השם יישאב אוטומטית מהערוץ</i>"
    await update_main_message(context, text, keyboards.kb_filter_cancel())


# ── Destinations ───────────────────────────────────────────────────────────────

async def dispatch_destinations(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await answer_callback(update)
    data: str = update.callback_query.data  # type: ignore[union-attr]

    if data == "menu:destinations":
        text, kb = renderer.render_dest_list()
        await update_main_message(context, text, kb)
    elif data == "dst:new":
        await _dst_add_start(update, context)
    elif ":" in data:
        parts = data.split(":")
        if len(parts) >= 3 and parts[0] == "dst":
            dst_id = int(parts[1])
            action = parts[2]
            await _dispatch_dst_action(update, context, dst_id, action)


async def _dispatch_dst_action(
    update: Update, context: ContextTypes.DEFAULT_TYPE, dst_id: int, action: str
) -> None:
    if action == "view":
        text, kb = renderer.render_dest_detail(dst_id)
        await update_main_message(context, text, kb)
    elif action == "confirm_delete":
        dest = source_repo.get_destination_by_id(dst_id)
        if dest:
            text = f"⚠️ <b>מחיקת יעד</b>\n\nהאם למחוק את <b>{dest.name}</b>? פעולה זו אינה הפיכה."
            kb = keyboards.kb_confirm_delete_dest(dst_id)
        else:
            text, kb = renderer.render_error("יעד לא נמצא", "destinations")
        await update_main_message(context, text, kb)
    elif action == "delete":
        if source_repo.is_destination_in_use(dst_id):
            text, kb = renderer.render_error(
                "לא ניתן למחוק יעד שמשויך למשימות קיימות.\n"
                "מחק את המשימות הקשורות תחילה.",
                back_target="destinations",
            )
        else:
            source_repo.delete_destination(dst_id)
            text, kb = renderer.render_dest_list()
        await update_main_message(context, text, kb)


async def _dst_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["awaiting_input"] = "dest_ref"  # type: ignore[index]
    text = f"{texts.TITLE_DESTINATIONS}\n\nהזן @username, מזהה מספרי, או קישור t.me/:\n<i>השם יישאב אוטומטית מהערוץ</i>"
    await update_main_message(context, text, keyboards.kb_filter_cancel())


# ── Text input handlers ────────────────────────────────────────────────────────

async def handle_source_ref(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await delete_user_message(update)
    raw = (update.message.text or "").strip()  # type: ignore[union-attr]
    try:
        ref = validation_service.validate_channel_ref(raw)
        # Name = ref for now; worker will update it with the real title
        source_repo.add_source(ref, ref)
        context.user_data.pop("awaiting_input", None)  # type: ignore[union-attr]
        text, kb = renderer.render_source_list()
    except ValidationError as e:
        text = f"{texts.TITLE_SOURCES}\n\n⚠️ {e}\n\nהזן @username, מזהה מספרי, או קישור t.me/:"
        kb = keyboards.kb_filter_cancel()
    await update_main_message(context, text, kb)


async def handle_dest_ref(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await delete_user_message(update)
    raw = (update.message.text or "").strip()  # type: ignore[union-attr]
    try:
        ref = validation_service.validate_channel_ref(raw)
        # Name = ref for now; worker will update it with the real title
        source_repo.add_destination(ref, ref)
        context.user_data.pop("awaiting_input", None)  # type: ignore[union-attr]
        text, kb = renderer.render_dest_list()
    except ValidationError as e:
        text = f"{texts.TITLE_DESTINATIONS}\n\n⚠️ {e}\n\nהזן @username, מזהה מספרי, או קישור t.me/:"
        kb = keyboards.kb_filter_cancel()
    await update_main_message(context, text, kb)
