"""Sends short status / error messages to the configured Telegram channel.

Used by the pipeline to make the channel itself a debug feed - if
something fails inside the run (Anthropic error, render error, no fresh
items) the user sees it without having to open GitHub Actions logs.
"""
from __future__ import annotations

import asyncio
import logging
import os

log = logging.getLogger(__name__)


def _escape_md(text: str) -> str:
    for ch in r"_*[]()~`>#+-=|{}.!\\":
        text = text.replace(ch, f"\\{ch}")
    return text


async def _send(text: str) -> None:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat = (os.getenv("TELEGRAM_CHANNEL_ID") or "").strip()
    if not token or not chat:
        return
    from telegram import Bot
    from telegram.constants import ParseMode

    bot = Bot(token=token)
    try:
        await bot.send_message(
            chat_id=chat,
            text=text[:3900],
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_notification=True,
        )
    except Exception:  # noqa: BLE001
        # Last-ditch retry without markdown in case escaping fails.
        try:
            await bot.send_message(chat_id=chat, text=text[:3900], disable_notification=True)
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to push status to Telegram: %s", exc)


def notify(text: str) -> None:
    """Fire-and-forget status post. Safe to call from sync code."""
    try:
        asyncio.run(_send(text))
    except RuntimeError:
        # Already inside an event loop (rare in this pipeline).
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_send(text))
        finally:
            loop.close()


def notify_error(stage: str, exc: BaseException, *, context: str = "") -> None:
    import traceback

    tb = "".join(traceback.format_exception_only(type(exc), exc)).strip()
    deep = traceback.format_exc()[-1200:]
    body = (
        f"❌ *{_escape_md(stage)}*\n"
        f"`{_escape_md(tb)}`\n"
    )
    if context:
        body += f"\n_{_escape_md(context)}_\n"
    body += f"\n```\n{_escape_md(deep)}\n```"
    notify(body)


def notify_summary(report) -> None:  # noqa: ANN001
    lines = [
        "📊 *LCB run finished*",
        f"fetched: `{report.fetched}`",
        f"new: `{report.new}`",
        f"processed: `{report.processed}`",
    ]
    for r in report.publish_results:
        marker = "✅" if r.ok else "⚠️"
        info = r.remote_id or r.error or ""
        lines.append(f"{marker} {_escape_md(r.platform)}: {_escape_md(info[:200])}")
    notify("\n".join(lines))
