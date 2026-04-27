"""Instagram Reels publisher (Graph API for IG Business accounts).

Instagram requires a publicly accessible URL for the video file. Configure
INSTAGRAM_PUBLIC_BASE_URL to point at a directory that mirrors OUTPUT_DIR
(e.g., a CDN or static-hosting bucket). The publisher uploads nothing to that
host on its own.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from urllib.parse import quote

import httpx

from ..config import settings
from ..models import GeneratedAssets, RewrittenPost
from .base import PublishResult

log = logging.getLogger(__name__)
GRAPH = "https://graph.facebook.com/v19.0"


class InstagramPublisher:
    name = "instagram"

    def is_configured(self) -> bool:
        return all(
            [
                settings.instagram_user_id,
                settings.instagram_access_token,
                settings.instagram_public_base_url,
            ]
        )

    def _public_url(self, video_path: str) -> str:
        rel = Path(video_path).relative_to(settings.output_dir)
        base = settings.instagram_public_base_url.rstrip("/")
        return f"{base}/{quote(str(rel))}"

    def publish(self, post: RewrittenPost, assets: GeneratedAssets) -> PublishResult:
        try:
            video_url = self._public_url(assets.video_path)
            caption = (
                f"{post.headline}\n\n{post.short_caption}\n\n"
                + " ".join(f"#{tag}" for tag in post.hashtags)
            )[:2200]
            with httpx.Client(timeout=60.0) as client:
                create = client.post(
                    f"{GRAPH}/{settings.instagram_user_id}/media",
                    data={
                        "media_type": "REELS",
                        "video_url": video_url,
                        "caption": caption,
                        "share_to_feed": "true",
                        "access_token": settings.instagram_access_token,
                    },
                )
                create.raise_for_status()
                container_id = create.json()["id"]

                # Poll until the container is FINISHED (Reels need transcoding).
                for _ in range(30):
                    status = client.get(
                        f"{GRAPH}/{container_id}",
                        params={
                            "fields": "status_code",
                            "access_token": settings.instagram_access_token,
                        },
                    ).json()
                    if status.get("status_code") == "FINISHED":
                        break
                    if status.get("status_code") == "ERROR":
                        return PublishResult(
                            platform=self.name, ok=False, error=str(status)
                        )
                    time.sleep(5)

                publish = client.post(
                    f"{GRAPH}/{settings.instagram_user_id}/media_publish",
                    data={
                        "creation_id": container_id,
                        "access_token": settings.instagram_access_token,
                    },
                )
                publish.raise_for_status()
                media_id = publish.json()["id"]
            return PublishResult(platform=self.name, ok=True, remote_id=media_id)
        except httpx.HTTPError as exc:
            return PublishResult(platform=self.name, ok=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            log.exception("Instagram publish failed")
            return PublishResult(platform=self.name, ok=False, error=str(exc))
