"""Handlers for the duplicate-scan flow (main menu → channel picker → scan/delete)."""
from __future__ import annotations

import logging
from telegram import Update
from telegram.ext import ContextTypes

from app.repositories import scan_repo, source_repo
from app.services import validation_service
from app.models import ValidationError
from app.ui import renderer, texts, keyboards
from app.bot.handlers._common import update_main_message, answer_callback, delete_user_message

logger = logging.getLogger(__name__)


async def dispatch_scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    data: str = update.callback_query.data  # type: ignore[union-attr]

    if data == "menu:scan":
        text, kb = renderer.render_scan_picker()
        await update_main_message(context, text, kb)
        return

    if not data.startswith("scan:"):
        return

    parts = data.split(":")  # scan:action or scan:action:id
    action = parts[1] if len(parts) > 1 else ""

    if action == "manual":
        context.user_data["awaiting_input"] = "scan_channel_ref"  # type: ignore[index]
        text = f"{texts.TITLE_SCAN_PICKER}\n\nהזן @username, מזהה מספרי, או קישור t.me/ של הערוץ לסריקה:"
        await update_main_message(context, text, keyboards.kb_scan_cancel())

    elif action == "dst" and len(parts) >= 3:
        dest_id = int(parts[2])
        dest = source_repo.get_destination_by_id(dest_id)
        if dest is None:
            text, kb = renderer.render_error("יעד לא נמצא", "scan")
            await update_main_message(context, text, kb)
            return
        await _start_scan_for_channel(
            update, context,
            channel_ref=dest.channel_ref,
            channel_title=dest.title or dest.name,
            dest_id=dest_id,
        )

    elif action == "view" and len(parts) >= 3:
        scan_id = int(parts[2])
        text, kb = renderer.render_scan_report_by_id(scan_id)
        await update_main_message(context, text, kb)

    elif action == "confirm_delete" and len(parts) >= 3:
        scan_id = int(parts[2])
        text, kb = renderer.render_confirm_delete_dupes_by_id(scan_id)
        await update_main_message(context, text, kb)

    elif action == "delete" and len(parts) >= 3:
        scan_id = int(parts[2])
        await _queue_delete(update, context, scan_id)

    elif action == "rescan" and len(parts) >= 3:
        scan_id = int(parts[2])
        old = scan_repo.get_scan_by_id(scan_id)
        if old:
            await _start_scan_for_channel(
                update, context,
                channel_ref=old["channel_ref"],
                channel_title=old["channel_title"],
                dest_id=old.get("dest_id"),
            )
        else:
            text, kb = renderer.render_scan_picker()
            await update_main_message(context, text, kb)

    elif action == "stop" and len(parts) >= 3:
        scan_id = int(parts[2])
        scan_repo.cancel_scan(scan_id)
        text, kb = renderer.render_scan_report_by_id(scan_id)
        await update_main_message(context, text, kb)

    elif action == "confirm_reset" and len(parts) >= 3:
        scan_id = int(parts[2])
        scan = scan_repo.get_scan_by_id(scan_id)
        if scan:
            channel_name = scan.get("channel_title") or scan.get("channel_ref") or "ערוץ"
            text = (
                f"⚠️ <b>אפס נתוני סריקה — {texts.esc(channel_name)}</b>\n\n"
                "פעולה זו תמחק את כל הנתונים מהסריקות הקודמות לערוץ זה.\n"
                "⚠️ פעולה זו אינה הפיכה!"
            )
            kb = keyboards.kb_confirm_reset_scan(scan_id)
        else:
            text, kb = renderer.render_scan_picker()
        await update_main_message(context, text, kb)

    elif action == "reset" and len(parts) >= 3:
        scan_id = int(parts[2])
        scan = scan_repo.get_scan_by_id(scan_id)
        if scan:
            scan_repo.cancel_scan(scan_id)  # stop if running
            deleted = scan_repo.delete_scans_for_channel(scan["channel_ref"])
            logger.info("Reset: deleted %d scan records for channel %s", deleted, scan["channel_ref"])
        text, kb = renderer.render_scan_picker()
        await update_main_message(context, text, kb)


async def handle_scan_channel_ref(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle manually typed channel ref for scanning."""
    await delete_user_message(update)
    raw = (update.message.text or "").strip()  # type: ignore[union-attr]
    try:
        ref = validation_service.validate_channel_ref(raw)
    except ValidationError as e:
        text = f"{texts.TITLE_SCAN_PICKER}\n\n⚠️ {e}\n\nהזן @username, מזהה מספרי, או קישור t.me/:"
        await update_main_message(context, text, keyboards.kb_scan_cancel())
        return

    context.user_data.pop("awaiting_input", None)  # type: ignore[union-attr]
    await _start_scan_for_channel(
        update, context,
        channel_ref=ref,
        channel_title=ref,
        dest_id=None,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _start_scan_for_channel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    channel_ref: str,
    channel_title: str,
    dest_id: int | None,
) -> None:
    # If a scan for this channel is already pending/running, show it
    existing = scan_repo.get_latest_scan_for_channel(channel_ref)
    if existing and existing["status"] in ("pending", "running"):
        text, kb = renderer.render_scan_report_by_id(existing["id"])
        await update_main_message(context, text, kb)
        return

    scan_id = scan_repo.create_scan(channel_ref, channel_title, dest_id)
    text, kb = renderer.render_scan_report_by_id(scan_id)
    await update_main_message(context, text, kb)


async def _queue_delete(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    scan_id: int,
) -> None:
    scan = scan_repo.get_scan_by_id(scan_id)
    if scan is None or scan["status"] != "done":
        text, kb = renderer.render_error("לא נמצאה סריקה מושלמת", "scan")
        await update_main_message(context, text, kb)
        return

    existing_del = scan_repo.get_latest_delete_job(scan_id)
    if existing_del and existing_del["status"] in ("pending", "running"):
        text = (
            f"{texts.TITLE_SCAN_REPORT} — <b>{texts.esc(scan['channel_title'])}</b>\n\n"
            "⏳ משימת המחיקה כבר בתהליך..."
        )
        kb = keyboards.kb_scan_report(scan_id, "done", True)
        await update_main_message(context, text, kb)
        return

    scan_repo.create_delete_job(scan_id)
    text = (
        f"{texts.TITLE_SCAN_REPORT} — <b>{texts.esc(scan['channel_title'])}</b>\n\n"
        "🗑 משימת המחיקה הועברה לתור..."
    )
    kb = keyboards.kb_scan_report(scan_id, "done", True)
    await update_main_message(context, text, kb)
