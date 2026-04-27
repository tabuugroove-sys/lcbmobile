"""TikTok Content Posting API uploader (chunked upload + publish)."""
from __future__ import annotations

import logging
import os
from pathlib import Path

import httpx

from ..config import settings
from ..models import GeneratedAssets, RewrittenPost
from .base import PublishResult

log = logging.getLogger(__name__)
API = "https://open.tiktokapis.com/v2"


class TikTokPublisher:
    name = "tiktok"

    def is_configured(self) -> bool:
        return bool(settings.tiktok_access_token and settings.tiktok_open_id)

    def publish(self, post: RewrittenPost, assets: GeneratedAssets) -> PublishResult:
        try:
            video_path = Path(assets.video_path)
            video_size = video_path.stat().st_size
            chunk_size = min(video_size, 10 * 1024 * 1024)
            total_chunks = max(1, (video_size + chunk_size - 1) // chunk_size)

            headers = {
                "Authorization": f"Bearer {settings.tiktok_access_token}",
                "Content-Type": "application/json",
            }
            title = f"{post.headline} {' '.join('#' + h for h in post.hashtags[:5])}"[:150]

            with httpx.Client(timeout=120.0) as client:
                init = client.post(
                    f"{API}/post/publish/video/init/",
                    headers=headers,
                    json={
                        "post_info": {
                            "title": title,
                            "privacy_level": "PUBLIC_TO_EVERYONE",
                            "disable_duet": False,
                            "disable_comment": False,
                            "disable_stitch": False,
                        },
                        "source_info": {
                            "source": "FILE_UPLOAD",
                            "video_size": video_size,
                            "chunk_size": chunk_size,
                            "total_chunk_count": total_chunks,
                        },
                    },
                )
                init.raise_for_status()
                data = init.json()["data"]
                publish_id = data["publish_id"]
                upload_url = data["upload_url"]

                with video_path.open("rb") as fh:
                    for i in range(total_chunks):
                        start = i * chunk_size
                        end = min(start + chunk_size, video_size) - 1
                        fh.seek(start)
                        chunk = fh.read(end - start + 1)
                        put = client.put(
                            upload_url,
                            content=chunk,
                            headers={
                                "Content-Range": f"bytes {start}-{end}/{video_size}",
                                "Content-Type": "video/mp4",
                                "Content-Length": str(len(chunk)),
                            },
                        )
                        put.raise_for_status()
            return PublishResult(platform=self.name, ok=True, remote_id=publish_id)
        except httpx.HTTPError as exc:
            return PublishResult(platform=self.name, ok=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            log.exception("TikTok publish failed")
            return PublishResult(platform=self.name, ok=False, error=str(exc))
