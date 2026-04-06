"""Conservative rate limiter with FloodWait handling."""
from __future__ import annotations

import asyncio
import logging
import random

logger = logging.getLogger(__name__)


class RateLimiter:
    """Enforces a random delay between Telegram sends and handles FloodWait."""

    def __init__(self, min_ms: int = 1500, max_ms: int = 4000, flood_buffer_s: int = 5):
        self.min_ms = min_ms
        self.max_ms = max_ms
        self.flood_buffer_s = flood_buffer_s

    def update_from_settings(self, settings: dict[str, str]) -> None:
        try:
            self.min_ms = int(settings.get("min_delay_ms", self.min_ms))
            self.max_ms = int(settings.get("max_delay_ms", self.max_ms))
            self.flood_buffer_s = int(settings.get("flood_wait_buffer_s", self.flood_buffer_s))
            # Ensure min <= max
            if self.min_ms > self.max_ms:
                self.min_ms, self.max_ms = self.max_ms, self.min_ms
        except (ValueError, TypeError):
            pass

    async def wait(self) -> None:
        """Wait a random interval between min_ms and max_ms."""
        delay_s = random.uniform(self.min_ms / 1000.0, self.max_ms / 1000.0)
        await asyncio.sleep(delay_s)

    async def handle_flood_wait(self, seconds: int) -> None:
        """Wait the required FloodWait time plus the configured buffer."""
        total = seconds + self.flood_buffer_s
        logger.warning("FloodWait: waiting %d seconds (%d + %d buffer)", total, seconds, self.flood_buffer_s)
        await asyncio.sleep(total)
