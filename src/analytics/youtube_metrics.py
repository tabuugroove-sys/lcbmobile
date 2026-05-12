"""Refresh YouTube reaction metrics for previously published Shorts."""
from __future__ import annotations

import logging
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from ..config import settings
from ..storage import Store

log = logging.getLogger(__name__)


def _int_stat(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _service():
    if settings.youtube_api_key:
        return build(
            "youtube",
            "v3",
            developerKey=settings.youtube_api_key,
            cache_discovery=False,
        )

    token_file = Path(settings.youtube_token_file)
    if not token_file.exists():
        log.info("YouTube metrics skipped: no YOUTUBE_API_KEY or token file")
        return None

    creds = Credentials.from_authorized_user_file(str(token_file))
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_file.write_text(creds.to_json())
    if not creds.valid:
        log.info("YouTube metrics skipped: OAuth token is not valid")
        return None
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def refresh_youtube_metrics(store: Store) -> None:
    if not settings.analytics_enabled:
        return

    targets = store.youtube_metric_targets(
        stale_after_hours=settings.youtube_metrics_refresh_hours,
        limit=50,
    )
    if not targets:
        return

    try:
        service = _service()
        if service is None:
            return

        by_video_id = {video_id: fingerprint for fingerprint, video_id in targets}
        video_ids = list(by_video_id)
        for start in range(0, len(video_ids), 50):
            chunk = video_ids[start : start + 50]
            response = (
                service.videos()
                .list(part="statistics", id=",".join(chunk))
                .execute()
            )
            for video in response.get("items", []):
                video_id = video.get("id")
                if not video_id:
                    continue
                stats = video.get("statistics", {})
                store.record_youtube_metrics(
                    fingerprint=by_video_id[video_id],
                    video_id=video_id,
                    view_count=_int_stat(stats.get("viewCount")),
                    like_count=_int_stat(stats.get("likeCount")),
                    comment_count=_int_stat(stats.get("commentCount")),
                )
        log.info("Refreshed YouTube metrics for %d video(s)", len(video_ids))
    except Exception as exc:  # noqa: BLE001
        log.warning("YouTube metrics refresh failed: %s", exc)
