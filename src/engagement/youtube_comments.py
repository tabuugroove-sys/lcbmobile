"""Auto-reply to new YouTube comments on recently published Shorts."""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from ..config import settings
from ..storage import Store

log = logging.getLogger(__name__)

COMMENT_SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)
_URL_OR_HANDLE = re.compile(r"(https?://|www\.|t\.me/|wa\.me/|@\w{3,})", re.I)


@dataclass
class CommentReplyReport:
    videos_checked: int = 0
    comments_seen: int = 0
    replies_sent: int = 0
    skipped: int = 0
    errors: int = 0
    likes_sent: int = 0
    likes_unsupported: int = 0


def _youtube_service():
    token_file = Path(settings.youtube_token_file)
    creds: Credentials | None = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), COMMENT_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        elif Path(settings.youtube_client_secret_file).exists():
            if os.getenv("GITHUB_ACTIONS"):
                raise RuntimeError("YOUTUBE_TOKEN is required in GitHub Actions.")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(settings.youtube_client_secret_file), COMMENT_SCOPES
            )
            creds = flow.run_local_server(port=0)
        else:
            raise RuntimeError("YouTube OAuth token/client secret is not configured.")
        token_file.write_text(creds.to_json())
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _extract_json(text: str) -> dict[str, Any]:
    match = _JSON_BLOCK.search(text)
    if not match:
        raise ValueError(f"No JSON object in reply writer response: {text[:200]!r}")
    return json.loads(match.group(0))


def _is_obvious_spam(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return True
    if _URL_OR_HANDLE.search(lowered):
        return True
    spam_bits = ["subscribe", "inscreva", "ganhe dinheiro", "pix", "telegram"]
    return any(bit in lowered for bit in spam_bits)


def _draft_reply(*, video_title: str, author_name: str, comment_text: str) -> str | None:
    if _is_obvious_spam(comment_text):
        return None
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured.")

    client = Anthropic(api_key=settings.anthropic_api_key)
    response = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=140,
        temperature=0.7,
        system=(
            "Voce responde comentarios de um canal brasileiro de Shorts de fofoca "
            "e entretenimento. Responda em pt-BR, de forma curta, calorosa e natural. "
            "Nao invente fatos, nao prometa nada, nao use links, nao peca like/sub. "
            "Se o comentario for spam, odio, assedio, pedido ilegal ou muito confuso, "
            "retorne action=skip. Responda somente JSON valido."
        ),
        messages=[
            {
                "role": "user",
                "content": (
                    "Gere resposta para este comentario.\n\n"
                    f"VIDEO: {video_title}\n"
                    f"AUTOR: {author_name or 'desconhecido'}\n"
                    f"COMENTARIO: {comment_text}\n\n"
                    'Formato: {"action":"reply|skip","reply":"texto ate 180 caracteres"}'
                ),
            }
        ],
    )
    text = "".join(
        block.text for block in response.content if getattr(block, "type", "") == "text"
    )
    payload = _extract_json(text)
    if payload.get("action") != "reply":
        return None
    reply = str(payload.get("reply") or "").strip()
    reply = " ".join(reply.split())
    if not reply or _URL_OR_HANDLE.search(reply):
        return None
    return reply[:180]


def _list_top_level_comments(yt, video_id: str, max_comments: int) -> list[dict[str, Any]]:
    comments: list[dict[str, Any]] = []
    request = yt.commentThreads().list(
        part="snippet,replies",
        videoId=video_id,
        order="time",
        maxResults=min(max_comments, 100),
        textFormat="plainText",
    )
    while request and len(comments) < max_comments:
        response = request.execute()
        for item in response.get("items", []):
            comments.append(item)
            if len(comments) >= max_comments:
                break
        request = yt.commentThreads().list_next(request, response)
    return comments


def _video_title(yt, video_id: str) -> str:
    response = yt.videos().list(part="snippet", id=video_id).execute()
    items = response.get("items", [])
    if not items:
        return ""
    return items[0].get("snippet", {}).get("title", "")


