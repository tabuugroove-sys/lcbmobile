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

# Telegram caption limit is 1024 chars; we keep a small margin.
_MAX_CAPTION = 1020


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

    @staticmethod
    def _build_caption(post: RewrittenPost) -> str:
        """Build an HTML caption that never exceeds _MAX_CAPTION.

        Strategy: the headline, source link and hashtags have a fixed size,
        so we truncate only *long_caption* (the variable-length part) to fit
        inside the limit.  This way we never slice through an HTML tag.
        """
        esc = html_mod.escape
        headline_part = f"<b>{esc(post.headline)}</b>\n\n"
        source_part = f'\n\n<a href="{esc(post.source_url)}">Fonte</a>\n\n'
        hashtags_part = " ".join(f"#{esc(tag)}" for tag in post.hashtags)

        # Budget left for the long_caption text (escaped, no HTML tags around it)
        fixed_len = len(headline_part) + len(source_part) + len(hashtags_part)
        budget = _MAX_CAPTION - fixed_len

        body = esc(post.long_caption)
        if len(body) > budget:
            body = body[: max(budget - 1, 0)] + "\u2026"

        return headline_part + body + source_part + hashtags_part

    async def _publish_async(
        self, post: RewrittenPost, assets: GeneratedAssets
    ) -> PublishResult:
        bot = Bot(token=settings.telegram_bot_token)
        caption = self._build_caption(post)

        with open(assets.video_path, "rb") as fh:
            msg = await bot.send_video(
                chat_id=settings.telegram_channel_id,
                video=fh,
                caption=caption,
                parse_mode=ParseMode.HTML,
                supports_streaming=True,
            )

        return PublishResult(platform=self.name, ok=True, remote_id=str(msg.message_id))
