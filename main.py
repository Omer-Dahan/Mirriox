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
import signal
import sys

from app.network_errors import is_network_error

_PID_FILE = "mirriox.pid"


def _kill_old_process() -> None:
    """Terminate any previously running Mirriox process recorded in the PID file."""
    logger = logging.getLogger(__name__)
    if not os.path.exists(_PID_FILE):
        return
    try:
        with open(_PID_FILE) as f:
            old_pid = int(f.read().strip())
    except (ValueError, OSError):
        return

    if old_pid == os.getpid():
        return  # shouldn't happen, but guard against self-kill

    try:
        os.kill(old_pid, 0)  # check if process is alive
    except OSError:
        return  # already gone

    try:
        if sys.platform == "win32":
            import subprocess
            subprocess.call(
                ["taskkill", "/F", "/PID", str(old_pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            os.kill(old_pid, signal.SIGTERM)
        logger.info("Terminated old process (PID %d)", old_pid)
    except OSError as e:
        logger.warning("Could not terminate old process %d: %s", old_pid, e)


def _write_pid() -> None:
    with open(_PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def _remove_pid() -> None:
    try:
        os.remove(_PID_FILE)
    except OSError:
        pass


class _CollapseNetworkErrors(logging.Filter):
    """
    Replace multi-line tracebacks for transient network errors with a single
    WARNING line. Keeps the log clean without hiding real problems.
    """
    _NETWORK_EXC_NAMES = frozenset({
        "NetworkError", "ConnectError", "ReadError",
        "RemoteProtocolError", "ConnectionError", "ConnectionResetError",
        "TimeoutError",
    })
    NOISY_LOGGERS = frozenset({
        "telegram.ext.Updater",
        "telegram.ext.Application",
        "asyncio",
    })

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        if record.name not in self.NOISY_LOGGERS:
            return True
        if not record.exc_info:
            return True
        exc_type = record.exc_info[0]
        if exc_type is None:
            return True
        # Walk the MRO to catch subclasses (e.g. telegram.error.NetworkError)
        names = {cls.__name__ for cls in exc_type.__mro__}
        if names & self._NETWORK_EXC_NAMES:
            record.levelno = logging.WARNING
            record.levelname = "WARNING"
            record.exc_info = None
            record.exc_text = None
            # Shorten the message to one line
            record.msg = "ניתוק רשת זמני (%s) — ממשיך לנסות..."
            record.args = (exc_type.__name__,)
        return True


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("telethon").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)

    # Collapse noisy network-error tracebacks to single WARNING lines
    _f = _CollapseNetworkErrors()
    for name in _CollapseNetworkErrors.NOISY_LOGGERS:
        logging.getLogger(name).addFilter(_f)


def main() -> None:
    _setup_logging()
    logger = logging.getLogger(__name__)

    _kill_old_process()
    _write_pid()
    try:
        _run_main(logger)
    finally:
        _remove_pid()


def _run_main(logger: logging.Logger) -> None:
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
    from app import db

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



async def _run_with_restart(name: str, coro_fn, config) -> None:
    """Wrap a long-running coroutine with automatic restart on network errors.

    Always retries after a fixed 5s delay so recovery is quick after the
    network comes back (no exponential backoff that grows to minutes).
    """
    _logger = logging.getLogger(__name__)
    _RETRY_DELAY_S = 5
    while True:
        try:
            await coro_fn(config)
            return  # clean exit
        except Exception as exc:
            if is_network_error(exc):
                _logger.warning(
                    "[%s] ניתוק רשת (%s) — מנסה שוב בעוד %ds...",
                    name, exc, _RETRY_DELAY_S,
                )
                await asyncio.sleep(_RETRY_DELAY_S)
            else:
                _logger.exception("[%s] שגיאה קריטית — מפסיק: %s", name, exc)
                raise


def _asyncio_exception_handler(loop: asyncio.AbstractEventLoop, context: dict) -> None:
    """
    Suppress the known Windows asyncio bug where a socket is already invalid
    when asyncio tries to shut it down (WinError 10022).
    All other exceptions go through the default handler.
    """
    exc = context.get("exception")
    if isinstance(exc, OSError) and getattr(exc, "winerror", None) == 10022:
        return  # harmless Windows socket-cleanup race — ignore
    loop.default_exception_handler(context)


async def _run_all(config) -> None:
    """Run bot and worker concurrently, with auto-restart on network errors."""
    asyncio.get_running_loop().set_exception_handler(_asyncio_exception_handler)

    from app.bot.bot_main import run_async as bot_run_async
    from app.worker.worker_main import run_async as worker_run_async

    worker_task = asyncio.create_task(
        _run_with_restart("worker", worker_run_async, config), name="worker"
    )
    bot_task = asyncio.create_task(
        _run_with_restart("bot", bot_run_async, config), name="bot"
    )

    try:
        done, _ = await asyncio.wait(
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
