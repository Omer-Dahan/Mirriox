"""InlineKeyboardMarkup builders. All callback_data follows domain:id:action format."""
from __future__ import annotations

from typing import TYPE_CHECKING
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.ui import texts

if TYPE_CHECKING:
    from app.models import Job, Source, Destination, BlockedWord, Admin


def _btn(label: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(label, callback_data=data)


def _back(target: str) -> list[InlineKeyboardButton]:
    return [_btn(texts.BTN_BACK, f"menu:{target}")]


def kb_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_btn(texts.BTN_JOBS, "menu:jobs"), _btn(texts.BTN_NEW_JOB, "job:new")],
        [_btn(texts.BTN_SOURCES, "menu:sources"), _btn(texts.BTN_DESTINATIONS, "menu:destinations")],
        [_btn(texts.BTN_BLOCKED_WORDS, "menu:filters"), _btn(texts.BTN_ADMINS, "menu:admins")],
        [_btn(texts.BTN_SETTINGS, "menu:settings")],
    ])


# ── Jobs ───────────────────────────────────────────────────────────────────────

def kb_job_list(jobs: list["Job"]) -> InlineKeyboardMarkup:
    rows = []
    for job in jobs:
        status_label = texts.STATUS_LABELS.get(job.status, job.status)
        label = f"{job.name} [{status_label}]"
        rows.append([_btn(label, f"job:{job.id}:view")])
    rows.append([_btn(texts.BTN_NEW_JOB, "job:new"), _btn(texts.BTN_MAIN_MENU, "menu:main")])
    return InlineKeyboardMarkup(rows)


def kb_job_detail(job: "Job") -> InlineKeyboardMarkup:
    rows = []

    if job.status == "draft":
        rows.append([_btn(texts.BTN_SUBMIT_JOB, f"job:{job.id}:submit")])
        rows.append([_btn(texts.BTN_DELETE_JOB, f"job:{job.id}:confirm_delete")])

    if job.status in ("pending", "running", "waiting_retry"):
        rows.append([_btn(texts.BTN_CANCEL_JOB, f"job:{job.id}:confirm_cancel")])

    if job.is_terminal():
        rows.append([_btn(texts.BTN_DELETE_JOB, f"job:{job.id}:confirm_delete")])

    rows.append([
        _btn(texts.BTN_REFRESH, f"job:{job.id}:view"),
        _btn(texts.BTN_BACK, "menu:jobs"),
    ])
    return InlineKeyboardMarkup(rows)


def kb_confirm_delete_job(job_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        _btn(texts.BTN_YES_DELETE, f"job:{job_id}:delete"),
        _btn(texts.BTN_CANCEL, f"job:{job_id}:view"),
    ]])


def kb_confirm_cancel_job(job_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        _btn(texts.BTN_YES_CANCEL, f"job:{job_id}:cancel"),
        _btn(texts.BTN_CANCEL, f"job:{job_id}:view"),
    ]])


# ── Wizard ─────────────────────────────────────────────────────────────────────

def kb_wizard_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_btn(texts.BTN_CANCEL, "job:cancel_wizard")]])


def kb_wizard_name_step() -> InlineKeyboardMarkup:
    """Name step: allow skipping to auto-generate name from channel names."""
    return InlineKeyboardMarkup([
        [_btn("⏭ דלג (שם אוטומטי)", "wzd:skip_name")],
        [_btn(texts.BTN_CANCEL, "job:cancel_wizard")],
    ])


def kb_wizard_source_list(
    sources: list["Source"], selected_ids: list[int] | None = None
) -> InlineKeyboardMarkup:
    if selected_ids is None:
        selected_ids = []
    rows = []
    for src in sources:
        check = "✅" if src.id in selected_ids else "◻"
        label = f"{check} {src.display()[:45]}"
        rows.append([_btn(label, f"wzd:toggle_src:{src.id}")])
    if selected_ids:
        rows.append([_btn("✔ סיים בחירה", "wzd:done_sources")])
    rows.append([_btn(texts.BTN_ADD + " מקור", "wzd:add_source")])
    rows.append([_btn(texts.BTN_CANCEL, "job:cancel_wizard")])
    return InlineKeyboardMarkup(rows)


def kb_wizard_dest_list(dests: list["Destination"]) -> InlineKeyboardMarkup:
    rows = []
    for dest in dests:
        label = dest.display()[:50]
        rows.append([_btn(label, f"wzd:dst:{dest.id}")])
    rows.append([_btn(texts.BTN_ADD + " יעד", "wzd:add_dest")])
    rows.append([_btn(texts.BTN_CANCEL, "job:cancel_wizard")])
    return InlineKeyboardMarkup(rows)


def kb_wizard_mode() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_btn(texts.MODE_LABELS["all"],        "wzd:mode:all")],
        [_btn(texts.MODE_LABELS["date_range"], "wzd:mode:date_range")],
        [_btn(texts.MODE_LABELS["id_range"],   "wzd:mode:id_range")],
        [_btn(texts.MODE_LABELS["single_id"],  "wzd:mode:single_id")],
        [_btn(texts.BTN_CANCEL, "job:cancel_wizard")],
    ])


