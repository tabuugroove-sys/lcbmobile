"""Healthcheck: verify the bot token + channel and post a test ping.

Run from the workflow before the pipeline so you see a clear error if the
token is missing, the bot is not an admin, or the channel id is wrong.

Usage:  python -m scripts.check_telegram
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime


async def main() -> int:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
    if not token or not chat:
        print(
            "[telegram] missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHANNEL_ID secret.",
            file=sys.stderr,
        )
        return 2

    from telegram import Bot
    from telegram.error import TelegramError

    bot = Bot(token=token)
    try:
        me = await bot.get_me()
        chat_info = await bot.get_chat(chat)
        msg = await bot.send_message(
            chat_id=chat,
            text=(
                "✅ LCB Mobile pipeline conectado.\n"
                f"Bot: @{me.username} → canal: {chat_info.title}\n"
                f"UTC: {datetime.utcnow().isoformat(timespec='seconds')}Z"
            ),
            disable_notification=True,
        )
        print(
            f"[telegram] ok: bot=@{me.username} chat='{chat_info.title}' "
            f"message_id={msg.message_id}"
        )
        return 0
    except TelegramError as exc:
        print(f"[telegram] FAILED: {exc}", file=sys.stderr)
        print(
            "Tip: make sure the bot is added as ADMIN of the channel and "
            "TELEGRAM_CHANNEL_ID is either '@your_channel' or a numeric -100... id.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
