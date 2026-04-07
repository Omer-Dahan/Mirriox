"""Job lifecycle and creation wizard handlers."""
from __future__ import annotations

import logging
from telegram import Update
from telegram.ext import ContextTypes

from app.models import JobError, ValidationError
from app.repositories import source_repo, filter_repo
from app.services import job_service, validation_service
from app.ui import renderer, texts, keyboards
from app.bot.handlers._common import update_main_message, answer_callback, delete_user_message

logger = logging.getLogger(__name__)


async def dispatch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route job-related callback queries."""
    await answer_callback(update)
    data: str = update.callback_query.data  # type: ignore[union-attr]

    if data == "menu:jobs":
        await _show_job_list(update, context)
    elif data == "job:new":
        await _wizard_start(update, context)
    elif data == "job:cancel_wizard":
        await _wizard_cancel(update, context)
    elif data == "wzd:skip_name":
        await _wizard_skip_name(update, context)
    elif data == "wzd:toggle_filter":
        await _wizard_toggle_filter(update, context)
    elif data == "wzd:confirm":
        await _wizard_confirm(update, context)
    elif data.startswith("wzd:toggle_src:"):
        await _wizard_toggle_source(update, context, int(data.split(":")[2]))
    elif data == "wzd:done_sources":
        await _wizard_done_sources(update, context)
    elif data.startswith("wzd:dst:"):
        await _wizard_pick_dest(update, context, int(data.split(":")[2]))
    elif data.startswith("wzd:mode:"):
        await _wizard_pick_mode(update, context, data.split(":")[2])
    elif data.startswith("wzd:toggle_type:"):
        await _wizard_toggle_type(update, context, data.split(":")[2])
    elif data == "wzd:done_types":
        await _wizard_done_types(update, context)
    elif data == "wzd:add_source":
        await _wizard_redirect_add_source(update, context)
    elif data == "wzd:add_dest":
        await _wizard_redirect_add_dest(update, context)
    elif ":" in data:
        parts = data.split(":")
        if len(parts) >= 3 and parts[0] == "job":
            job_id = int(parts[1])
            action = parts[2]
            await _dispatch_job_action(update, context, job_id, action)


async def _dispatch_job_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    job_id: int,
    action: str,
) -> None:
    if action == "view":
        text, kb = renderer.render_job_detail(job_id)
        await update_main_message(context, text, kb)
    elif action == "submit":
        await _job_submit(update, context, job_id)
    elif action == "confirm_delete":
        await _job_confirm_delete(update, context, job_id)
    elif action == "delete":
        await _job_delete(update, context, job_id)
    elif action == "confirm_cancel":
        await _job_confirm_cancel(update, context, job_id)
    elif action == "cancel":
        await _job_cancel(update, context, job_id)
    elif action == "pause":
        await _job_pause(update, context, job_id)
    elif action == "resume":
        await _job_resume(update, context, job_id)


# ── Job list ───────────────────────────────────────────────────────────────────

async def _show_job_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text, kb = renderer.render_job_list()
    await update_main_message(context, text, kb)


# ── Job actions ────────────────────────────────────────────────────────────────

async def _job_submit(
    update: Update, context: ContextTypes.DEFAULT_TYPE, job_id: int
) -> None:
    try:
        job_service.submit_job(job_id)
        text, kb = renderer.render_job_detail(job_id)
    except JobError as e:
        text, kb = renderer.render_error(str(e), back_target="jobs")
    await update_main_message(context, text, kb)


async def _job_confirm_delete(
    update: Update, context: ContextTypes.DEFAULT_TYPE, job_id: int
) -> None:
    from app.repositories import job_repo
    job = job_repo.get_by_id(job_id)
    if job is None:
        text, kb = renderer.render_error("משימה לא נמצאה", "jobs")
    else:
        text, kb = renderer.render_job_confirm_delete(job)
    await update_main_message(context, text, kb)


async def _job_delete(
    update: Update, context: ContextTypes.DEFAULT_TYPE, job_id: int
) -> None:
    try:
        job_service.delete_job(job_id)
        text, kb = renderer.render_job_list()
    except JobError as e:
        text, kb = renderer.render_error(str(e), "jobs")
    await update_main_message(context, text, kb)


async def _job_confirm_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE, job_id: int
) -> None:
    from app.repositories import job_repo
    job = job_repo.get_by_id(job_id)
    if job is None:
        text, kb = renderer.render_error("משימה לא נמצאה", "jobs")
    else:
        text, kb = renderer.render_job_confirm_cancel(job)
    await update_main_message(context, text, kb)


async def _job_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE, job_id: int
) -> None:
    try:
        job_service.cancel_job(job_id)
        text, kb = renderer.render_job_detail(job_id)
    except JobError as e:
        text, kb = renderer.render_error(str(e), "jobs")
    await update_main_message(context, text, kb)


async def _job_pause(
    update: Update, context: ContextTypes.DEFAULT_TYPE, job_id: int
) -> None:
    from app.repositories import job_repo
    job = job_repo.get_by_id(job_id)
    if job and job.status in ("pending", "running", "waiting_retry"):
        job_repo.pause_job(job_id)
        logger.info("Job #%d paused by user", job_id)
    text, kb = renderer.render_job_detail(job_id)
    await update_main_message(context, text, kb)


async def _job_resume(
    update: Update, context: ContextTypes.DEFAULT_TYPE, job_id: int
) -> None:
    from app.repositories import job_repo
    job = job_repo.get_by_id(job_id)
    if job and job.status == "paused":
        job_repo.resume_job(job_id)
        logger.info("Job #%d resumed by user", job_id)
    text, kb = renderer.render_job_detail(job_id)
    await update_main_message(context, text, kb)


# ── Creation wizard ────────────────────────────────────────────────────────────

def _init_wizard(context: ContextTypes.DEFAULT_TYPE) -> dict:
    context.user_data["wizard"] = {  # type: ignore[index]
        "_step": 1,
        "_total": 7,
        "name": None,
        "source_ids": [],
        "source_names": [],
        "dest_id": None,
        "dest_name": None,
        "mode": None,
        "date_from": None,
        "date_to": None,
        "id_from": None,
        "id_to": None,
        "single_id": None,
        "use_blocked_words": True,
        "content_types": {"text", "image", "video"},
    }
    return context.user_data["wizard"]  # type: ignore[index]


def _get_wizard(context: ContextTypes.DEFAULT_TYPE) -> dict | None:
    return context.user_data.get("wizard")  # type: ignore[union-attr]


async def _wizard_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    w = _init_wizard(context)
    w["_step"] = 1
    context.user_data["awaiting_input"] = "job_name"  # type: ignore[index]

    text, kb = renderer.render_wizard_step(
        texts.WIZARD_ENTER_NAME, w, keyboards.kb_wizard_name_step()
    )
    await update_main_message(context, text, kb)


async def _wizard_skip_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User skipped name — will be auto-generated from source > dest at confirm."""
    w = _get_wizard(context)
    if not w:
        return
    w["name"] = None  # Signal to auto-generate later
    context.user_data.pop("awaiting_input", None)  # type: ignore[union-attr]
    w["_step"] = 2
    await _wizard_show_source_select(context, w)


