"""YouTube Shorts uploader via Data API v3 (OAuth installed-app flow)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from ..config import settings
from ..models import GeneratedAssets, RewrittenPost
from .base import PublishResult

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


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
            tags = post.hashtags + ["Shorts", "fofoca", "celebridades", "Brasil"]
            description_parts = [
                post.long_caption,
                "",
                f"Fonte: {post.source_url}",
                "",
                " ".join(f"#{tag}" for tag in tags),
                "#Shorts",
            ]
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
