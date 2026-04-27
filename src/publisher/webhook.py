"""Webhook publisher.

Why this exists: YouTube/IG/TikTok native APIs all require
either a desktop OAuth flow or platform approval that takes days. This
publisher offloads the actual upload to a SaaS automation tool (Make.com,
Zapier, n8n, ...) which is already approved by the platforms. The user
authenticates that SaaS once via OAuth in their mobile browser; from there
on we just POST a payload and the SaaS uploads.

Flow:
  1. Upload the rendered .mp4 (and thumbnail) as assets on a GitHub Release
     in the SAME repo. GITHUB_TOKEN is provided automatically by Actions,
     so no extra secrets are needed if the repo is public.
  2. POST a JSON payload to WEBHOOK_URL with the public asset URLs +
     title/description/hashtags. Make.com / Zapier scenarios then upload
     to YouTube, Instagram, TikTok using their pre-approved connectors.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import httpx

from ..config import settings
from ..models import GeneratedAssets, RewrittenPost
from .base import PublishResult

log = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _release_tag(post: RewrittenPost) -> str:
    safe = "".join(c for c in post.headline if c.isalnum())[:24].lower() or "post"
    return f"auto-{int(time.time())}-{safe}"


def _create_release(
    client: httpx.Client, repo: str, token: str, tag: str, body: str
) -> dict:
    resp = client.post(
        f"{GITHUB_API}/repos/{repo}/releases",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={
            "tag_name": tag,
            "name": tag,
            "body": body[:1000],
            "draft": False,
            "prerelease": False,
        },
    )
    resp.raise_for_status()
    return resp.json()


def _upload_asset(
    client: httpx.Client, upload_url: str, token: str, path: Path, content_type: str
) -> dict:
    # upload_url comes back with "{?name,label}" template suffix.
    base = upload_url.split("{", 1)[0]
    with path.open("rb") as fh:
        data = fh.read()
    resp = client.post(
        base,
        params={"name": path.name},
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": content_type,
        },
        content=data,
        timeout=httpx.Timeout(180.0),
    )
    resp.raise_for_status()
    return resp.json()


class WebhookPublisher:
    name = "webhook"

    def is_configured(self) -> bool:
        return bool(_env("WEBHOOK_URL"))

    def publish(self, post: RewrittenPost, assets: GeneratedAssets) -> PublishResult:
        webhook_url = _env("WEBHOOK_URL")
        repo = _env("GITHUB_REPOSITORY") or _env("WEBHOOK_RELEASE_REPO")
        token = _env("GITHUB_TOKEN") or _env("WEBHOOK_GITHUB_TOKEN")
        auth_header = _env("WEBHOOK_AUTH_HEADER")
        targets = [
            t.strip()
            for t in _env("WEBHOOK_TARGETS", "youtube,instagram,tiktok").split(",")
            if t.strip()
        ]

        if not repo or not token:
            return PublishResult(
                platform=self.name,
                ok=False,
                error="GITHUB_REPOSITORY and GITHUB_TOKEN are required to upload assets.",
            )

        try:
            with httpx.Client(timeout=60.0) as client:
                tag = _release_tag(post)
                release = _create_release(
                    client, repo, token, tag, post.long_caption[:900]
                )
                upload_url = release["upload_url"]

                video_asset = _upload_asset(
                    client,
                    upload_url,
                    token,
                    Path(assets.video_path),
                    "video/mp4",
                )
                thumb_url = None
                if assets.thumbnail_path:
                    thumb_asset = _upload_asset(
                        client,
                        upload_url,
                        token,
                        Path(assets.thumbnail_path),
                        "image/jpeg",
                    )
                    thumb_url = thumb_asset.get("browser_download_url")

                payload = {
                    "title": post.headline,
                    "short_caption": post.short_caption,
                    "long_caption": post.long_caption,
                    "hashtags": post.hashtags,
                    "category": post.category,
                    "language": settings.content_lang,
                    "source_url": post.source_url,
                    "video_url": video_asset.get("browser_download_url"),
                    "thumbnail_url": thumb_url,
                    "duration_seconds": assets.duration_seconds,
                    "release_tag": tag,
                    "targets": targets,
                }

                headers = {"Content-Type": "application/json"}
                if auth_header:
                    headers["Authorization"] = auth_header

                hook_resp = client.post(
                    webhook_url,
                    headers=headers,
                    content=json.dumps(payload),
                    timeout=httpx.Timeout(60.0),
                )
                hook_resp.raise_for_status()

            return PublishResult(
                platform=self.name,
                ok=True,
                remote_id=tag,
                url=video_asset.get("browser_download_url"),
            )
        except httpx.HTTPError as exc:
            return PublishResult(platform=self.name, ok=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            log.exception("Webhook publish failed")
            return PublishResult(platform=self.name, ok=False, error=str(exc))
