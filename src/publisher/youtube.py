"""YouTube Shorts uploader via Data API v3 (OAuth installed-app flow)."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from ..config import settings
from ..models import GeneratedAssets, RewrittenPost, _normalize_url
from .base import PublishResult

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

_SOURCE_URL_RE = re.compile(r"^Fonte:\s*(https?://\S+)", re.IGNORECASE | re.MULTILINE)


def _source_urls(description: str) -> set[str]:
    """Return canonical source URLs embedded in a YouTube description."""
    return {
        normalized
        for raw_url in _SOURCE_URL_RE.findall(description or "")
        if (normalized := _normalize_url(raw_url.rstrip(".,;)")))
    }


def _existing_upload_for_source(service, source_url: str) -> tuple[str, str] | None:
    """Find an already-uploaded video for the same article URL.

    This is intentionally called immediately before upload. A render can take
    many minutes, so the server and a fallback runner may both pass the earlier
    pipeline dedupe check while neither video exists yet.
    """
    expected = _normalize_url(source_url)
    if not expected:
        return None

    channel_response = service.channels().list(
        part="contentDetails", mine=True
    ).execute()
    channels = channel_response.get("items") or []
    if not channels:
        raise RuntimeError("Authenticated Google account has no YouTube channel")
    playlist_id = channels[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    response = service.playlistItems().list(
        part="snippet", playlistId=playlist_id, maxResults=50
    ).execute()
    for row in response.get("items") or []:
        snippet = row.get("snippet") or {}
        if expected not in _source_urls(str(snippet.get("description") or "")):
            continue
        video_id = str((snippet.get("resourceId") or {}).get("videoId") or "")
        if video_id:
            return video_id, str(snippet.get("title") or "")
    return None


class YouTubePublisher:
    name = "youtube"

    def is_configured(self) -> bool:
        return Path(settings.youtube_client_secret_file).exists()

    def _service(self):
        token_file = Path(settings.youtube_token_file)
        creds: Credentials | None = None
        if token_file.exists():
            creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(settings.youtube_client_secret_file), SCOPES
                )
                creds = flow.run_local_server(port=0)
            token_file.write_text(creds.to_json())
        return build("youtube", "v3", credentials=creds, cache_discovery=False)

    def publish(self, post: RewrittenPost, assets: GeneratedAssets) -> PublishResult:
        try:
            yt = self._service()
            existing = _existing_upload_for_source(yt, post.source_url)
            if existing:
                video_id, title = existing
                log.warning(
                    "Remote dedupe blocked duplicate upload for %s; reusing %s (%s)",
                    post.source_url,
                    video_id,
                    title,
                )
                return PublishResult(
                    platform=self.name,
                    ok=True,
                    remote_id=video_id,
                    url=f"https://youtube.com/shorts/{video_id}",
                    reused_existing=True,
                )
            tags = post.hashtags + ["Shorts", "fofoca", "celebridades", "Brasil"]
            credits_path = Path(assets.video_path).parent / "media_credits.txt"
            media_credits = ""
            if credits_path.exists():
                media_credits = credits_path.read_text(encoding="utf-8").strip()
            description_parts = [
                post.long_caption,
                "",
                f"Fonte: {post.source_url}",
            ]
            if media_credits:
                description_parts.extend(["", media_credits])
            description_parts.extend(
                ["", " ".join(f"#{tag}" for tag in tags), "#Shorts"]
            )
            body = {
                "snippet": {
                    "title": post.headline[:95] + " #Shorts",
                    "description": "\n".join(description_parts)[:4900],
                    "tags": tags[:30],
                    "categoryId": settings.youtube_category_id,
                    "defaultLanguage": "pt-BR",
                    "defaultAudioLanguage": "pt-BR",
                },
                "status": {
                    "privacyStatus": "public",
                    "selfDeclaredMadeForKids": False,
                },
            }
            media = MediaFileUpload(assets.video_path, mimetype="video/mp4", resumable=True)
            request = yt.videos().insert(part="snippet,status", body=body, media_body=media)
            response = None
            while response is None:
                _, response = request.next_chunk()
            video_id = response["id"]
            return PublishResult(
                platform=self.name,
                ok=True,
                remote_id=video_id,
                url=f"https://youtube.com/shorts/{video_id}",
            )
        except HttpError as exc:
            return PublishResult(platform=self.name, ok=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            log.exception("YouTube publish failed")
            return PublishResult(platform=self.name, ok=False, error=str(exc))


def hours_since_latest_short() -> float | None:
    """Read the channel itself so local and GitHub runners share one gap gate."""
    if not Path(settings.youtube_token_file).exists():
        return None
    service = YouTubePublisher()._service()
    channel_response = service.channels().list(
        part="contentDetails", mine=True
    ).execute()
    channels = channel_response.get("items") or []
    if not channels:
        return None
    playlist_id = channels[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    response = service.playlistItems().list(
        part="snippet", playlistId=playlist_id, maxResults=10
    ).execute()
    for row in response.get("items") or []:
        snippet = row.get("snippet") or {}
        text = f"{snippet.get('title', '')} {snippet.get('description', '')}".lower()
        if "#shorts" not in text:
            continue
        raw = str(snippet.get("publishedAt") or "")
        if not raw:
            continue
        published = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return max(
            0.0,
            (datetime.now(timezone.utc) - published.astimezone(timezone.utc)).total_seconds()
            / 3600.0,
        )
    return None
