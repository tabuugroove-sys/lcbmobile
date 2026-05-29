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


async def _send(text: str) -> None:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat = (os.getenv("TELEGRAM_CHANNEL_ID") or "").strip()
    if not token or not chat:
        return
    from telegram import Bot

    bot = Bot(token=token)
    try:
        await bot.send_message(
            chat_id=chat,
            text=text[:3900],
            disable_notification=True,
            disable_web_page_preview=True,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to push status to Telegram: %s", exc)


def notify(text: str) -> None:
    """Fire-and-forget plain-text status post. Safe to call from sync code."""
    try:
        asyncio.run(_send(text))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_send(text))
        finally:
            loop.close()


def notify_error(stage: str, exc: BaseException, *, context: str = "") -> None:
    import traceback

    head = "".join(traceback.format_exception_only(type(exc), exc)).strip()
    tail = traceback.format_exc()
    # Keep the bottom of the traceback (the actual failure site) and clip the rest.
    if len(tail) > 1500:
        tail = "...\n" + tail[-1500:]
    parts = [f"❌ {stage}", head]
    if context:
        parts.append(f"context: {context}")
    parts.append("")
    parts.append(tail)
    notify("\n".join(parts))


def notify_summary(report) -> None:  # noqa: ANN001
    lines = [
        "📊 LCB run finished",
        f"fetched: {report.fetched}",
        f"new: {report.new}",
        f"processed: {report.processed}",
    ]
    for r in report.publish_results:
        marker = "OK" if r.ok else "FAIL"
        info = r.remote_id or r.error or ""
        lines.append(f"[{marker}] {r.platform}: {info[:200]}")
    notify("\n".join(lines))