async def _wizard_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("wizard", None)  # type: ignore[union-attr]
    context.user_data.pop("awaiting_input", None)  # type: ignore[union-attr]
    text, kb = renderer.render_main_menu()
    await update_main_message(context, text, kb)


async def _wizard_toggle_filter(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    w = _get_wizard(context)
    if not w:
        return
    w["use_blocked_words"] = not w.get("use_blocked_words", True)
    await _wizard_show_summary(context, w)


async def _wizard_redirect_add_source(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """User wants to add a new source from within the wizard."""
    text = f"{texts.TITLE_SOURCES}\n\nהזן @username, מזהה מספרי, או קישור t.me/:\n<i>השם יישאב אוטומטית מהערוץ</i>"
    await update_main_message(context, text, keyboards.kb_wizard_cancel())
    context.user_data["awaiting_input"] = "wzd_source_ref"  # type: ignore[index]


async def _wizard_redirect_add_dest(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    text = f"{texts.TITLE_DESTINATIONS}\n\nהזן @username, מזהה מספרי, או קישור t.me/:\n<i>השם יישאב אוטומטית מהערוץ</i>"
    await update_main_message(context, text, keyboards.kb_wizard_cancel())
    context.user_data["awaiting_input"] = "wzd_dest_ref"  # type: ignore[index]


async def _wizard_toggle_source(
    update: Update, context: ContextTypes.DEFAULT_TYPE, source_id: int
) -> None:
    w = _get_wizard(context)
    if not w:
        return
    src = source_repo.get_source_by_id(source_id)
    if src is None:
        text, kb = renderer.render_error("מקור לא נמצא")
        await update_main_message(context, text, kb)
        return
    ids: list = w.setdefault("source_ids", [])
    names: list = w.setdefault("source_names", [])
    if source_id in ids:
        idx = ids.index(source_id)
        ids.pop(idx)
        names.pop(idx)
    else:
        ids.append(source_id)
        names.append(src.display())
    await _wizard_show_source_select(context, w)


async def _wizard_done_sources(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    w = _get_wizard(context)
    if not w or not w.get("source_ids"):
        return
    w["_step"] = 3
    await _wizard_show_dest_select(context, w)


async def _wizard_pick_dest(
    update: Update, context: ContextTypes.DEFAULT_TYPE, dest_id: int
) -> None:
    w = _get_wizard(context)
    if not w:
        return
    dest = source_repo.get_destination_by_id(dest_id)
    if dest is None:
        text, kb = renderer.render_error("יעד לא נמצא")
        await update_main_message(context, text, kb)
        return
    w["dest_id"] = dest.id
    w["dest_name"] = dest.display()
    w["_step"] = 4
    await _wizard_show_mode_select(context, w)


async def _wizard_pick_mode(
    update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str
) -> None:
    w = _get_wizard(context)
    if not w:
        return
    w["mode"] = mode
    w["_step"] = 5

    if mode == "all":
        # Skip params step — go to content types selection
        w["_step"] = 6
        await _wizard_show_content_types(context, w)
    elif mode == "date_range":
        context.user_data["awaiting_input"] = "job_date_from"  # type: ignore[index]
        text, kb = renderer.render_wizard_step(
            texts.WIZARD_ENTER_DATE_FROM, w, keyboards.kb_wizard_cancel()
        )
        await update_main_message(context, text, kb)
    elif mode == "id_range":
        context.user_data["awaiting_input"] = "job_id_from"  # type: ignore[index]
        text, kb = renderer.render_wizard_step(
            texts.WIZARD_ENTER_ID_FROM, w, keyboards.kb_wizard_cancel()
        )
        await update_main_message(context, text, kb)
    elif mode == "single_id":
        context.user_data["awaiting_input"] = "job_single_id"  # type: ignore[index]
        text, kb = renderer.render_wizard_step(
            texts.WIZARD_ENTER_SINGLE_ID, w, keyboards.kb_wizard_cancel()
        )
        await update_main_message(context, text, kb)


async def _wizard_show_source_select(
    context: ContextTypes.DEFAULT_TYPE, w: dict
) -> None:
    sources = source_repo.get_all_sources()
    selected = w.get("source_ids", [])
    if not sources:
        text, kb = renderer.render_wizard_step(
            texts.NO_SOURCES_YET, w, keyboards.kb_wizard_source_list([], selected)
        )
    else:
        text, kb = renderer.render_wizard_step(
            texts.WIZARD_SELECT_SOURCE, w, keyboards.kb_wizard_source_list(sources, selected)
        )
    await update_main_message(context, text, kb)


async def _wizard_show_dest_select(
    context: ContextTypes.DEFAULT_TYPE, w: dict
) -> None:
    dests = source_repo.get_all_destinations()
    if not dests:
        text, kb = renderer.render_wizard_step(
            texts.NO_DESTINATIONS_YET, w, keyboards.kb_wizard_dest_list([])
        )
    else:
        text, kb = renderer.render_wizard_step(
            texts.WIZARD_SELECT_DEST, w, keyboards.kb_wizard_dest_list(dests)
        )
    await update_main_message(context, text, kb)


async def _wizard_show_mode_select(
    context: ContextTypes.DEFAULT_TYPE, w: dict
) -> None:
    text, kb = renderer.render_wizard_step(
        texts.WIZARD_SELECT_MODE, w, keyboards.kb_wizard_mode()
    )
    await update_main_message(context, text, kb)


async def _wizard_show_content_types(
    context: ContextTypes.DEFAULT_TYPE, w: dict
) -> None:
    selected: set = w.setdefault("content_types", {"text", "image", "video"})
    text, kb = renderer.render_wizard_step(
        texts.WIZARD_SELECT_CONTENT_TYPES, w, keyboards.kb_wizard_content_types(selected)
    )
    await update_main_message(context, text, kb)


async def _wizard_toggle_type(
    update: Update, context: ContextTypes.DEFAULT_TYPE, type_name: str
) -> None:
    w = _get_wizard(context)
    if not w:
        return
    selected: set = w.setdefault("content_types", {"text", "image", "video"})
    if type_name in selected:
        selected.discard(type_name)
    else:
        selected.add(type_name)
    await _wizard_show_content_types(context, w)


async def _wizard_done_types(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    w = _get_wizard(context)
    if not w or not w.get("content_types"):
        return
    w["_step"] = 7
    await _wizard_show_summary(context, w)


async def _wizard_show_summary(
    context: ContextTypes.DEFAULT_TYPE, w: dict
) -> None:
    word_count = filter_repo.count()
    text = texts.wizard_summary_text(w, word_count)
    kb = keyboards.kb_wizard_summary(w.get("use_blocked_words", True))
    await update_main_message(context, text, kb)


async def _wizard_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    w = _get_wizard(context)
    if not w:
        text, kb = renderer.render_main_menu()
        await update_main_message(context, text, kb)
        return

    source_ids: list = w.get("source_ids", [])
    source_names: list = w.get("source_names", [])
    if not source_ids:
        text, kb = renderer.render_error("לא נבחר אף מקור", "jobs")
        await update_main_message(context, text, kb)
        return

    name_base = w.get("name")
    dst_label = (w.get("dest_name") or "יעד").split("(")[0].strip()

    try:
        created = []
        for sid, sname in zip(source_ids, source_names):
            src_label = sname.split("(")[0].strip()
            if not name_base:
                job_name = f"{src_label} > {dst_label}"[:80]
            elif len(source_ids) > 1:
                job_name = f"{name_base} — {src_label}"[:80]
            else:
                job_name = name_base

            ct_set: set = w.get("content_types", {"text", "image", "video"})
            content_types_str = ",".join(sorted(ct_set)) if ct_set else "text,image,video"

            job = job_service.create_draft_job(
                name=job_name,
                source_id=sid,
                destination_id=w["dest_id"],
                mode=w["mode"],
                date_from=w.get("date_from"),
                date_to=w.get("date_to"),
                id_from=w.get("id_from"),
                id_to=w.get("id_to"),
                single_message_id=w.get("single_id"),
                use_blocked_words=w.get("use_blocked_words", True),
                content_types=content_types_str,
            )
            created.append(job)

        context.user_data.pop("wizard", None)  # type: ignore[union-attr]
        context.user_data.pop("awaiting_input", None)  # type: ignore[union-attr]
        if len(created) == 1:
            text, kb = renderer.render_job_detail(created[0].id)
        else:
            text, kb = renderer.render_job_list()
    except (JobError, ValidationError) as e:
        text, kb = renderer.render_error(str(e), "jobs")

    await update_main_message(context, text, kb)


# ── Text input handlers (called from the central dispatcher) ──────────────────

async def handle_job_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await delete_user_message(update)
    w = _get_wizard(context)
    if not w:
        return
    raw = (update.message.text or "").strip()  # type: ignore[union-attr]
    try:
        name = validation_service.validate_job_name(raw)
    except ValidationError as e:
        text, kb = renderer.render_wizard_step(
            f"⚠️ {e}\n\n{texts.WIZARD_ENTER_NAME}", w, keyboards.kb_wizard_cancel()
        )
        await update_main_message(context, text, kb)
        return

    w["name"] = name
    w["_step"] = 2
    context.user_data.pop("awaiting_input", None)  # type: ignore[union-attr]
    await _wizard_show_source_select(context, w)


async def handle_job_date_from(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await delete_user_message(update)
    w = _get_wizard(context)
    if not w:
        return
    raw = (update.message.text or "").strip()  # type: ignore[union-attr]
    try:
        dt = validation_service._parse_date(raw, "תאריך התחלה")
        w["date_from"] = raw
        context.user_data["awaiting_input"] = "job_date_to"  # type: ignore[index]
        text, kb = renderer.render_wizard_step(
            texts.WIZARD_ENTER_DATE_TO, w, keyboards.kb_wizard_cancel()
        )
    except ValidationError as e:
        text, kb = renderer.render_wizard_step(
            f"⚠️ {e}\n\n{texts.WIZARD_ENTER_DATE_FROM}", w, keyboards.kb_wizard_cancel()
        )
    await update_main_message(context, text, kb)


async def handle_job_date_to(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await delete_user_message(update)
    w = _get_wizard(context)
    if not w:
        return
    raw = (update.message.text or "").strip()  # type: ignore[union-attr]
    try:
        validation_service.validate_date_range(w.get("date_from", ""), raw)
        w["date_to"] = raw
        context.user_data.pop("awaiting_input", None)  # type: ignore[union-attr]
        w["_step"] = 6
        await _wizard_show_content_types(context, w)
    except ValidationError as e:
        text, kb = renderer.render_wizard_step(
            f"⚠️ {e}\n\n{texts.WIZARD_ENTER_DATE_TO}", w, keyboards.kb_wizard_cancel()
        )
        await update_main_message(context, text, kb)


async def handle_job_id_from(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await delete_user_message(update)
    w = _get_wizard(context)
    if not w:
        return
    raw = (update.message.text or "").strip()  # type: ignore[union-attr]
    try:
        val = validation_service.validate_single_id(raw)
        w["id_from"] = val
        context.user_data["awaiting_input"] = "job_id_to"  # type: ignore[index]
        text, kb = renderer.render_wizard_step(
            texts.WIZARD_ENTER_ID_TO, w, keyboards.kb_wizard_cancel()
        )
    except ValidationError as e:
        text, kb = renderer.render_wizard_step(
            f"⚠️ {e}\n\n{texts.WIZARD_ENTER_ID_FROM}", w, keyboards.kb_wizard_cancel()
        )
    await update_main_message(context, text, kb)


async def handle_job_id_to(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await delete_user_message(update)
    w = _get_wizard(context)
    if not w:
        return
    raw = (update.message.text or "").strip()  # type: ignore[union-attr]
    try:
        id_from = w.get("id_from", 0)
        id_to = validation_service.validate_single_id(raw)
        if id_from and id_to <= id_from:
            raise ValidationError("מזהה הסיום חייב להיות גדול ממזהה ההתחלה")
        w["id_to"] = id_to
        context.user_data.pop("awaiting_input", None)  # type: ignore[union-attr]
        w["_step"] = 6
        await _wizard_show_content_types(context, w)
    except ValidationError as e:
        text, kb = renderer.render_wizard_step(
            f"⚠️ {e}\n\n{texts.WIZARD_ENTER_ID_TO}", w, keyboards.kb_wizard_cancel()
        )
        await update_main_message(context, text, kb)


async def handle_job_single_id(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await delete_user_message(update)
    w = _get_wizard(context)
    if not w:
        return
    raw = (update.message.text or "").strip()  # type: ignore[union-attr]
    try:
        val = validation_service.validate_single_id(raw)
        w["single_id"] = val
        context.user_data.pop("awaiting_input", None)  # type: ignore[union-attr]
        w["_step"] = 6
        await _wizard_show_content_types(context, w)
    except ValidationError as e:
        text, kb = renderer.render_wizard_step(
            f"⚠️ {e}\n\n{texts.WIZARD_ENTER_SINGLE_ID}", w, keyboards.kb_wizard_cancel()
        )
        await update_main_message(context, text, kb)


async def handle_wzd_source_ref(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await delete_user_message(update)
    w = _get_wizard(context)
    raw = (update.message.text or "").strip()  # type: ignore[union-attr]
    try:
        ref = validation_service.validate_channel_ref(raw)
        src = source_repo.add_source(ref, ref)  # name = ref until worker resolves title
        context.user_data.pop("awaiting_input", None)  # type: ignore[union-attr]
        if w:
            ids: list = w.setdefault("source_ids", [])
            names: list = w.setdefault("source_names", [])
            if src.id not in ids:
                ids.append(src.id)
                names.append(src.display())
            w["_step"] = 2
            await _wizard_show_source_select(context, w)
        else:
            text, kb = renderer.render_source_list()
            await update_main_message(context, text, kb)
    except ValidationError as e:
        text = f"{texts.TITLE_SOURCES}\n\n⚠️ {e}\n\nהזן @username, מזהה מספרי, או קישור t.me/:"
        await update_main_message(context, text, keyboards.kb_wizard_cancel())


async def handle_wzd_dest_ref(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await delete_user_message(update)
    w = _get_wizard(context)
    raw = (update.message.text or "").strip()  # type: ignore[union-attr]
    try:
        ref = validation_service.validate_channel_ref(raw)
        dest = source_repo.add_destination(ref, ref)  # name = ref until worker resolves title
        context.user_data.pop("awaiting_input", None)  # type: ignore[union-attr]
        if w:
            w["dest_id"] = dest.id
            w["dest_name"] = dest.display()
            w["_step"] = 4
            await _wizard_show_mode_select(context, w)
        else:
            text, kb = renderer.render_dest_list()
            await update_main_message(context, text, kb)
    except ValidationError as e:
        text = f"{texts.TITLE_DESTINATIONS}\n\n⚠️ {e}\n\nהזן @username, מזהה מספרי, או קישור t.me/:"
        await update_main_message(context, text, keyboards.kb_wizard_cancel())
