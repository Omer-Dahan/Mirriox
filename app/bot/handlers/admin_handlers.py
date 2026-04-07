"""Handlers for admin management and settings screens."""
from __future__ import annotations

import logging
from telegram import Update
from telegram.ext import ContextTypes

from app.models import ValidationError
from app.repositories import admin_repo, state_repo
from app.services import validation_service
from app.ui import renderer, texts, keyboards
from app.bot.handlers._common import update_main_message, answer_callback, delete_user_message

logger = logging.getLogger(__name__)


async def dispatch_admins(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    data: str = update.callback_query.data  # type: ignore[union-attr]
    bootstrap_ids: list[int] = context.bot_data.get("admin_ids", [])  # type: ignore[union-attr]

    if data == "menu:admins":
        text, kb = renderer.render_admin_list(bootstrap_ids)
        await update_main_message(context, text, kb)
    elif data == "adm:new":
        context.user_data["awaiting_input"] = "admin_id"  # type: ignore[index]
        await update_main_message(context, texts.PROMPT_ADMIN_ID, keyboards.kb_admin_cancel())
    elif ":" in data:
        parts = data.split(":")
        if len(parts) >= 3 and parts[0] == "adm":
            tid = int(parts[1])
            action = parts[2]
            await _dispatch_admin_action(update, context, tid, action, bootstrap_ids)


async def _dispatch_admin_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    telegram_id: int,
    action: str,
    bootstrap_ids: list[int],
) -> None:
    if action == "confirm_remove":
        if telegram_id in bootstrap_ids:
            text, kb = renderer.render_error("לא ניתן להסיר מנהל bootstrap", "admins")
        else:
            admin = admin_repo.get_by_telegram_id(telegram_id)
            name = f"@{admin.username}" if admin and admin.username else str(telegram_id)
            text = f"{texts.TITLE_ADMINS}\n\nהאם להסיר את {name} מרשימת המנהלים?"
            kb = keyboards.kb_confirm_remove_admin(telegram_id)
        await update_main_message(context, text, kb)
    elif action == "remove":
        if telegram_id in bootstrap_ids:
            text, kb = renderer.render_error("לא ניתן להסיר מנהל bootstrap", "admins")
        else:
            admin_repo.remove(telegram_id)
            logger.info("Admin %d removed", telegram_id)
            text, kb = renderer.render_admin_list(bootstrap_ids)
        await update_main_message(context, text, kb)


async def handle_admin_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await delete_user_message(update)
    bootstrap_ids: list[int] = context.bot_data.get("admin_ids", [])  # type: ignore[union-attr]
    raw = (update.message.text or "").strip()  # type: ignore[union-attr]
    try:
        tid = validation_service.validate_telegram_id(raw)
        username = None
        admin_repo.add(tid, username, added_by=update.effective_user.id)  # type: ignore[union-attr]
        logger.info("Admin %d added", tid)
        context.user_data.pop("awaiting_input", None)  # type: ignore[union-attr]
        text, kb = renderer.render_admin_list(bootstrap_ids)
    except ValidationError as e:
        text = f"{texts.TITLE_ADMINS}\n\n⚠️ {e}\n\nהזן מזהה Telegram:"
        kb = keyboards.kb_admin_cancel()
    await update_main_message(context, text, kb)


# ── Settings ───────────────────────────────────────────────────────────────────

async def dispatch_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    data: str = update.callback_query.data  # type: ignore[union-attr]

    if data == "menu:settings":
        text, kb = renderer.render_settings()
        await update_main_message(context, text, kb)
    elif data.startswith("cfg:"):
        key = data[4:]
        if key in texts.TOGGLE_SETTINGS:
            current = state_repo.get_setting(key) or "1"
            state_repo.set_setting(key, "0" if current == "1" else "1")
            text, kb = renderer.render_settings()
            await update_main_message(context, text, kb)
        elif key in texts.EDITABLE_SETTINGS:
            context.user_data["awaiting_input"] = "setting_value"  # type: ignore[index]
            context.user_data["setting_key"] = key  # type: ignore[index]
            await update_main_message(
                context,
                texts.prompt_setting(key),
                keyboards.kb_setting_cancel(),
            )


async def handle_setting_value(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await delete_user_message(update)
    key = context.user_data.pop("setting_key", None)  # type: ignore[union-attr]
    raw = (update.message.text or "").strip()  # type: ignore[union-attr]

    LIMITS = {
        "min_delay_ms":         (100,  60000),
        "max_delay_ms":         (100,  60000),
        "flood_wait_buffer_s":  (0,    300),
        "max_retries":          (1,    20),
        "heartbeat_interval_s": (5,    300),
    }

    if not key:
        text, kb = renderer.render_settings()
        await update_main_message(context, text, kb)
        return

    label = texts.SETTINGS_LABELS.get(key, key)
    min_v, max_v = LIMITS.get(key, (0, 999999))

    try:
        val = validation_service.validate_positive_int_setting(raw, label, min_v, max_v)
        state_repo.set_setting(key, str(val))
        context.user_data.pop("awaiting_input", None)  # type: ignore[union-attr]
        text, kb = renderer.render_settings()
    except ValidationError as e:
        text = f"{texts.TITLE_SETTINGS}\n\n⚠️ {e}\n\n{texts.prompt_setting(key).split(chr(10))[-1]}"
        kb = keyboards.kb_setting_cancel()
    await update_main_message(context, text, kb)
