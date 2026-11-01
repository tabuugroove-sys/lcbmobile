"""Refresh YouTube reaction metrics for previously published Shorts."""
from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo
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
    if credentials is not None:
        return build("youtube", "v3", credentials=credentials, cache_discovery=False)
    if settings.youtube_api_key:
        return build(
            "youtube",
            "v3",
            developerKey=settings.youtube_api_key,
            cache_discovery=False,
        )
    log.info("YouTube metrics skipped: no YOUTUBE_API_KEY or token file")
    return None


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


def _video_metadata(service: Any, video_ids: list[str]) -> dict[str, dict]:
    metadata: dict[str, dict] = {}
    if service is None:
        return metadata
    for start in range(0, len(video_ids), 50):
        chunk = video_ids[start : start + 50]
        response = (
            service.videos()
            .list(part="snippet,contentDetails", id=",".join(chunk))
            .execute()
        )
        for video in response.get("items", []):
            video_id = str(video.get("id") or "")
            title = str((video.get("snippet") or {}).get("title") or "")
            if video_id and title:
                raw = str((video.get("contentDetails") or {}).get("duration") or "")
                match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", raw)
                seconds = sum(int(v or 0) * multiplier for v, multiplier in zip(match.groups(), (3600, 60, 1))) if match else 0
                kind = "long" if seconds > 180 or "radar musical" in title.lower() else "short" if "#shorts" in title.lower() else None
                snippet = video.get('snippet') or {}
                thumbnails = snippet.get('thumbnails') or {}
                thumbnail = thumbnails.get('high') or thumbnails.get('medium') or thumbnails.get('default') or {}
                metadata[video_id] = {"title": title, "content_format": kind,
                    'published_at': snippet.get('publishedAt'), 'duration_seconds': seconds,
                    'thumbnail_url': thumbnail.get('url')}
    return metadata


def _refresh_channel_history(store: Store, analytics_service: Any, data_service: Any) -> int:
    # Enumerate all uploads: top-200 alone excludes the control population.
    if data_service is None:
        raise RuntimeError('Channel history requires authenticated YouTube Data API')
    channels = data_service.channels().list(part='id,contentDetails', mine=True).execute().get('items', [])
    expected = os.getenv('YOUTUBE_EXPECTED_CHANNEL_ID', 'UC-TFUUc4YHleNoIFXBVaj7A')
    if len(channels) != 1 or channels[0]['id'] != expected:
        raise RuntimeError('Analytics OAuth belongs to a different channel')
    playlist = channels[0]['contentDetails']['relatedPlaylists']['uploads']
    ids, tokens, token = [], set(), None
    while True:
        args = dict(part='contentDetails', playlistId=playlist, maxResults=50)
        if token:
            args['pageToken'] = token
        response = data_service.playlistItems().list(**args).execute()
        ids.extend(r['contentDetails']['videoId'] for r in response.get('items', []))
        token = response.get('nextPageToken')
        if not token:
            break
        if token in tokens:
            raise RuntimeError('Repeated uploads pagination token')
        tokens.add(token)
    ids = list(dict.fromkeys(ids))
    rows = []
    end = datetime.now(ZoneInfo('America/Sao_Paulo')).date().isoformat()
    for start in range(0, len(ids), 50):
        chunk = ids[start:start+50]
        response = analytics_service.reports().query(
            ids='channel==MINE', startDate='2005-01-01', endDate=end,
            metrics='views,subscribersGained', dimensions='video',
            filters='video=='+','.join(chunk), maxResults=50,
        ).execute()
        rows.extend(row for row in _analytics_rows(response) if row['video_id'] in chunk)
    metadata = _video_metadata(data_service, ids)
    for row in rows:
        video_id = str(row["video_id"])
        store.record_youtube_growth_metrics(
            fingerprint=f"youtube:{video_id}",
            video_id=video_id,
            view_count=int(row["view_count"]),
            subscribers_gained=int(row["subscribers_gained"]),
            title=metadata.get(video_id, {}).get("title"),
            content_format=metadata.get(video_id, {}).get("content_format"),
        )
        if video_id in metadata:
            store.record_youtube_context(video_id, metadata[video_id])
    from .winner_insights import write_insights
    write_insights(store, settings.output_dir)
    store.mark_analytics_refreshed('channel_history_v2')
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
            if store.analytics_refresh_due('channel_history_v2', settings.youtube_metrics_refresh_hours):
                history_count = _refresh_channel_history(store, analytics_service, service)
                log.info("Refreshed channel-wide growth history for %d video(s)", history_count)
    except Exception as exc:  # noqa: BLE001
        log.warning("YouTube metrics refresh failed: %s", exc)
