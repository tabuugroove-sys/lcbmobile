"""YouTube Data API helpers for the isolated LOOXX music channel."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from .playlist import SunoTrack

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]
SONG_ID_RE = re.compile(r"Suno track ID:\s*([0-9a-f-]{36})", re.IGNORECASE)


@dataclass(frozen=True)
class RemoteSunoUpload:
    song_id: str
    video_id: str
    title: str
    published_at: datetime


def youtube_service(token_file: Path) -> Any:
    if not token_file.exists():
        raise RuntimeError(
            f"LOOXX YouTube token is missing: {token_file}. "
            "Run scripts.get_looxx_youtube_token first."
        )
    credentials = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    if not credentials.valid:
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            token_file.write_text(credentials.to_json())
        else:
            raise RuntimeError("LOOXX YouTube OAuth token is invalid; authorize it again")
    return build("youtube", "v3", credentials=credentials, cache_discovery=False)


def recent_suno_uploads(service: Any, *, limit: int = 200) -> list[RemoteSunoUpload]:
    channels = service.channels().list(part="contentDetails", mine=True).execute()
    items = channels.get("items", [])
    if not items:
        raise RuntimeError("The authorized Google account does not have a YouTube channel")
    uploads_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    results: list[RemoteSunoUpload] = []
    page_token: str | None = None
    scanned = 0
    while scanned < limit:
        response = (
            service.playlistItems()
            .list(
                part="snippet",
                playlistId=uploads_id,
                maxResults=min(50, limit - scanned),
                pageToken=page_token,
            )
            .execute()
        )
        page_items = response.get("items", [])
        scanned += len(page_items)
        for item in page_items:
            snippet = item.get("snippet", {})
            match = SONG_ID_RE.search(str(snippet.get("description") or ""))
            if not match:
                continue
            published_raw = str(snippet.get("publishedAt") or "")
            try:
                published_at = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            resource = snippet.get("resourceId", {})
            video_id = str(resource.get("videoId") or "")
            if video_id:
                results.append(
                    RemoteSunoUpload(
                        song_id=match.group(1).lower(),
                        video_id=video_id,
                        title=str(snippet.get("title") or ""),
                        published_at=published_at,
                    )
                )
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return results


def video_description(track: SunoTrack, playlist_url: str) -> str:
    lines = [
        f"{track.title} — official audio by LOOXX.",
        "",
    ]
    if track.description:
        lines.extend([track.description, ""])
    lines.extend(
        [
            f"Listen on Suno: {track.suno_url}",
            f"LOOXX 70s Radio playlist: {playlist_url}",
            "",
            "Created by Tabuu with Suno.",
            f"Suno track ID: {track.song_id}",
            "",
            "#LOOXX #NewMusic #SoulFunk #VintageSoul #Suno",
        ]
    )
    return "\n".join(lines)[:5000]


def video_body(
    track: SunoTrack,
    playlist_url: str,
    *,
    privacy_status: str,
) -> dict[str, object]:
    privacy = privacy_status if privacy_status in {"public", "unlisted", "private"} else "public"
    return {
        "snippet": {
            "title": f"{track.title} — LOOXX"[:100],
            "description": video_description(track, playlist_url),
            "tags": [
                "LOOXX",
                "Tabuu",
                "new music",
                "vintage soul",
                "soul funk",
                "70s soul",
                "Suno",
                "AI music",
            ],
            "categoryId": "10",
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,
        },
    }


def upload_track(
    service: Any,
    track: SunoTrack,
    video_path: Path,
    playlist_url: str,
    *,
    privacy_status: str = "public",
) -> str:
    media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
    request = service.videos().insert(
        part="snippet,status",
        body=video_body(track, playlist_url, privacy_status=privacy_status),
        media_body=media,
    )
    response = None
    while response is None:
        progress, response = request.next_chunk()
        if progress is not None:
            log.info("YouTube upload progress: %.0f%%", progress.progress() * 100)
    video_id = str(response.get("id") or "")
    if not video_id:
        raise RuntimeError("YouTube upload returned no video id")
    return video_id
