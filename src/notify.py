"""Sends short status / error messages to the configured Telegram channel.

Used by the pipeline to make the channel itself a debug feed - if
something fails inside the run (Anthropic error, render error, no fresh
items) the user sees it without having to open GitHub Actions logs.
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Coroutine
from typing import Any

log = logging.getLogger(__name__)


async def _send_message(
    token: str,
    chat: str,
    text: str,
    *,
    label: str,
    silent: bool,
) -> bool:
    if not token or not chat:
        return False
    from telegram import Bot

    bot = Bot(token=token)
    try:
        await bot.send_message(
            chat_id=chat,
            text=text[:3900],
            disable_notification=silent,
            disable_web_page_preview=True,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to push status through %s bot: %s", label, exc)
        return False
    return True


async def _send(text: str) -> bool:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat = (os.getenv("TELEGRAM_CHANNEL_ID") or "").strip()
    return await _send_message(
        token,
        chat,
        text,
        label="telegram",
        silent=True,
    )


def _run(coroutine: Coroutine[Any, Any, bool]) -> bool:
    try:
        return asyncio.run(coroutine)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coroutine)
        finally:
            loop.close()


def _urgent_targets() -> list[tuple[str, str, str]]:
    """Return configured urgent targets in priority order, without duplicates."""
    notify_chat = (
        os.getenv("LCBAND_NOTIFY_CHAT_ID")
        or os.getenv("TELEGRAM_CHANNEL_ID")
        or ""
    ).strip()
    urgent_chat = (
        os.getenv("LCBAND_URGENT_CHAT_ID")
        or os.getenv("ESCALATION_BOT_CHAT_ID")
        or notify_chat
    ).strip()
    escalation_chat = (
        os.getenv("ESCALATION_BOT_CHAT_ID")
        or os.getenv("LCBAND_URGENT_CHAT_ID")
        or notify_chat
    ).strip()
    candidates = [
        (
            "urgent",
            (os.getenv("LCBAND_URGENT_BOT_TOKEN") or "").strip(),
            urgent_chat,
        ),
        (
            "escalation",
            (os.getenv("ESCALATION_BOT_TOKEN") or "").strip(),
            escalation_chat,
        ),
        (
            "notify",
            (os.getenv("LCBAND_NOTIFY_BOT_TOKEN") or "").strip(),
            notify_chat,
        ),
        (
            "telegram",
            (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip(),
            (os.getenv("TELEGRAM_CHANNEL_ID") or "").strip(),
        ),
    ]
    targets: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for label, token, chat in candidates:
        identity = (token, chat)
        if not token or not chat or identity in seen:
            continue
        seen.add(identity)
        targets.append((label, token, chat))
    return targets


def notify(text: str) -> None:
    """Fire-and-forget plain-text status post. Safe to call from sync code."""
    _run(_send(text))


def notify_urgent(text: str) -> bool:
    """Send an audible urgent alert, falling back to the normal notify bot."""
    targets = _urgent_targets()
    if not targets:
        log.error("No urgent or notify Telegram bot target is configured")
        return False
    for label, token, chat in targets:
        if _run(
            _send_message(
                token,
                chat,
                text,
                label=label,
                silent=False,
            )
        ):
            return True
    return False


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
