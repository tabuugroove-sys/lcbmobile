"""Instagram Reels publisher (Graph API for IG Business accounts).

Instagram requires a publicly accessible URL for the video file. Prefer
INSTAGRAM_PUBLIC_BASE_URL when a CDN/static bucket mirrors OUTPUT_DIR. In
GitHub Actions, the publisher can also create a GitHub Release asset and use
that public download URL, matching the webhook publisher's cloud-only flow.
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
from .webhook import _create_release, _env, _release_tag, _upload_asset

log = logging.getLogger(__name__)
GRAPH = "https://graph.facebook.com/v19.0"


class InstagramPublisher:
    name = "instagram"

    def is_configured(self) -> bool:
        if not settings.instagram_user_id or not settings.instagram_access_token:
            return False
        if settings.instagram_public_base_url:
            return True
        return bool(
            (_env("GITHUB_REPOSITORY") or _env("WEBHOOK_RELEASE_REPO"))
            and _env("GITHUB_TOKEN")
        )

    def _public_url(self, video_path: str) -> str:
        rel = Path(video_path).relative_to(settings.output_dir)
        base = settings.instagram_public_base_url.rstrip("/")
        return f"{base}/{quote(str(rel))}"

    def _release_url(
        self,
        client: httpx.Client,
        post: RewrittenPost,
        assets: GeneratedAssets,
    ) -> str:
        repo = _env("GITHUB_REPOSITORY") or _env("WEBHOOK_RELEASE_REPO")
        token = _env("GITHUB_TOKEN")
        if not repo or not token:
            raise RuntimeError(
                "INSTAGRAM_PUBLIC_BASE_URL or GITHUB_REPOSITORY/GITHUB_TOKEN is required."
            )
        tag = _release_tag(post)
        release = _create_release(client, repo, token, tag, post.long_caption[:900])
        video_asset = _upload_asset(
            client,
            release["upload_url"],
            token,
            Path(assets.video_path),
            "video/mp4",
        )
        url = video_asset.get("browser_download_url")
        if not url:
            raise RuntimeError("GitHub release asset did not return browser_download_url.")
        return str(url)

    def _video_url(
        self,
        client: httpx.Client,
        post: RewrittenPost,
        assets: GeneratedAssets,
    ) -> str:
        if settings.instagram_public_base_url:
            return self._public_url(assets.video_path)
        return self._release_url(client, post, assets)

    def publish(self, post: RewrittenPost, assets: GeneratedAssets) -> PublishResult:
        try:
            caption = (
                f"{post.headline}\n\n{post.short_caption}\n\n"
                + " ".join(f"#{tag}" for tag in post.hashtags)
            )[:2200]
            with httpx.Client(timeout=60.0) as client:
                video_url = self._video_url(client, post, assets)
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
