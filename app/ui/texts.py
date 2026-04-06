"""All Hebrew UI strings. Single source of truth for the management bot."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import Job, Source, Destination, Admin, BlockedWord, WorkerState

# ── Status labels ──────────────────────────────────────────────────────────────

STATUS_LABELS: dict[str, str] = {
    "draft":         "📝 טיוטה",
    "pending":       "⏳ ממתין לביצוע",
    "running":       "▶️ פועל",
    "paused":        "⏸ מושהה",
    "completed":     "✅ הושלם",
    "cancelled":     "🚫 בוטל",
    "failed":        "❌ נכשל",
    "waiting_retry": "🔄 ממתין לניסיון חוזר",
}

MODE_LABELS: dict[str, str] = {
    "all":        "📋 כל ההודעות",
    "date_range": "📅 טווח תאריכים",
    "id_range":   "🔢 טווח מזהים",
    "single_id":  "1️⃣ הודעה בודדת",
}

WORKER_STATUS_LABELS: dict[str, str] = {
    "idle":    "💤 במתינה",
    "running": "▶️ פועל",
    "stopped": "⏹ עצור",
    "error":   "❌ שגיאה",
}

# ── Button labels ──────────────────────────────────────────────────────────────

BTN_MAIN_MENU       = "🏠 תפריט ראשי"
BTN_JOBS            = "📂 משימות"
BTN_NEW_JOB         = "➕ משימה חדשה"
BTN_SOURCES         = "📡 מקורות"
BTN_DESTINATIONS    = "📤 יעדים"
BTN_BLOCKED_WORDS   = "🚫 מילים חסומות"
BTN_ADMINS          = "👥 מנהלים"
BTN_SETTINGS        = "⚙️ הגדרות"
BTN_BACK            = "⬅️ חזרה"
BTN_CANCEL          = "❌ ביטול"
BTN_CONFIRM         = "✅ אישור"
BTN_DELETE          = "🗑 מחק"
BTN_REFRESH         = "🔄 רענן"
BTN_ADD             = "➕ הוסף"
BTN_SUBMIT_JOB      = "▶️ הגש להרצה"
BTN_CANCEL_JOB      = "⏹ בטל משימה"
BTN_DELETE_JOB      = "🗑 מחק משימה"
BTN_YES_DELETE      = "✅ כן, מחק"
BTN_YES_CANCEL      = "✅ כן, בטל"
BTN_YES_CLEAR       = "✅ כן, מחק הכל"
BTN_FILTER_TOGGLE_ON  = "🚫 סינון: כן"
BTN_FILTER_TOGGLE_OFF = "✅ סינון: לא"
BTN_SAVE_DRAFT      = "💾 שמור כטיוטה"

# ── Screen titles ──────────────────────────────────────────────────────────────

TITLE_MAIN_MENU       = "🏠 <b>מיריוקס — לוח בקרה</b>"
TITLE_JOBS            = "📂 <b>משימות</b>"
TITLE_JOB_DETAIL      = "📋 <b>פרטי משימה</b>"
TITLE_NEW_JOB         = "➕ <b>משימה חדשה</b>"
TITLE_SOURCES         = "📡 <b>ערוצי מקור</b>"
TITLE_SOURCE_DETAIL   = "📡 <b>פרטי מקור</b>"
TITLE_DESTINATIONS    = "📤 <b>ערוצי יעד</b>"
TITLE_DEST_DETAIL     = "📤 <b>פרטי יעד</b>"
TITLE_BLOCKED_WORDS   = "🚫 <b>מילים חסומות</b>"
TITLE_ADMINS          = "👥 <b>מנהלים</b>"
TITLE_SETTINGS        = "⚙️ <b>הגדרות</b>"
TITLE_CONFIRM_DELETE  = "⚠️ <b>אישור מחיקה</b>"
TITLE_CONFIRM_CANCEL  = "⚠️ <b>אישור ביטול</b>"
TITLE_CONFIRM_CLEAR   = "⚠️ <b>אישור מחיקת כל המילים</b>"
TITLE_ERROR           = "❌ <b>שגיאה</b>"

# ── Main menu ──────────────────────────────────────────────────────────────────

def main_menu_text(worker_status: str, active_job: "Job | None") -> str:
    ws_label = WORKER_STATUS_LABELS.get(worker_status, worker_status)
    if active_job:
        job_line = (
            f"📋 משימה פעילה: <b>{_esc(active_job.name)}</b> "
            f"[{STATUS_LABELS.get(active_job.status, active_job.status)}]\n"
            f"   הועתקו: {active_job.copied_count} | דולגו: {active_job.skipped_count}"
        )
    else:
        job_line = "אין משימה פעילה כרגע"

    return (
        f"{TITLE_MAIN_MENU}\n\n"
        f"🖥 עובד: {ws_label}\n"
        f"{job_line}"
    )


# ── Job list ───────────────────────────────────────────────────────────────────

def jobs_list_text(jobs: list["Job"]) -> str:
    if not jobs:
        return f"{TITLE_JOBS}\n\nאין משימות עדיין."
    lines = [f"{TITLE_JOBS}\n"]
    for job in jobs:
        status_label = STATUS_LABELS.get(job.status, job.status)
        lines.append(f"• <b>{_esc(job.name)}</b> — {status_label}")
    return "\n".join(lines)


# ── Job detail ─────────────────────────────────────────────────────────────────

def job_detail_text(
    job: "Job",
    source: "Source | None",
    dest: "Destination | None",
) -> str:
    src_str = source.display() if source else f"[#{job.source_id}]"
    dst_str = dest.display() if dest else f"[#{job.destination_id}]"
    status_label = STATUS_LABELS.get(job.status, job.status)
    mode_label = MODE_LABELS.get(job.mode, job.mode)

    params = _mode_params_text(job)
    filter_str = "כן" if job.use_blocked_words else "לא"

    progress = (
        f"סרוקו: — | הועתקו: {job.copied_count} | "
        f"דולגו: {job.skipped_count} | נכשלו: {job.failed_count}"
    )

    checkpoint = (
        f"נקודת המשך: #{job.last_processed_id}" if job.last_processed_id else "—"
    )

    retry_info = ""
    if job.status == "waiting_retry":
        retry_info = f"\n🔄 ניסיון חוזר: {job.retry_count}/{job.max_retries}"
        if job.next_retry_at:
            retry_info += f" (ב-{_fmt_dt(job.next_retry_at)})"

    error_info = ""
    if job.error_message:
        error_info = f"\n⚠️ שגיאה אחרונה:\n<code>{_esc(job.error_message[:200])}</code>"

    started = _fmt_dt(job.started_at) if job.started_at else "—"
    finished = _fmt_dt(job.completed_at) if job.completed_at else "—"
    updated = _fmt_dt(job.last_updated_at)

    return (
        f"{TITLE_JOB_DETAIL}: <b>{_esc(job.name)}</b>\n\n"
        f"📡 מקור: {_esc(src_str)}\n"
        f"📤 יעד: {_esc(dst_str)}\n"
        f"🔧 מצב: {mode_label}\n"
        f"{params}"
        f"🚫 סינון מילים: {filter_str}\n"
        f"🔵 סטטוס: {status_label}\n\n"
        f"📊 {progress}\n"
        f"📍 {checkpoint}\n"
        f"🕐 התחלה: {started} | סיום: {finished}\n"
        f"🔃 עדכון: {updated}"
        f"{retry_info}"
        f"{error_info}"
    )


def _mode_params_text(job: "Job") -> str:
    if job.mode == "date_range":
        return f"📅 מ: {job.date_from} עד: {job.date_to}\n"
    if job.mode == "id_range":
        return f"🔢 מ: #{job.id_from} עד: #{job.id_to}\n"
    if job.mode == "single_id":
        return f"1️⃣ הודעה: #{job.single_message_id}\n"
    return ""


# ── Job creation wizard ────────────────────────────────────────────────────────

def wizard_header(step: int, total: int, partial: dict) -> str:
    lines = [f"<b>שלב {step}/{total}</b>"]
    if partial.get("name"):
        lines.append(f"שם: {_esc(partial['name'])}")
    if partial.get("source_name"):
        lines.append(f"מקור: {_esc(partial['source_name'])}")
    if partial.get("dest_name"):
        lines.append(f"יעד: {_esc(partial['dest_name'])}")
    if partial.get("mode"):
        lines.append(f"מצב: {MODE_LABELS.get(partial['mode'], partial['mode'])}")
    return "\n".join(lines)


WIZARD_ENTER_NAME = "הזן שם למשימה:"
WIZARD_SELECT_SOURCE = "בחר ערוץ מקור:"
WIZARD_SELECT_DEST = "בחר ערוץ יעד:"
WIZARD_SELECT_MODE = "בחר מצב העתקה:"
WIZARD_ENTER_DATE_FROM = "הזן תאריך התחלה (DD/MM/YYYY או DD/MM/YYYY HH:MM):"
WIZARD_ENTER_DATE_TO = "הזן תאריך סיום (DD/MM/YYYY או DD/MM/YYYY HH:MM):"
WIZARD_ENTER_ID_FROM = "הזן מזהה הודעה ראשונה (מספר):"
WIZARD_ENTER_ID_TO = "הזן מזהה הודעה אחרונה (מספר):"
WIZARD_ENTER_SINGLE_ID = "הזן מזהה ההודעה:"
WIZARD_FILTER_AND_CONFIRM = "בדוק את הפרטים ואשר:"

NO_SOURCES_YET = "לא הוגדרו מקורות עדיין. הוסף מקור תחילה."
NO_DESTINATIONS_YET = "לא הוגדרו יעדים עדיין. הוסף יעד תחילה."


def wizard_summary_text(partial: dict, word_count: int) -> str:
    mode = partial.get("mode", "")
    mode_label = MODE_LABELS.get(mode, mode)
    filter_status = f"כן ({word_count} מילים)" if partial.get("use_blocked_words", True) else "לא"

    params = ""
    if mode == "date_range":
        params = f"\nטווח תאריכים: {partial.get('date_from','?')} – {partial.get('date_to','?')}"
    elif mode == "id_range":
        params = f"\nטווח מזהים: #{partial.get('id_from','?')} – #{partial.get('id_to','?')}"
    elif mode == "single_id":
        params = f"\nמזהה הודעה: #{partial.get('single_id','?')}"

    return (
        f"{TITLE_NEW_JOB}\n\n"
        f"📝 שם: <b>{_esc(partial.get('name','?'))}</b>\n"
        f"📡 מקור: {_esc(partial.get('source_name','?'))}\n"
        f"📤 יעד: {_esc(partial.get('dest_name','?'))}\n"
        f"🔧 מצב: {mode_label}{params}\n"
        f"🚫 סינון מילים: {filter_status}\n\n"
        f"אשר כדי לשמור כטיוטה."
    )


# ── Sources / destinations ─────────────────────────────────────────────────────

def source_list_text(sources: list["Source"]) -> str:
    if not sources:
        return f"{TITLE_SOURCES}\n\nלא הוגדרו מקורות עדיין."
    lines = [f"{TITLE_SOURCES}\n"]
    for s in sources:
        title = s.title or s.channel_ref
        lines.append(f"• <b>{_esc(s.name)}</b> — {_esc(title)}")
    return "\n".join(lines)


def source_detail_text(source: "Source") -> str:
    title = source.title or "—"
    rid = str(source.resolved_id) if source.resolved_id else "⏳ ממתין לאימות"
    status = "✅ נגיש" if source.resolved_id else ("❌ " + _esc(source.validation_error) if source.validation_error else "⏳ טרם אומת")
    return (
        f"{TITLE_SOURCE_DETAIL}: <b>{_esc(source.name)}</b>\n\n"
        f"כינוי: {_esc(source.name)}\n"
        f"הפניה: <code>{_esc(source.channel_ref)}</code>\n"
        f"כותרת: {_esc(title)}\n"
        f"מזהה: {rid}\n"
        f"גישה: {status}\n"
        f"נוסף: {_fmt_dt(source.created_at)}"
    )


def dest_list_text(dests: list["Destination"]) -> str:
    if not dests:
        return f"{TITLE_DESTINATIONS}\n\nלא הוגדרו יעדים עדיין."
    lines = [f"{TITLE_DESTINATIONS}\n"]
    for d in dests:
        title = d.title or d.channel_ref
        lines.append(f"• <b>{_esc(d.name)}</b> — {_esc(title)}")
    return "\n".join(lines)


def dest_detail_text(dest: "Destination") -> str:
    title = dest.title or "—"
    rid = str(dest.resolved_id) if dest.resolved_id else "⏳ ממתין לאימות"
    status = "✅ נגיש" if dest.resolved_id else ("❌ " + _esc(dest.validation_error) if dest.validation_error else "⏳ טרם אומת")
    return (
        f"{TITLE_DEST_DETAIL}: <b>{_esc(dest.name)}</b>\n\n"
        f"כינוי: {_esc(dest.name)}\n"
        f"הפניה: <code>{_esc(dest.channel_ref)}</code>\n"
        f"כותרת: {_esc(title)}\n"
        f"מזהה: {rid}\n"
        f"גישה: {status}\n"
        f"נוסף: {_fmt_dt(dest.created_at)}"
    )


PROMPT_SOURCE_NAME = f"{TITLE_SOURCES}\n\nשלב 1 — הזן שם כינוי למקור:"
PROMPT_SOURCE_REF  = f"{TITLE_SOURCES}\n\nשלב 2 — הזן @username, מזהה מספרי, או קישור t.me/:"
PROMPT_DEST_NAME   = f"{TITLE_DESTINATIONS}\n\nשלב 1 — הזן שם כינוי ליעד:"
PROMPT_DEST_REF    = f"{TITLE_DESTINATIONS}\n\nשלב 2 — הזן @username, מזהה מספרי, או קישור t.me/:"
CONFIRM_DELETE_SOURCE = "האם למחוק את המקור? פעולה זו אינה הפיכה."
CONFIRM_DELETE_DEST   = "האם למחוק את היעד? פעולה זו אינה הפיכה."


# ── Blocked words ──────────────────────────────────────────────────────────────

def blocked_words_text(words: list["BlockedWord"]) -> str:
    if not words:
        return f"{TITLE_BLOCKED_WORDS}\n\nאין מילים חסומות."
    lines = [f"{TITLE_BLOCKED_WORDS}\n", f"סה\"כ: {len(words)} מילים\n"]
    for w in words:
        lines.append(f"• {_esc(w.word)}")
    return "\n".join(lines)


PROMPT_BLOCKED_WORD = f"{TITLE_BLOCKED_WORDS}\n\nהזן מילה לחסימה:"
CONFIRM_CLEAR_WORDS = "האם למחוק את כל המילים החסומות? פעולה זו אינה הפיכה."


# ── Admins ─────────────────────────────────────────────────────────────────────

def admin_list_text(admins: list["Admin"], bootstrap_ids: list[int]) -> str:
    lines = [f"{TITLE_ADMINS}\n"]
    if not admins and not bootstrap_ids:
        lines.append("אין מנהלים מוגדרים.")
    else:
        for tid in bootstrap_ids:
            lines.append(f"• <code>{tid}</code> — מוגדר ב-config (לא ניתן להסרה)")
        for a in admins:
            if a.telegram_id not in bootstrap_ids:
                uname = f"@{a.username}" if a.username else ""
                lines.append(f"• {uname} <code>{a.telegram_id}</code>")
    lines.append("\n⚠️ מנהלי ה-bootstrap מוגדרים ב-.env ואינם ניתנים להסרה דרך הממשק.")
    return "\n".join(lines)


PROMPT_ADMIN_ID = f"{TITLE_ADMINS}\n\nהזן מזהה Telegram של המנהל החדש (מספר):"
CONFIRM_REMOVE_ADMIN = "האם להסיר מנהל זה?"


# ── Settings ───────────────────────────────────────────────────────────────────

SETTINGS_LABELS: dict[str, str] = {
    "min_delay_ms":         "עיכוב מינימלי (מ\"ש)",
    "max_delay_ms":         "עיכוב מקסימלי (מ\"ש)",
    "flood_wait_buffer_s":  "כיסוי FloodWait (שניות)",
    "max_retries":          "מקסימום ניסיונות חוזרים",
    "heartbeat_interval_s": "מרווח דופק עובד (שניות)",
}

EDITABLE_SETTINGS = list(SETTINGS_LABELS.keys())


def settings_text(settings: dict[str, str]) -> str:
    lines = [f"{TITLE_SETTINGS}\n"]
    for key, label in SETTINGS_LABELS.items():
        val = settings.get(key, "—")
        lines.append(f"• {label}: <b>{_esc(val)}</b>")
    return "\n".join(lines)


def prompt_setting(key: str) -> str:
    label = SETTINGS_LABELS.get(key, key)
    return f"{TITLE_SETTINGS}\n\nהזן ערך חדש עבור <b>{label}</b>:"


# ── Errors and confirmations ───────────────────────────────────────────────────

def error_text(msg: str) -> str:
    return f"{TITLE_ERROR}\n\n{_esc(msg)}"


def confirm_delete_job_text(job_name: str) -> str:
    return (
        f"{TITLE_CONFIRM_DELETE}\n\n"
        f"האם למחוק את המשימה <b>{_esc(job_name)}</b>?\n"
        "פעולה זו אינה הפיכה."
    )


def confirm_cancel_job_text(job_name: str) -> str:
    return (
        f"{TITLE_CONFIRM_CANCEL}\n\n"
        f"האם לבטל את המשימה <b>{_esc(job_name)}</b>?"
    )


# ── Utilities ──────────────────────────────────────────────────────────────────

def _esc(text: str | None) -> str:
    """Escape HTML special characters."""
    if text is None:
        return ""
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )


def _fmt_dt(dt_str: str | None) -> str:
    if not dt_str:
        return "—"
    # SQLite returns 'YYYY-MM-DD HH:MM:SS', show as 'DD/MM/YYYY HH:MM'
    try:
        from datetime import datetime
        dt = datetime.strptime(dt_str[:19], "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return dt_str[:16]
