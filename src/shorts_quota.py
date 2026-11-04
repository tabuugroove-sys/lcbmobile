"""Today's Shorts count, read live from the channel.

The slot runners count before they start a render and the YouTube publisher counts
again right before upload. Both use these functions: if the two counts could differ,
a runner would render again and again for a slot the publisher keeps refusing.
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .models import _normalize_url

SOURCE_RE = re.compile(r"^Fonte:\s*(https?://\S+)", re.IGNORECASE | re.MULTILINE)
# How many Shorts the channel needs today once the runner's slot is filled.
TARGET_ENV = "YOUTUBE_SHORTS_TARGET"
# scripts.run_pipeline exits with this code when the slot was filled during the render.
SLOT_FILLED_EXIT_CODE = 4


def extract_source_url(description: str) -> str | None:
    match = SOURCE_RE.search(description or "")
    if not match:
        return None
    return match.group(1).rstrip(".,;)")


def recent_uploads(service) -> list[dict[str, str]]:
    channel_response = service.channels().list(
        part="id,contentDetails", mine=True
    ).execute()
    channels = channel_response.get("items") or []
    expected = os.getenv("YOUTUBE_EXPECTED_CHANNEL_ID", "UC-TFUUc4YHleNoIFXBVaj7A")
    if len(channels) != 1 or channels[0].get("id") != expected:
        raise RuntimeError("OAuth is connected to the wrong YouTube channel")
    playlist_id = channels[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    response = service.playlistItems().list(
        part="snippet", playlistId=playlist_id, maxResults=50
    ).execute()
    uploads: list[dict[str, str]] = []
    for row in response.get("items") or []:
        snippet = row.get("snippet") or {}
        uploads.append(
            {
                "video_id": str((snippet.get("resourceId") or {}).get("videoId") or ""),
                "title": str(snippet.get("title") or ""),
                "description": str(snippet.get("description") or ""),
                "published_at": str(snippet.get("publishedAt") or ""),
            }
        )
    ids = [row["video_id"] for row in uploads if row["video_id"]]
    if not ids:
        return []
    videos = service.videos().list(part="snippet,status,processingDetails", id=",".join(ids)).execute().get("items", [])
    return [
        {"video_id": row["id"], "title": row["snippet"].get("title", ""),
         "description": row["snippet"].get("description", ""),
         "published_at": row["snippet"].get("publishedAt", "")}
        for row in videos
        if row.get("status", {}).get("privacyStatus") == "public"
        and (row.get("status", {}).get("uploadStatus") == "processed"
             or row.get("processingDetails", {}).get("processingStatus") == "succeeded")
    ]


def shorts_today(uploads: list[dict[str, str]], tz: ZoneInfo, today: date) -> int:
    unique_shorts: set[str] = set()
    for upload in uploads:
        text = f"{upload['title']} {upload['description']}".lower()
        if "#shorts" not in text:
            continue
        try:
            published = datetime.fromisoformat(upload["published_at"].replace("Z", "+00:00"))
        except ValueError:
            continue
        if published.astimezone(tz).date() == today:
            source_url = extract_source_url(upload["description"])
            if source_url:
                key = f"source:{_normalize_url(source_url)}"
            else:
                key = f"video:{upload['video_id']}"
            unique_shorts.add(key)
    return len(unique_shorts)


def slot_filled(service) -> tuple[int, int] | None:
    """Return (current, target) when the runner's slot already has its Short.

    Only the slot runners set the target, so manual and other runs upload as before.
    """
    target = int(os.getenv(TARGET_ENV) or 0)
    if target <= 0:
        return None
    tz = ZoneInfo(os.getenv("TIMEZONE", "America/Sao_Paulo"))
    current = shorts_today(recent_uploads(service), tz, datetime.now(tz).date())
    return (current, target) if current >= target else None
