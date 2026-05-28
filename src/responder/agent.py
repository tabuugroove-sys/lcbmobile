"""Orchestrate: read comments on our uploads -> generate reply -> post it.

YouTube only. Posts replies immediately (no approval step). Self-contained:
discovers our videos from the channel's own uploads playlist, so it does not
depend on the publish pipeline's state DB.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from ..config import ROOT, settings
from ..notify import notify
from .reply_writer import generate_reply
from .store import CommentStore

log = logging.getLogger(__name__)

# OAuth scope needed to read comment threads AND insert replies.
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def _service():
    """Build an authenticated YouTube service from the OAuth token file.

    Comment insertion is a write op, so the read-only API key path used by
    the metrics collector is not usable here — we must use OAuth creds.
    """
    token_file = Path(settings.youtube_token_file)
    if not token_file.exists():
        log.error("Comment responder: token file %s not found", token_file)
        return None

    creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_file.write_text(creds.to_json())
    if not creds.valid:
        log.error("Comment responder: OAuth token is not valid")
        return None

    have = set(creds.scopes or [])
    if "https://www.googleapis.com/auth/youtube.force-ssl" not in have:
        log.error(
            "Comment responder: token is missing youtube.force-ssl scope "
            "(scopes=%s). Re-run scripts.get_youtube_token.",
            sorted(have),
        )
        return None
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _channel_context(service) -> tuple[str, str] | None:
    """Return (our_channel_id, uploads_playlist_id)."""
    resp = service.channels().list(part="contentDetails", mine=True).execute()
    items = resp.get("items", [])
    if not items:
        return None
    channel_id = items[0]["id"]
    uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    return channel_id, uploads


def _recent_video_ids(service, uploads_playlist: str, limit: int) -> list[tuple[str, str]]:
    """Return [(video_id, title)] for the most recent `limit` uploads."""
    out: list[tuple[str, str]] = []
    page_token = None
    while len(out) < limit:
        resp = (
            service.playlistItems()
            .list(
                part="contentDetails,snippet",
                playlistId=uploads_playlist,
                maxResults=min(50, limit - len(out)),
                pageToken=page_token,
            )
            .execute()
        )
        for it in resp.get("items", []):
            vid = it["contentDetails"].get("videoId")
            title = it.get("snippet", {}).get("title", "")
            if vid:
                out.append((vid, title))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return out[:limit]


def _comment_threads(service, video_id: str, max_results: int):
    try:
        resp = (
            service.commentThreads()
            .list(
                part="snippet,replies",
                videoId=video_id,
                order="time",
                maxResults=min(100, max_results),
                textFormat="plainText",
            )
            .execute()
        )
        return resp.get("items", [])
    except HttpError as exc:
        # Comments disabled on the video, or transient API error — skip quietly.
        log.info("Skipping comments for %s: %s", video_id, exc)
        return []


def _already_replied_by_us(thread: dict, our_channel_id: str) -> bool:
    """Best-effort second dedup layer using the replies the API returned."""
    for reply in thread.get("replies", {}).get("comments", []):
        snip = reply.get("snippet", {})
        author = (snip.get("authorChannelId") or {}).get("value")
        if author and author == our_channel_id:
            return True
    return False


def run_comment_responder(*, dry_run: bool = False) -> dict[str, int]:
    dry_run = dry_run or os.getenv("COMMENT_DRY_RUN", "").strip().lower() in {
        "1", "true", "yes", "on"
    }
    lookback = _int_env("COMMENT_LOOKBACK_VIDEOS", 30)
    max_per_run = _int_env("COMMENT_MAX_PER_RUN", 10)
    max_per_video = _int_env("COMMENT_MAX_PER_VIDEO", 5)
    daily_cap = _int_env("COMMENT_DAILY_CAP", 120)

    db_path = Path(os.getenv("COMMENTS_DB_PATH", str(ROOT / "data" / "comments.db")))
    store = CommentStore(db_path)

    stats = {"videos": 0, "scanned": 0, "replied": 0, "skipped": 0, "errors": 0}

    service = _service()
    if service is None:
        notify("⚠️ Comment responder: sem token YouTube valido (force-ssl).")
        return stats

    ctx = _channel_context(service)
    if not ctx:
        log.error("Comment responder: could not resolve channel")
        return stats
    our_channel_id, uploads_playlist = ctx

    already_today = store.replied_count_today()
    budget = max(0, min(max_per_run, daily_cap - already_today))
    if budget == 0:
        log.info(
            "Comment responder: daily cap reached (%d/%d), nothing to do",
            already_today, daily_cap,
        )
        return stats

    videos = _recent_video_ids(service, uploads_playlist, lookback)
    stats["videos"] = len(videos)

    for video_id, title in videos:
        if stats["replied"] >= budget:
            break
        replied_this_video = 0
        for thread in _comment_threads(service, video_id, max_results=100):
            if stats["replied"] >= budget or replied_this_video >= max_per_video:
                break
            top = thread["snippet"]["topLevelComment"]
            comment_id = top["id"]
            snip = top["snippet"]
            author_channel = (snip.get("authorChannelId") or {}).get("value")
            text = snip.get("textOriginal") or snip.get("textDisplay") or ""
            author = snip.get("authorDisplayName", "")

            # Never reply to our own comments/replies.
            if author_channel and author_channel == our_channel_id:
                continue
            if store.is_handled(comment_id):
                continue
            if _already_replied_by_us(thread, our_channel_id):
                store.mark_handled(comment_id, video_id, "skipped", reason="pre-existing reply")
                continue

            stats["scanned"] += 1
            decision = generate_reply(title, text, author)
            if not decision["should_reply"]:
                if not dry_run:
                    store.mark_handled(
                        comment_id, video_id, "skipped", reason=decision["reason"][:200]
                    )
                stats["skipped"] += 1
                continue

            if dry_run:
                stats["replied"] += 1
                replied_this_video += 1
                log.info(
                    "[DRY] would reply to %s on %s\n  comment: %s\n  reply: %s",
                    comment_id, video_id, text[:120], decision["reply"],
                )
                continue

            try:
                created = (
                    service.comments()
                    .insert(
                        part="snippet",
                        body={
                            "snippet": {
                                "parentId": comment_id,
                                "textOriginal": decision["reply"],
                            }
                        },
                    )
                    .execute()
                )
                store.mark_handled(
                    comment_id, video_id, "replied",
                    reply_id=created.get("id"), reason=decision["reason"][:200],
                )
                stats["replied"] += 1
                replied_this_video += 1
                log.info("Replied to %s on %s: %s", comment_id, video_id, decision["reply"][:80])
            except HttpError as exc:
                # Do NOT mark handled on a transient failure — retry next run.
                stats["errors"] += 1
                log.warning("Failed to reply to %s: %s", comment_id, exc)

    log.info(
        "Comment responder done: videos=%(videos)d scanned=%(scanned)d "
        "replied=%(replied)d skipped=%(skipped)d errors=%(errors)d", stats
    )
    if stats["replied"] or stats["errors"]:
        notify(
            "💬 Respostas YouTube\n"
            f"replied={stats['replied']} skipped={stats['skipped']} "
            f"scanned={stats['scanned']} videos={stats['videos']} "
            f"errors={stats['errors']}"
        )
    return stats
