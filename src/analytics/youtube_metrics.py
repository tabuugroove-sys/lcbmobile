"""Refresh YouTube reaction metrics for previously published Shorts."""
from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from ..config import settings
from ..storage import Store

log = logging.getLogger(__name__)

_ANALYTICS_SCOPES = {
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
}


def _int_stat(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _oauth_credentials() -> Credentials | None:
    token_file = Path(settings.youtube_token_file)
    if not token_file.exists():
        log.info("YouTube analytics skipped: no OAuth token file")
        return None

    creds = Credentials.from_authorized_user_file(str(token_file))
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_file.write_text(creds.to_json())
    if not creds.valid:
        log.info("YouTube analytics skipped: OAuth token is not valid")
        return None
    return creds


def _data_service(credentials: Credentials | None):
    if settings.youtube_api_key:
        return build(
            "youtube",
            "v3",
            developerKey=settings.youtube_api_key,
            cache_discovery=False,
        )
    if credentials is None:
        log.info("YouTube metrics skipped: no YOUTUBE_API_KEY or token file")
        return None
    return build("youtube", "v3", credentials=credentials, cache_discovery=False)


def _analytics_service(credentials: Credentials | None):
    if credentials is None:
        return None
    granted = set(credentials.scopes or [])
    if granted and not _ANALYTICS_SCOPES.issubset(granted):
        missing = ", ".join(sorted(_ANALYTICS_SCOPES - granted))
        log.warning(
            "YouTube subscriber analytics skipped: OAuth token lacks %s; "
            "re-run scripts.get_youtube_token",
            missing,
        )
        return None
    return build(
        "youtubeAnalytics",
        "v2",
        credentials=credentials,
        cache_discovery=False,
    )


def _posted_date(value: str) -> str:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except (TypeError, ValueError):
        return "2020-01-01"


def _analytics_rows(response: dict[str, Any]) -> list[dict[str, object]]:
    headers = [str(header.get("name") or "") for header in response.get("columnHeaders", [])]
    rows: list[dict[str, object]] = []
    for values in response.get("rows", []) or []:
        row = dict(zip(headers, values))
        video_id = str(row.get("video") or "")
        if not video_id:
            continue
        rows.append(
            {
                "video_id": video_id,
                "view_count": _int_stat(row.get("views")),
                "subscribers_gained": _int_stat(row.get("subscribersGained")),
            }
        )
    return rows


def _refresh_growth_metrics(
    store: Store,
    service: Any,
    targets: list[tuple[str, str, str]],
) -> int:
    by_video_id = {
        video_id: (fingerprint, posted_at)
        for fingerprint, video_id, posted_at in targets
    }
    video_ids = list(by_video_id)
    refreshed = 0
    for start in range(0, len(video_ids), 50):
        chunk = video_ids[start : start + 50]
        start_date = min(_posted_date(by_video_id[video_id][1]) for video_id in chunk)
        response = (
            service.reports()
            .query(
                ids="channel==MINE",
                startDate=start_date,
                endDate=date.today().isoformat(),
                metrics="views,subscribersGained",
                dimensions="video",
                filters=f"video=={','.join(chunk)}",
                maxResults=len(chunk),
            )
            .execute()
        )
        for row in _analytics_rows(response):
            video_id = str(row["video_id"])
            target = by_video_id.get(video_id)
            if target is None:
                continue
            store.record_youtube_growth_metrics(
                fingerprint=target[0],
                video_id=video_id,
                view_count=int(row["view_count"]),
                subscribers_gained=int(row["subscribers_gained"]),
            )
            refreshed += 1
    return refreshed


def _video_titles(service: Any, video_ids: list[str]) -> dict[str, str]:
    titles: dict[str, str] = {}
    if service is None:
        return titles
    for start in range(0, len(video_ids), 50):
        chunk = video_ids[start : start + 50]
        response = (
            service.videos()
            .list(part="snippet", id=",".join(chunk))
            .execute()
        )
        for video in response.get("items", []):
            video_id = str(video.get("id") or "")
            title = str((video.get("snippet") or {}).get("title") or "")
            if video_id and title:
                titles[video_id] = title
    return titles


def _refresh_channel_history(store: Store, analytics_service: Any, data_service: Any) -> int:
    response = (
        analytics_service.reports()
        .query(
            ids="channel==MINE",
            startDate="2020-01-01",
            endDate=date.today().isoformat(),
            metrics="views,subscribersGained",
            dimensions="video",
            sort="-views",
            maxResults=min(settings.analytics_history_limit, 200),
        )
        .execute()
    )
    rows = _analytics_rows(response)
    titles = _video_titles(
        data_service,
        [str(row["video_id"]) for row in rows],
    )
    for row in rows:
        video_id = str(row["video_id"])
        store.record_youtube_growth_metrics(
            fingerprint=f"youtube:{video_id}",
            video_id=video_id,
            view_count=int(row["view_count"]),
            subscribers_gained=int(row["subscribers_gained"]),
            title=titles.get(video_id),
        )
    return len(rows)


def refresh_youtube_metrics(store: Store) -> None:
    if not settings.analytics_enabled:
        return

    targets = store.youtube_metric_targets(
        stale_after_hours=settings.youtube_metrics_refresh_hours,
        limit=50,
    )
    try:
        credentials = _oauth_credentials()
        service = _data_service(credentials)

        by_video_id = {
            video_id: fingerprint for fingerprint, video_id, _ in targets
        }
        video_ids = list(by_video_id)
        if service is not None and video_ids:
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
            log.info("Refreshed public YouTube metrics for %d video(s)", len(video_ids))

        analytics_service = _analytics_service(credentials)
        if analytics_service is not None:
            if targets:
                refreshed = _refresh_growth_metrics(store, analytics_service, targets)
                log.info(
                    "Refreshed YouTube views/subscriber growth for %d video(s)",
                    refreshed,
                )
            history_count = _refresh_channel_history(
                store,
                analytics_service,
                service,
            )
            log.info(
                "Refreshed channel-wide growth history for %d video(s)",
                history_count,
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("YouTube metrics refresh failed: %s", exc)
