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
    "paused":        "⏸ מושהית",
    "completed":     "✅ הושלם",
    "cancelled":     "🚫 בוטל",
    "failed":        "❌ נכשל",
    "waiting_retry": "🔄 ממתין לניסיון חוזר",
}

STATUS_ICONS: dict[str, str] = {
    "draft":         "📝",
    "pending":       "⏳",
    "running":       "▶️",
    "paused":        "⏸",
    "completed":     "✅",
    "cancelled":     "🚫",
    "failed":        "❌",
    "waiting_retry": "🔄",
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
BTN_PAUSE_JOB       = "⏸ השהה משימה"
BTN_RESUME_JOB      = "▶️ המשך משימה"
BTN_CANCEL_JOB      = "⏹ בטל משימה"
BTN_DELETE_JOB      = "🗑 מחק משימה"
BTN_YES_DELETE      = "✅ כן, מחק"
BTN_YES_CANCEL      = "✅ כן, בטל"
BTN_YES_CLEAR       = "✅ כן, מחק הכל"
BTN_FILTER_TOGGLE_ON  = "🚫 סינון: כן"
BTN_FILTER_TOGGLE_OFF = "✅ סינון: לא"
BTN_GROUP_TOGGLE_ON   = "✅ שליחה במרוכז: כן"
BTN_GROUP_TOGGLE_OFF  = "❌ שליחה במרוכז: לא"
BTN_TEXT_TOGGLE_ON    = "✅ העתקת טקסט: כן"
BTN_TEXT_TOGGLE_OFF   = "❌ העתקת טקסט: לא"
BTN_SAVE_DRAFT      = "💾 שמור כטיוטה"
BTN_TRANSFER_STATS  = "📊 סטטיסטיקות העברות"

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
            f"📋 משימה פעילה: <b>{esc(active_job.name)}</b> "
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
    return f"{TITLE_JOBS}\n\nבחר משימה מהרשימה:"


# ── Job detail ─────────────────────────────────────────────────────────────────

def job_detail_text(
    job: "Job",
    source: "Source | None",
    dest: "Destination | None",
    queue_position: "int | None" = None,
) -> str:
    src_str = source.display() if source else f"[#{job.source_id}]"
    dst_str = dest.display() if dest else f"[#{job.destination_id}]"
    status_label = STATUS_LABELS.get(job.status, job.status)
    mode_label = MODE_LABELS.get(job.mode, job.mode)

    filter_str = "כן" if job.use_blocked_words else "לא"
    ct_parts = [p.strip() for p in (job.content_types or "text,image,video").split(",") if p.strip()]
    ct_map = {"image": "תמונות", "video": "סרטונים", "text": "טקסט"}
    ct_str = ", ".join(ct_map[p] for p in ("image", "video", "text") if p in ct_parts) or "—"

    params_line = ""
    if job.mode == "date_range":
        params_line = f"\nטווח: {job.date_from} – {job.date_to}"
    elif job.mode == "id_range":
        params_line = f"\nטווח מזהים: #{job.id_from} – #{job.id_to}"
    elif job.mode == "single_id":
        params_line = f"\nמזהה: #{job.single_message_id}"

    queue_line = f"\nמיקום בתור: #{queue_position}" if queue_position else ""

    retry_info = ""
    if job.status == "waiting_retry":
        retry_info = f"\n\nניסיון חוזר: {job.retry_count}/{job.max_retries}"
        if job.next_retry_at:
            retry_info += f" (ב-{_fmt_dt(job.next_retry_at)})"

    error_info = ""
    if job.error_message:
        error_info = f"\n\n⚠️ שגיאה אחרונה:\n<code>{esc(job.error_message[:200])}</code>"

    checkpoint = f"#{job.last_processed_id}" if job.last_processed_id else "—"
    started  = _fmt_dt(job.started_at)
    finished = _fmt_dt(job.completed_at)
    updated  = _fmt_dt(job.last_updated_at)

    report_line = ""
    if job.report_url:
        report_line = f"\n\n📋 <a href=\"{job.report_url}\">דוח שגיאות / דילוגים</a>"

    return (
        f"{status_label} {esc(job.name)}\n"
        f"\n"
        f"שם: {esc(job.name)}\n"
        f"מזהה: {job.id}\n"
        f"\n"
        f"מקור: {esc(src_str)}\n"
        f"יעד: {esc(dst_str)}\n"
        f"מצב: {mode_label}{params_line}\n"
        f"תוכן: {ct_str}\n"
        f"סינון מילים: {filter_str}\n"
        f"סטטוס: {status_label}{queue_line}"
        f"\n"
        f"\nתוצאות:\n"
        f"הועתקו: {job.copied_count}\n"
        f"דולגו: {job.skipped_count}\n"
        f"נכשלו: {job.failed_count}\n"
        f"נקודת המשך: {checkpoint}"
        f"\n"
        f"\nזמנים:\n"
        f"התחלה: {started}\n"
        f"סיום: {finished}\n"
        f"עדכון אחרון: {updated}"
        f"{retry_info}"
        f"{error_info}"
        f"{report_line}"
    )


# ── Job creation wizard ────────────────────────────────────────────────────────

def wizard_header(step: int, total: int, partial: dict) -> str:
    lines = [f"<b>שלב {step}/{total}</b>"]
    if partial.get("name"):
        lines.append(f"שם: {esc(partial['name'])}")
    names = partial.get("source_names", [])
    if names:
        if len(names) == 1:
            lines.append(f"מקור: {esc(names[0])}")
        else:
            lines.append(f"מקורות: {len(names)} נבחרו")
    if partial.get("dest_name"):
        lines.append(f"יעד: {esc(partial['dest_name'])}")
    if partial.get("mode"):
        lines.append(f"מצב: {MODE_LABELS.get(partial['mode'], partial['mode'])}")
    return "\n".join(lines)


WIZARD_SELECT_CONTENT_TYPES = "בחר אילו סוגי תוכן להעתיק:"
WIZARD_ENTER_NAME = "הזן שם למשימה:"
WIZARD_SELECT_SOURCE = "בחר ערוצי מקור (ניתן לבחור כמה) — לחץ ✔ סיים בחירה לאחר הבחירה:"
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
    group_status = "כן" if partial.get("group_media", True) else "לא"
    text_status = "כן" if partial.get("copy_text", True) else "לא"

    ct_set = partial.get("content_types", {"text", "image", "video"})
    ct_labels = []
    if "image" in ct_set:
        ct_labels.append("🖼 תמונות")
    if "video" in ct_set:
        ct_labels.append("🎬 סרטונים")
    if "text" in ct_set:
        ct_labels.append("💬 טקסט")
    content_types_str = ", ".join(ct_labels) if ct_labels else "—"

    params = ""
    if mode == "date_range":
        params = f"\nטווח תאריכים: {partial.get('date_from','?')} – {partial.get('date_to','?')}"
    elif mode == "id_range":
        params = f"\nטווח מזהים: #{partial.get('id_from','?')} – #{partial.get('id_to','?')}"
    elif mode == "single_id":
        params = f"\nמזהה הודעה: #{partial.get('single_id','?')}"

    src_names = partial.get("source_names", [])
    if len(src_names) == 1:
        src_str = esc(src_names[0])
    elif len(src_names) > 1:
        src_str = f"{len(src_names)} מקורות: " + ", ".join(esc(n) for n in src_names)
    else:
        src_str = "?"

    return (
        f"{TITLE_NEW_JOB}\n\n"
        f"📝 שם: <b>{esc(partial.get('name','?'))}</b>\n"
        f"📡 מקור: {src_str}\n"
        f"📤 יעד: {esc(partial.get('dest_name','?'))}\n"
        f"🔧 מצב: {mode_label}{params}\n"
        f"📁 סוגי תוכן: {content_types_str}\n"
        f"🚫 סינון מילים: {filter_status}\n"
        f"📦 שליחה במרוכז: {group_status}\n"
        f"📝 העתקת טקסט: {text_status}\n\n"
        f"אשר כדי לשמור כטיוטה."
    )


DAILY_LIMIT = 20_000


def moon_progress_bar(percent: float, total_cells: int = 10) -> str:
    """Moon-phase progress bar. Fills right→left (RTL): 🌑 empty, 🌒🌓🌔 partial, 🌕 full."""
    progress = max(0.0, min(100.0, percent)) / 100
    filled = progress * total_cells
    full_count = int(filled)
    remainder = filled - full_count

    if full_count < total_cells and remainder > 0:
        if remainder >= 0.67:
            partial = "🌔"
        elif remainder >= 0.34:
            partial = "🌓"
        else:
            partial = "🌒"
        empty_count = total_cells - full_count - 1
    else:
        partial = ""
        empty_count = total_cells - full_count

    return "🌑" * empty_count + partial + "🌕" * full_count


def transfer_stats_text(stats: dict) -> str:
    today = stats["since_midnight"]
    pct = min(today / DAILY_LIMIT * 100, 100)
    bar = moon_progress_bar(pct)
    remaining = max(DAILY_LIMIT - today, 0)
    limit_line = (
        f"\n{bar} {pct:.1f}%\n"
        f"נוצלו: <b>{today:,}</b> / {DAILY_LIMIT:,}  |  נותרו: <b>{remaining:,}</b>"
    )
    return (
        "📊 <b>סטטיסטיקות העברות</b>\n\n"
        f"🕐 שעה אחרונה: <b>{stats['last_hour']:,}</b> הודעות\n"
        f"📅 היום (מחצות): <b>{stats['since_midnight']:,}</b> הודעות\n"
        f"📆 24 שעות אחרונות: <b>{stats['last_24h']:,}</b> הודעות\n"
        f"\n<b>מגבלה יומית: {DAILY_LIMIT:,} הודעות</b>\n"
        f"{limit_line}"
    )


# ── Sources / destinations ─────────────────────────────────────────────────────

def source_list_text(sources: list["Source"]) -> str:
    if not sources:
        return f"{TITLE_SOURCES}\n\nלא הוגדרו מקורות עדיין."
    return f"{TITLE_SOURCES}\n\nבחר מקור מהרשימה:"


def source_detail_text(source: "Source") -> str:
    title = source.title or "—"
    rid = str(source.resolved_id) if source.resolved_id else "⏳ ממתין לאימות"
    status = "✅ נגיש" if source.resolved_id else ("❌ " + esc(source.validation_error) if source.validation_error else "⏳ טרם אומת")
    return (
        f"{TITLE_SOURCE_DETAIL}: <b>{esc(source.name)}</b>\n\n"
        f"הפניה: <code>{esc(source.channel_ref)}</code>\n"
        f"כותרת: {esc(title)}\n"
        f"מזהה: {rid}\n"
        f"גישה: {status}\n"
        + _channel_extra_lines(source) +
        f"נוסף: {_fmt_dt(source.created_at)}"
    )


def dest_list_text(dests: list["Destination"]) -> str:
    if not dests:
        return f"{TITLE_DESTINATIONS}\n\nלא הוגדרו יעדים עדיין."
    return f"{TITLE_DESTINATIONS}\n\nבחר יעד מהרשימה:"


def dest_detail_text(dest: "Destination") -> str:
    title = dest.title or "—"
    rid = str(dest.resolved_id) if dest.resolved_id else "⏳ ממתין לאימות"
    status = "✅ נגיש" if dest.resolved_id else ("❌ " + esc(dest.validation_error) if dest.validation_error else "⏳ טרם אומת")
    return (
        f"{TITLE_DEST_DETAIL}: <b>{esc(dest.name)}</b>\n\n"
        f"הפניה: <code>{esc(dest.channel_ref)}</code>\n"
        f"כותרת: {esc(title)}\n"
        f"מזהה: {rid}\n"
        f"גישה: {status}\n"
        + _channel_extra_lines(dest) +
        f"נוסף: {_fmt_dt(dest.created_at)}"
    )


def _channel_extra_lines(ch) -> str:
    """Build extra-info lines for a Source or Destination. Returns a string ending with \n."""
    lines = ""
    if ch.channel_type:
        lines += f"סוג: {esc(ch.channel_type)}"
        if ch.verified:
            lines += " ✅ מאומת"
        lines += "\n"
    if ch.username:
        lines += f"@: @{esc(ch.username)}\n"
    if ch.participants_count is not None:
        lines += f"👥 מנויים: {ch.participants_count:,}\n"
    if ch.about:
        about_short = ch.about[:120] + ("…" if len(ch.about) > 120 else "")
        lines += f"📝 תיאור: {esc(about_short)}\n"
    if ch.total_messages is not None or ch.photos_count is not None:
        stats = []
        if ch.total_messages is not None:
            stats.append(f"📨 {ch.total_messages:,} הודעות")
        if ch.photos_count is not None:
            stats.append(f"🖼 {ch.photos_count:,} תמונות")
        if ch.videos_count is not None:
            stats.append(f"🎬 {ch.videos_count:,} סרטונים")
        if ch.docs_count is not None:
            stats.append(f"📁 {ch.docs_count:,} קבצים")
        lines += " | ".join(stats) + "\n"
    if lines:
        lines = "\n" + lines + "\n"
    return lines


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
        lines.append(f"• {esc(w.word)}")
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

TOGGLE_SETTINGS: dict[str, str] = {
    "group_media": "קיבוץ תמונות/סרטונים לאלבום (עד 10)",
}

EDITABLE_SETTINGS = list(SETTINGS_LABELS.keys())


def settings_text(settings: dict[str, str]) -> str:
    lines = [f"{TITLE_SETTINGS}\n"]
    for key, label in SETTINGS_LABELS.items():
        val = settings.get(key, "—")
        lines.append(f"• {label}: <b>{esc(val)}</b>")
    for key, label in TOGGLE_SETTINGS.items():
        is_on = settings.get(key, "1") == "1"
        status = "✅ פעיל" if is_on else "❌ כבוי"
        lines.append(f"• {label}: <b>{status}</b>")
    return "\n".join(lines)


def prompt_setting(key: str) -> str:
    label = SETTINGS_LABELS.get(key, key)
    return f"{TITLE_SETTINGS}\n\nהזן ערך חדש עבור <b>{label}</b>:"


# ── Errors and confirmations ───────────────────────────────────────────────────

def error_text(msg: str) -> str:
    return f"{TITLE_ERROR}\n\n{esc(msg)}"


def confirm_delete_job_text(job_name: str) -> str:
    return (
        f"{TITLE_CONFIRM_DELETE}\n\n"
        f"האם למחוק את המשימה <b>{esc(job_name)}</b>?\n"
        "פעולה זו אינה הפיכה."
    )


def confirm_cancel_job_text(job_name: str) -> str:
    return (
        f"{TITLE_CONFIRM_CANCEL}\n\n"
        f"האם לבטל את המשימה <b>{esc(job_name)}</b>?"
    )


# ── Utilities ──────────────────────────────────────────────────────────────────

def esc(text: str | None) -> str:
    """Escape HTML special characters."""
    if text is None:
        return ""
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )


def _fmt_dt(dt_str: str | None) -> str:
    """Parse a UTC datetime string from SQLite and return it in Israel local time (Asia/Jerusalem)."""
    if not dt_str:
        return "—"
    try:
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        _IL = ZoneInfo("Asia/Jerusalem")
        dt = datetime.strptime(dt_str[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return dt.astimezone(_IL).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return dt_str[:16]
