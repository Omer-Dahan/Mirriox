"""
Create anonymous Telegraph reports for completed jobs.

Reports contain t.me links to failed / unexpectedly-skipped messages only.
No job name, no channel name — neutral content per user requirement.
"""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

_API = "https://api.telegra.ph"
_MAX_ITEMS = 500  # cap to stay well within Telegraph's size limit


# ── Low-level HTTP ─────────────────────────────────────────────────────────────

def _post_sync(method: str, params: dict) -> dict:
    url = f"{_API}/{method}"
    data = json.dumps(params, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json; charset=utf-8"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ── Account token ──────────────────────────────────────────────────────────────

def _get_or_create_token_sync() -> str:
    from app.repositories import state_repo
    token = state_repo.get_setting("telegraph_token")
    if token:
        return token
    resp = _post_sync("createAccount", {
        "short_name": "msg_report",
        "author_name": "Message Report",
    })
    if not resp.get("ok"):
        raise RuntimeError(f"Telegraph createAccount failed: {resp}")
    token = resp["result"]["access_token"]
    state_repo.set_setting("telegraph_token", token)
    return token


# ── Link builder ───────────────────────────────────────────────────────────────

def _msg_link(msg_id: int, resolved_id: Optional[int], channel_ref: str) -> str:
    """Build a t.me deep link to a specific message."""
    if resolved_id:
        # resolved_id is already the bare channel ID (Telethon entity.id)
        return f"https://t.me/c/{resolved_id}/{msg_id}"
    # Fall back to username / ref
    ref = channel_ref.lstrip("@")
    if ref.startswith("t.me/"):
        ref = ref[5:]
    ref = ref.split("/")[-1]
    return f"https://t.me/{ref}/{msg_id}"


# ── Content builder ────────────────────────────────────────────────────────────

def _build_content(
    messages: list[dict],
    resolved_id: Optional[int],
    channel_ref: str,
) -> list:
    nodes: list = []

    failed  = [m for m in messages if m["status"] == "failed"][:_MAX_ITEMS]
    skipped = [m for m in messages if m["status"] == "skipped"][:_MAX_ITEMS]

    if failed:
        nodes.append({"tag": "h4", "children": [f"Failed ({len(failed)})"]})
        for m in failed:
            link = _msg_link(m["msg_id"], resolved_id, channel_ref)
            reason = m.get("reason") or "error"
            nodes.append({"tag": "p", "children": [
                {"tag": "a", "attrs": {"href": link}, "children": [f"#{m['msg_id']}"]},
                f"  —  {reason}",
            ]})

    if skipped:
        nodes.append({"tag": "h4", "children": [f"Skipped ({len(skipped)})"]})
        for m in skipped:
            link = _msg_link(m["msg_id"], resolved_id, channel_ref)
            reason = m.get("reason") or "skipped"
            nodes.append({"tag": "p", "children": [
                {"tag": "a", "attrs": {"href": link}, "children": [f"#{m['msg_id']}"]},
                f"  —  {reason}",
            ]})

    return nodes


# ── Public API ─────────────────────────────────────────────────────────────────

def create_sync(
    job_id: int,
    messages: list[dict],
    resolved_id: Optional[int],
    channel_ref: str,
) -> Optional[str]:
    """Synchronous Telegraph page creation. Returns URL or None."""
    if not messages:
        return None
    try:
        token = _get_or_create_token_sync()
        content = _build_content(messages, resolved_id, channel_ref)
        resp = _post_sync("createPage", {
            "access_token": token,
            "title": f"Report #{job_id}",
            "content": content,
            "return_content": False,
        })
        if resp.get("ok"):
            return resp["result"]["url"]
        logger.warning("Telegraph createPage failed: %s", resp)
        return None
    except Exception as exc:
        logger.warning("Telegraph report failed for job #%d: %s", job_id, exc)
        return None


async def create_report(
    job_id: int,
    messages: list[dict],
    resolved_id: Optional[int],
    channel_ref: str,
) -> Optional[str]:
    """Async wrapper — runs the sync call in a thread so the event loop is not blocked."""
    return await asyncio.to_thread(create_sync, job_id, messages, resolved_id, channel_ref)
