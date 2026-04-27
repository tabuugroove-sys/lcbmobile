"""Builds the list of active publishers based on environment configuration."""
from __future__ import annotations

import logging

from .base import Publisher
from .instagram import InstagramPublisher
from .telegram import TelegramPublisher
from .tiktok import TikTokPublisher
from .twitter import TwitterPublisher
from .youtube import YouTubePublisher

log = logging.getLogger(__name__)

ALL_PUBLISHERS: list[Publisher] = [
    YouTubePublisher(),
    InstagramPublisher(),
    TikTokPublisher(),
    TwitterPublisher(),
    TelegramPublisher(),
]


def build_publishers(only: list[str] | None = None) -> list[Publisher]:
    """Return configured publishers, optionally filtered by name."""
    chosen: list[Publisher] = []
    for pub in ALL_PUBLISHERS:
        if only and pub.name not in only:
            continue
        if not pub.is_configured():
            log.info("Publisher %s skipped (not configured)", pub.name)
            continue
        chosen.append(pub)
    return chosen