def _insert_reply(yt, comment_id: str, reply_text: str) -> str:
    response = (
        yt.comments()
        .insert(
            part="snippet",
            body={
                "snippet": {
                    "parentId": comment_id,
                    "textOriginal": reply_text,
                }
            },
        )
        .execute()
    )
    return str(response.get("id") or "")


def respond_to_youtube_comments(
    *,
    store: Store | None = None,
    video_limit: int = 20,
    comment_limit: int = 50,
    reply_limit: int = 10,
    dry_run: bool = False,
) -> CommentReplyReport:
    store = store or Store(settings.db_path)
    report = CommentReplyReport()
    targets = store.youtube_comment_targets(limit=video_limit)
    if not targets:
        log.info("YouTube comment replies skipped: no published YouTube videos.")
        return report

    yt = _youtube_service()
    if reply_limit > 0:
        report.likes_unsupported = 1
        log.info("YouTube comment likes skipped: Data API has no comment-like method.")

    for _, video_id in targets:
        report.videos_checked += 1
        try:
            title = _video_title(yt, video_id)
            threads = _list_top_level_comments(yt, video_id, comment_limit)
        except HttpError as exc:
            report.errors += 1
            log.warning("YouTube comment fetch failed for %s: %s", video_id, exc)
            continue

        for thread in threads:
            if report.replies_sent >= reply_limit:
                return report
            snippet = thread.get("snippet", {})
            top = snippet.get("topLevelComment", {})
            comment_id = str(top.get("id") or "")
            comment_snippet = top.get("snippet", {})
            comment_text = str(comment_snippet.get("textOriginal") or "").strip()
            author_name = str(comment_snippet.get("authorDisplayName") or "").strip()
            author_channel_id = (
                comment_snippet.get("authorChannelId", {}) or {}
            ).get("value")
            report.comments_seen += 1

            if not comment_id or store.youtube_comment_was_processed(comment_id):
                report.skipped += 1
                continue
            if int(snippet.get("totalReplyCount") or 0) > 0:
                report.skipped += 1
                store.record_youtube_comment_action(
                    comment_id=comment_id,
                    video_id=video_id,
                    author_channel_id=author_channel_id,
                    author_name=author_name,
                    comment_text=comment_text,
                    reply_text=None,
                    status="skipped_existing_reply",
                )
                continue

            try:
                reply = _draft_reply(
                    video_title=title,
                    author_name=author_name,
                    comment_text=comment_text,
                )
                if not reply:
                    report.skipped += 1
                    store.record_youtube_comment_action(
                        comment_id=comment_id,
                        video_id=video_id,
                        author_channel_id=author_channel_id,
                        author_name=author_name,
                        comment_text=comment_text,
                        reply_text=None,
                        status="skipped_by_policy",
                    )
                    continue
                if dry_run:
                    log.info("DRY_RUN comment reply %s -> %s", comment_id, reply)
                    report.skipped += 1
                    continue
                reply_id = _insert_reply(yt, comment_id, reply)
                report.replies_sent += 1
                store.record_youtube_comment_action(
                    comment_id=comment_id,
                    video_id=video_id,
                    author_channel_id=author_channel_id,
                    author_name=author_name,
                    comment_text=comment_text,
                    reply_text=reply,
                    status="replied",
                )
                log.info("Replied to YouTube comment %s -> %s", comment_id, reply_id)
            except Exception as exc:  # noqa: BLE001
                report.errors += 1
                store.record_youtube_comment_action(
                    comment_id=comment_id,
                    video_id=video_id,
                    author_channel_id=author_channel_id,
                    author_name=author_name,
                    comment_text=comment_text,
                    reply_text=None,
                    status="error",
                    error=str(exc),
                )
                log.warning("YouTube comment reply failed for %s: %s", comment_id, exc)

    return report
