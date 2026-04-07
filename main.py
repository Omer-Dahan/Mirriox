"""
Mirriox — entry point.

Usage:
  python main.py          Run bot + worker together (default)
  python main.py bot      Run the management bot only
  python main.py worker   Run the userbot worker only
  python main.py setup    Authenticate the Telethon session interactively
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("telethon").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)


def main() -> None:
    _setup_logging()
    logger = logging.getLogger(__name__)

    parser = argparse.ArgumentParser(description="Mirriox Telegram Copier")
    parser.add_argument(
        "mode",
        nargs="?",
        default="all",
        choices=["all", "bot", "worker", "setup"],
        help="Component to run (default: all — bot + worker together)",
    )
    args = parser.parse_args()

    from app.config import load_config
    import app.db as db

    config = load_config()
    db.init(config.DB_PATH)
    db.init_schema()

    if args.mode == "all":
        logger.info("Starting bot + worker together (DB: %s)", config.DB_PATH)
        asyncio.run(_run_all(config))

    elif args.mode == "bot":
        logger.info("Starting management bot only (DB: %s)", config.DB_PATH)
        from app.bot.bot_main import run
        run(config)

    elif args.mode == "worker":
        logger.info("Starting userbot worker only (DB: %s)", config.DB_PATH)
        from app.worker.worker_main import run
        run(config)

    elif args.mode == "setup":
        _run_setup(config)


_NETWORK_ERROR_HINTS = (
    "getaddrinfo failed",
    "ConnectError",
    "ConnectionError",
    "ConnectionResetError",
    "RemoteProtocolError",
    "NetworkError",
    "TimeoutError",
    "WinError 1231",
    "WinError 10060",
    "WinError 10061",
    "WinError 1236",
    "Network is unreachable",
    "Connection refused",
    "Server disconnected",
    "OSError",
)


def _is_network_error(exc: BaseException) -> bool:
    msg = f"{type(exc).__name__}: {exc}"
    return any(hint in msg for hint in _NETWORK_ERROR_HINTS)


async def _run_with_restart(name: str, coro_fn, config) -> None:
    """Wrap a long-running coroutine with automatic restart on network errors."""
    _logger = logging.getLogger(__name__)
    delay = 5
    max_delay = 120
    while True:
        try:
            await coro_fn(config)
            return  # clean exit
        except asyncio.CancelledError:
            raise  # shutdown requested — do not restart
        except Exception as exc:
            if _is_network_error(exc):
                _logger.warning(
                    "[%s] ניתוק רשת (%s) — מנסה שוב בעוד %ds...",
                    name, exc, delay,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, max_delay)
            else:
                _logger.exception("[%s] שגיאה קריטית — מפסיק: %s", name, exc)
                raise


async def _run_all(config) -> None:
    """Run bot and worker concurrently, with auto-restart on network errors."""
    from app.bot.bot_main import run_async as bot_run_async
    from app.worker.worker_main import run_async as worker_run_async

    worker_task = asyncio.create_task(
        _run_with_restart("worker", worker_run_async, config), name="worker"
    )
    bot_task = asyncio.create_task(
        _run_with_restart("bot", bot_run_async, config), name="bot"
    )

    try:
        done, pending = await asyncio.wait(
            [bot_task, worker_task],
            return_when=asyncio.FIRST_EXCEPTION,
        )
        for task in done:
            if task.exception():
                raise task.exception()  # type: ignore[misc]
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        for task in [bot_task, worker_task]:
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass


def _run_setup(config) -> None:
    """Interactive Telethon session setup."""
    from telethon import TelegramClient

    logger = logging.getLogger("setup")
    logger.info("Setting up Telethon session: %s", config.TELETHON_SESSION)

    session_dir = os.path.dirname(config.TELETHON_SESSION)
    if session_dir:
        os.makedirs(session_dir, exist_ok=True)

    phone = input("מספר טלפון (עם קידומת מדינה, למשל +972501234567): ").strip()
    password = input("סיסמת 2FA (אם אין — השאר ריק ולחץ Enter): ").strip() or None

    async def _do_auth():
        client = TelegramClient(
            config.TELETHON_SESSION,
            config.TELETHON_API_ID,
            config.TELETHON_API_HASH,
        )
        await client.start(phone=phone, password=password)
        me = await client.get_me()
        logger.info(
            "Session created successfully for: %s (id=%s)",
            getattr(me, "username", getattr(me, "first_name", "?")),
            getattr(me, "id", "?"),
        )
        await client.disconnect()

    asyncio.run(_do_auth())
    print("\nSession setup complete. You can now run: python main.py")


if __name__ == "__main__":
    main()
