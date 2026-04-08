"""Telethon entity-resolution helpers shared between worker modules."""
from __future__ import annotations

import re

from telethon import TelegramClient
from telethon.tl.types import PeerChannel, PeerChat


async def get_entity_safe(client: TelegramClient, ref: str):
    """
    Resolve a channel reference to a Telethon entity.
    Handles: @username, plain numeric ID, -100XXXXXXXXX (Bot API format).
    """
    ref = ref.strip()

    # Bot API format: -1001234567890 → PeerChannel(1234567890)
    if re.match(r"^-100\d+$", ref):
        channel_id = int(ref[4:])  # strip "-100"
        return await client.get_entity(PeerChannel(channel_id))

    # Negative group ID: -1234567890 → PeerChat
    if re.match(r"^-\d+$", ref):
        chat_id = int(ref[1:])
        return await client.get_entity(PeerChat(chat_id))

    # Plain positive integer — treat as channel ID (PeerChannel)
    if re.match(r"^\d+$", ref):
        try:
            return await client.get_entity(PeerChannel(int(ref)))
        except Exception:  # pylint: disable=broad-exception-caught
            return await client.get_entity(int(ref))

    # @username or username
    return await client.get_entity(ref)
