"""Telegram publisher: posts the Short as a video to a channel."""
from __future__ import annotations

import asyncio
import html as html_mod
import logging

from telegram import Bot
from telegram.constants import ParseMode

from ..config import settings
from ..models import GeneratedAssets, RewrittenPost
from .base import PublishResult

log = logging.getLogger(__name__)


class TelegramPublisher:
    name = "telegram"

    def is_configured(self) -> bool:
        return bool(settings.telegram_bot_token and settings.telegram_channel_id)

    def publish(self, post: RewrittenPost, assets: GeneratedAssets) -> PublishResult:
        try:
            return asyncio.run(self._publish_async(post, assets))
        except Exception as exc:  # noqa: BLE001
            log.exception("Telegram publish failed")
            return PublishResult(platform=self.name, ok=False, error=str(exc))

    async def _publish_async(
        self, post: RewrittenPost, assets: GeneratedAssets
    ) -> PublishResult:
        bot = Bot(token=settings.telegram_bot_token)
        esc = html_mod.escape
        caption = (
            f"<b>{esc(post.headline)}</b>\n\n"
            f"{esc(post.long_caption)}\n\n"
            f'<a href="{esc(post.source_url)}">Fonte</a>\n\n'
            + " ".join(f"#{esc(tag)}" for tag in post.hashtags)
        )[:1020]
        with open(assets.video_path, "rb") as fh:
            msg = await bot.send_video(
                chat_id=settings.telegram_channel_id,
                video=fh,
                caption=caption,
                parse_mode=ParseMode.HTML,
                supports_streaming=True,
            )
        return PublishResult(platform=self.name, ok=True, remote_id=str(msg.message_id))
