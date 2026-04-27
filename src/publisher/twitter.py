"""X / Twitter publisher: chunked media upload (v1.1) + create tweet (v2)."""
from __future__ import annotations

import logging

import tweepy

from ..config import settings
from ..models import GeneratedAssets, RewrittenPost
from .base import PublishResult

log = logging.getLogger(__name__)


class TwitterPublisher:
    name = "twitter"

    def is_configured(self) -> bool:
        return all(
            [
                settings.twitter_consumer_key,
                settings.twitter_consumer_secret,
                settings.twitter_access_token,
                settings.twitter_access_secret,
            ]
        )

    def publish(self, post: RewrittenPost, assets: GeneratedAssets) -> PublishResult:
        try:
            auth = tweepy.OAuth1UserHandler(
                settings.twitter_consumer_key,
                settings.twitter_consumer_secret,
                settings.twitter_access_token,
                settings.twitter_access_secret,
            )
            api_v1 = tweepy.API(auth, wait_on_rate_limit=True)
            media = api_v1.media_upload(
                filename=assets.video_path,
                media_category="tweet_video",
                chunked=True,
            )

            client = tweepy.Client(
                consumer_key=settings.twitter_consumer_key,
                consumer_secret=settings.twitter_consumer_secret,
                access_token=settings.twitter_access_token,
                access_token_secret=settings.twitter_access_secret,
                bearer_token=settings.twitter_bearer_token or None,
            )
            text = post.short_caption[:270]
            response = client.create_tweet(text=text, media_ids=[media.media_id_string])
            tweet_id = str(response.data["id"])
            return PublishResult(
                platform=self.name,
                ok=True,
                remote_id=tweet_id,
                url=f"https://x.com/i/status/{tweet_id}",
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("Twitter publish failed")
            return PublishResult(platform=self.name, ok=False, error=str(exc))
