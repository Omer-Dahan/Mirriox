"""
Assembles the text + keyboard for each bot screen.
Every render_* function returns (text, InlineKeyboardMarkup).
"""
from __future__ import annotations

from typing import TYPE_CHECKING
from telegram import InlineKeyboardMarkup

from app.ui import texts, keyboards
from app.repositories import source_repo, filter_repo, state_repo

if TYPE_CHECKING:
    from app.models import Job, Source, Destination, Admin, BlockedWord, WorkerState


def render_main_menu() -> tuple[str, InlineKeyboardMarkup]:
    worker = state_repo.get_worker_state()
    from app.repositories import job_repo
    active = job_repo.get_active_job()
    text = texts.main_menu_text(worker.status, active)
    return text, keyboards.kb_main_menu()


def render_job_list() -> tuple[str, InlineKeyboardMarkup]:
    from app.repositories import job_repo
    jobs = job_repo.get_all()
    return texts.jobs_list_text(jobs), keyboards.kb_job_list(jobs)


def render_job_detail(job_id: int) -> tuple[str, InlineKeyboardMarkup]:
    from app.repositories import job_repo
    job = job_repo.get_by_id(job_id)
    if job is None:
        return texts.error_text(f"משימה #{job_id} לא נמצאה"), keyboards.kb_error_back("jobs")
    src = source_repo.get_source_by_id(job.source_id)
    dst = source_repo.get_destination_by_id(job.destination_id)
    return texts.job_detail_text(job, src, dst), keyboards.kb_job_detail(job)


def render_job_confirm_delete(job: "Job") -> tuple[str, InlineKeyboardMarkup]:
    return (
        texts.confirm_delete_job_text(job.name),
        keyboards.kb_confirm_delete_job(job.id),
    )


def render_job_confirm_cancel(job: "Job") -> tuple[str, InlineKeyboardMarkup]:
    return (
        texts.confirm_cancel_job_text(job.name),
        keyboards.kb_confirm_cancel_job(job.id),
    )


def render_source_list() -> tuple[str, InlineKeyboardMarkup]:
    sources = source_repo.get_all_sources()
    return texts.source_list_text(sources), keyboards.kb_source_list(sources)


def render_source_detail(source_id: int) -> tuple[str, InlineKeyboardMarkup]:
    src = source_repo.get_source_by_id(source_id)
    if src is None:
        return texts.error_text("מקור לא נמצא"), keyboards.kb_error_back("sources")
    return texts.source_detail_text(src), keyboards.kb_source_detail(source_id)


def render_dest_list() -> tuple[str, InlineKeyboardMarkup]:
    dests = source_repo.get_all_destinations()
    return texts.dest_list_text(dests), keyboards.kb_dest_list(dests)


def render_dest_detail(dest_id: int) -> tuple[str, InlineKeyboardMarkup]:
    dest = source_repo.get_destination_by_id(dest_id)
    if dest is None:
        return texts.error_text("יעד לא נמצא"), keyboards.kb_error_back("destinations")
    return texts.dest_detail_text(dest), keyboards.kb_dest_detail(dest_id)


def render_blocked_words() -> tuple[str, InlineKeyboardMarkup]:
    words = filter_repo.get_all()
    return texts.blocked_words_text(words), keyboards.kb_blocked_words(words)


def render_admin_list(bootstrap_ids: list[int]) -> tuple[str, InlineKeyboardMarkup]:
    from app.repositories import admin_repo
    admins = admin_repo.get_all()
    return (
        texts.admin_list_text(admins, bootstrap_ids),
        keyboards.kb_admin_list(admins, bootstrap_ids),
    )


def render_settings() -> tuple[str, InlineKeyboardMarkup]:
    settings = state_repo.get_settings_dict()
    return texts.settings_text(settings), keyboards.kb_settings(settings)


def render_error(msg: str, back_target: str = "main") -> tuple[str, InlineKeyboardMarkup]:
    return texts.error_text(msg), keyboards.kb_error_back(back_target)


def render_wizard_step(
    step_text: str,
    partial: dict,
    keyboard: InlineKeyboardMarkup,
) -> tuple[str, InlineKeyboardMarkup]:
    header = texts.wizard_header(
        partial.get("_step", 1),
        partial.get("_total", 6),
        partial,
    )
    return f"{texts.TITLE_NEW_JOB}\n\n{header}\n\n{step_text}", keyboard