def kb_wizard_summary(use_blocked_words: bool) -> InlineKeyboardMarkup:
    filter_btn_label = texts.BTN_FILTER_TOGGLE_ON if use_blocked_words else texts.BTN_FILTER_TOGGLE_OFF
    return InlineKeyboardMarkup([
        [_btn(texts.BTN_SAVE_DRAFT, "wzd:confirm")],
        [_btn(filter_btn_label, "wzd:toggle_filter")],
        [_btn(texts.BTN_CANCEL, "job:cancel_wizard")],
    ])


# ── Sources ────────────────────────────────────────────────────────────────────

def kb_source_list(sources: list["Source"]) -> InlineKeyboardMarkup:
    rows = []
    for src in sources:
        label = src.display()[:50]
        rows.append([_btn(label, f"src:{src.id}:view")])
    rows.append([_btn(texts.BTN_ADD + " מקור", "src:new")])
    rows.append([_btn(texts.BTN_MAIN_MENU, "menu:main")])
    return InlineKeyboardMarkup(rows)


def kb_source_detail(source_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_btn(texts.BTN_DELETE, f"src:{source_id}:confirm_delete")],
        [_btn(texts.BTN_BACK, "menu:sources")],
    ])


def kb_confirm_delete_source(source_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        _btn(texts.BTN_YES_DELETE, f"src:{source_id}:delete"),
        _btn(texts.BTN_CANCEL, f"src:{source_id}:view"),
    ]])


# ── Destinations ───────────────────────────────────────────────────────────────

def kb_dest_list(dests: list["Destination"]) -> InlineKeyboardMarkup:
    rows = []
    for dest in dests:
        label = dest.display()[:50]
        rows.append([_btn(label, f"dst:{dest.id}:view")])
    rows.append([_btn(texts.BTN_ADD + " יעד", "dst:new")])
    rows.append([_btn(texts.BTN_MAIN_MENU, "menu:main")])
    return InlineKeyboardMarkup(rows)


def kb_dest_detail(dest_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_btn(texts.BTN_DELETE, f"dst:{dest_id}:confirm_delete")],
        [_btn(texts.BTN_BACK, "menu:destinations")],
    ])


def kb_confirm_delete_dest(dest_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        _btn(texts.BTN_YES_DELETE, f"dst:{dest_id}:delete"),
        _btn(texts.BTN_CANCEL, f"dst:{dest_id}:view"),
    ]])


# ── Filters ────────────────────────────────────────────────────────────────────

def kb_blocked_words(words: list["BlockedWord"]) -> InlineKeyboardMarkup:
    rows = []
    for w in words:
        label = f"🗑 {w.word[:30]}"
        rows.append([_btn(label, f"flt:{w.id}:delete")])
    rows.append([_btn(texts.BTN_ADD + " מילה", "flt:new")])
    if words:
        rows.append([_btn("🗑 מחק הכל", "flt:confirm_clear")])
    rows.append([_btn(texts.BTN_MAIN_MENU, "menu:main")])
    return InlineKeyboardMarkup(rows)


def kb_confirm_clear_words() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        _btn(texts.BTN_YES_CLEAR, "flt:clear"),
        _btn(texts.BTN_CANCEL, "menu:filters"),
    ]])


def kb_filter_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_btn(texts.BTN_CANCEL, "menu:filters")]])


def kb_source_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_btn(texts.BTN_CANCEL, "menu:sources")]])


def kb_dest_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_btn(texts.BTN_CANCEL, "menu:destinations")]])


# ── Admins ─────────────────────────────────────────────────────────────────────

def kb_admin_list(admins: list["Admin"], bootstrap_ids: list[int]) -> InlineKeyboardMarkup:
    rows = []
    for a in admins:
        if a.telegram_id not in bootstrap_ids:
            label = f"🗑 {a.username or str(a.telegram_id)}"
            rows.append([_btn(label, f"adm:{a.telegram_id}:confirm_remove")])
    rows.append([_btn(texts.BTN_ADD + " מנהל", "adm:new")])
    rows.append([_btn(texts.BTN_MAIN_MENU, "menu:main")])
    return InlineKeyboardMarkup(rows)


def kb_confirm_remove_admin(telegram_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        _btn("✅ כן, הסר", f"adm:{telegram_id}:remove"),
        _btn(texts.BTN_CANCEL, "menu:admins"),
    ]])


def kb_admin_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_btn(texts.BTN_CANCEL, "menu:admins")]])


# ── Settings ───────────────────────────────────────────────────────────────────

def kb_settings(settings: dict[str, str]) -> InlineKeyboardMarkup:
    rows = []
    for key in texts.EDITABLE_SETTINGS:
        label = texts.SETTINGS_LABELS.get(key, key)
        val = settings.get(key, "—")
        rows.append([_btn(f"{label}: {val}", f"cfg:{key}")])
    rows.append([_btn(texts.BTN_MAIN_MENU, "menu:main")])
    return InlineKeyboardMarkup(rows)


def kb_setting_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_btn(texts.BTN_CANCEL, "menu:settings")]])


# ── Generic error back button ──────────────────────────────────────────────────

def kb_error_back(target: str = "main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_btn(texts.BTN_BACK, f"menu:{target}")]])
