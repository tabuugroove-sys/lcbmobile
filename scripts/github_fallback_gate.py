"""Live YouTube quota gate for the scheduled GitHub Actions failover."""
from __future__ import annotations

import argparse
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]
SCHEDULE_TARGETS = {
    "13 13 * * *": 1,
    "13 18 * * *": 2,
    "13 23 * * *": 3,
}


def target_for_schedule(schedule: str) -> int:
    return SCHEDULE_TARGETS.get(schedule.strip(), 0)


def shorts_today(rows: list[dict], tz: ZoneInfo, today) -> int:
    count = 0
    for row in rows:
        snippet = row.get("snippet") or {}
        text = f"{snippet.get('title', '')} {snippet.get('description', '')}".lower()
        if "#shorts" not in text:
            continue
        published_at = str(snippet.get("publishedAt") or "")
        try:
            published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if published.astimezone(tz).date() == today:
            count += 1
    return count


def current_short_count(token_file: Path, tz: ZoneInfo) -> int:
    credentials = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    if not credentials.valid:
        if not credentials.refresh_token:
            raise RuntimeError("YouTube token has no refresh token")
        credentials.refresh(Request())
        token_file.write_text(credentials.to_json(), encoding="utf-8")
    service = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    channels = service.channels().list(part="contentDetails", mine=True).execute()
    channel_rows = channels.get("items") or []
    if not channel_rows:
        raise RuntimeError("Authenticated Google account has no YouTube channel")
    playlist_id = channel_rows[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    uploads = service.playlistItems().list(
        part="snippet",
        playlistId=playlist_id,
        maxResults=50,
    ).execute()
    now = datetime.now(tz)
    return shorts_today(uploads.get("items") or [], tz, now.date())


def write_github_output(path: str, **values: object) -> None:
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("gate", "verify"), required=True)
    parser.add_argument("--schedule", default="")
    parser.add_argument("--github-output", default=os.getenv("GITHUB_OUTPUT", ""))
    parser.add_argument("--attempts", type=int, default=1)
    parser.add_argument("--delay-seconds", type=float, default=0)
    args = parser.parse_args()

    target = target_for_schedule(args.schedule)
    if target == 0:
        if args.mode == "verify":
            raise SystemExit(f"Unknown fallback schedule: {args.schedule!r}")
        reason = "manual trigger: live quota gate bypassed"
        write_github_output(
            args.github_output,
            should_run="true",
            target=0,
            current="unknown",
            reason=reason,
        )
        print(reason)
        return 0

    tz = ZoneInfo(os.getenv("TIMEZONE", "America/Sao_Paulo"))
    token_file = Path(os.getenv("YOUTUBE_TOKEN_FILE", "youtube_token.json"))
    attempts = max(1, args.attempts)
    current = -1
    error = ""
    for attempt in range(1, attempts + 1):
        try:
            current = current_short_count(token_file, tz)
            error = ""
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
            print(f"YouTube quota check {attempt}/{attempts} failed: {exc}")
        if current >= target:
            break
        if attempt < attempts and args.delay_seconds > 0:
            time.sleep(args.delay_seconds)

    if args.mode == "gate":
        should_run = current < target
        reason = (
            f"cloud fallback needed: youtube_shorts_today={current} target={target}"
            if should_run
            else f"cloud fallback skipped: youtube_shorts_today={current} target={target}"
        )
        if error and current < 0:
            reason = f"live quota unavailable; failover will attempt publication: {error}"
        write_github_output(
            args.github_output,
            should_run=str(should_run).lower(),
            target=target,
            current=current,
            reason=reason,
        )
        print(reason)
        return 0

    if current >= target:
        print(f"Verified YouTube quota: {current}/{target}")
        return 0
    print(f"YouTube quota still missing after cloud failover: {current}/{target}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
