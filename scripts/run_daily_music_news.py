"""Daily server-first music bulletin. GitHub runs the same edition as a fallback."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from googleapiclient.http import MediaFileUpload

from src.analytics import refresh_youtube_metrics, select_best_candidates
from src.config import ROOT, settings
from src.editorial.music_filter import find_music_act_query, is_music_news
from src.models import NewsItem
from src.notify import notify_urgent
from src.processor.ai_writer import rewrite
from src.publisher.youtube import YouTubePublisher
from src.scraper.music_daily import collect_daily_music_news
from src.storage import Store
from src.video.horizontal_news import prepare_voice, render, reviewed_ranges, save
from src.video.mac_media import fetch_mac_artist_videos
from src.video.youtube_media import fetch_youtube_artist_videos

log = logging.getLogger(__name__)
PLATFORM = "youtube_daily_multinews"
EXPECTED_CHANNEL = "UC-TFUUc4YHleNoIFXBVaj7A"
TZ = ZoneInfo("America/Sao_Paulo")


def marker(edition: str) -> str:
    return f"Radar Musical edition={edition}"


def scheduled_due(now: datetime) -> bool:
    local = now.astimezone(TZ)
    return 15 <= local.hour < 23


def processed(row: dict) -> bool:
    return row.get("processingDetails", {}).get("processingStatus") == "succeeded" or row.get("status", {}).get("uploadStatus") == "processed"


def recent_uploads(service) -> list[dict]:
    channels = service.channels().list(part="id,contentDetails", mine=True).execute().get("items", [])
    expected = os.getenv("YOUTUBE_EXPECTED_CHANNEL_ID", EXPECTED_CHANNEL)
    if len(channels) != 1 or channels[0]["id"] != expected:
        raise RuntimeError("OAuth is connected to the wrong YouTube channel")
    playlist = channels[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    rows = service.playlistItems().list(part="contentDetails", playlistId=playlist, maxResults=50).execute().get("items", [])
    ids = [r["contentDetails"]["videoId"] for r in rows]
    if not ids:
        return []
    return service.videos().list(part="snippet,status,processingDetails", id=",".join(ids)).execute().get("items", [])


def edition_upload(rows: list[dict], edition: str) -> dict | None:
    matching = [r for r in rows if marker(edition) in r["snippet"].get("description", "")
                and r.get("status", {}).get("uploadStatus") not in {"failed", "rejected", "deleted"}
                and r.get("processingDetails", {}).get("processingStatus") != "failed"]
    public = [r for r in matching if r["status"].get("privacyStatus") == "public"]
    return min(public or matching, key=lambda r: (r["snippet"].get("publishedAt", ""), r["id"])) if matching else None


def previous_sources(rows: list[dict], edition: str) -> tuple[set[str], set[str]]:
    videos, news = set(), set()
    for row in rows:
        snippet = row["snippet"]
        if "Radar Musical" not in snippet.get("title", "") or marker(edition) in snippet.get("description", ""):
            continue
        for url in re.findall(r"https?://[^\s|]+", snippet.get("description", "")):
            (videos if "youtube.com/" in url or "youtu.be/" in url else news).add(url.rstrip(".,)"))
        # Only the most recent daily edition, not the entire channel, limits source reuse.
        break
    return videos, news


def candidates_for_day(items: list[NewsItem], edition: str, store: Store, previous_news: set[str]) -> list[NewsItem]:
    today = datetime.fromisoformat(edition).date()
    earliest = today - timedelta(days=1 if settings.fallback_to_yesterday else 0)
    candidates, seen = [], set()
    for item in items:
        if not item.published_at or not is_music_news(item):
            continue
        stamp = item.published_at
        local_date = stamp.replace(tzinfo=timezone.utc).astimezone(TZ).date() if stamp.tzinfo is None else stamp.astimezone(TZ).date()
        if not earliest <= local_date <= today or item.url in previous_news:
            continue
        key = item.content_hash()
        if key in seen or store.already_published(item.fingerprint(), PLATFORM) or store.already_published_by_content(key, PLATFORM):
            continue
        if not find_music_act_query(f"{item.title} {item.summary}"):
            continue
        seen.add(key)
        candidates.append(item)
    # Already published Shorts are intentionally eligible for the daily roundup.
    return candidates


def prepare_stories(candidates: list[NewsItem], store: Store, edition: str, folder: Path, avoid: set[str]) -> list[dict]:
    stories, artists = {}, set()

    def eligible(item: NewsItem) -> bool:
        artist = find_music_act_query(f"{item.title} {item.summary}")
        if not artist or artist.casefold() in artists:
            return False
        key = item.content_hash()
        output = folder / "media" / key
        output.mkdir(parents=True, exist_ok=True)
        try:
            post = rewrite(item)
            assets = fetch_youtube_artist_videos(
                artist, output, max_videos=3, search_query=f"{artist} ao vivo entrevista oficial",
                max_duration=1800, section_seconds=90, min_aspect_ratio=1.55, excluded_sources=avoid,
            )
            if len(assets) < 2:
                assets += fetch_mac_artist_videos(artist, max_videos=2, profile=f"horizontal-{edition}", excluded_sources=avoid)
            usable, seen_sources = [], set()
            for asset in assets:
                if asset.source_page in avoid or asset.source_page in seen_sources or asset.width / max(1, asset.height) < 1.55:
                    continue
                row = asset.as_manifest()
                row["reviewed_ranges"] = reviewed_ranges(row, output)
                if row["reviewed_ranges"]:
                    usable.append(row)
                    seen_sources.add(asset.source_page)
            coverage = sum(b - a for row in usable for a, b in row["reviewed_ranges"])
            # Generous budget at the relaxed voice speed; exact coverage is checked again after TTS.
            required = max(40.0, len(post.script_voiceover.split()) / (1.7 * settings.elevenlabs_speed) + 8)
            if len(usable) < 2 or coverage < required:
                log.warning("Trying another story: %s has %d sources / %.1fs reviewed footage", artist, len(usable), coverage)
                return False
            stories[item.fingerprint()] = {"id": key, "artist": artist, "headline": post.headline,
                "narration": post.script_voiceover, "item": item.model_dump(mode="json"), "assets": usable}
            artists.add(artist.casefold())
            return True
        except Exception as exc:
            log.warning("Media preparation failed for %s: %s", artist, exc)
            return False

    selected = select_best_candidates(candidates, store, limit=5, stage="daily_music_news", eligibility=eligible)
    if len(selected) < 5:
        raise RuntimeError(f"Only {len(selected)} of 5 music stories have sufficient artist footage; choosing new candidates on retry")
    return [stories[item.fingerprint()] for item in selected]


def metadata(stories: list[dict], edition: str, chapters: list[dict]) -> dict:
    headline = stories[0]["headline"][:52]
    title = f"{headline} | Radar Musical {edition[8:10]}/{edition[5:7]} | 5 noticias"
    lines = [f"Cinco noticias musicais em pauta. {marker(edition)}", ""]
    for chapter in chapters:
        minutes, seconds = divmod(int(chapter["start"]), 60)
        lines.append(f"{minutes:02d}:{seconds:02d} {chapter['artist']}: {chapter['headline']}")
    lines += ["", "Narracao original em portugues. Imagens de arquivo, nao necessariamente dos eventos noticiados.", "", "Fontes:"]
    for story in stories:
        lines.append(f"{story['artist']}: {story['item']['url']}")
    lines += ["", "Imagens de arquivo / creditos:"]
    for story in stories:
        for asset in story["assets"]:
            lines.append(f"{story['artist']} / {asset['creator'][:60]}: {asset['source_page']}")
    lines += ["", "#NoticiasMusicais #MusicaBrasileira"]
    return {"title": title[:100], "description": "\n".join(lines)[:4900],
            "categoryId": "10", "defaultLanguage": "pt-BR", "defaultAudioLanguage": "pt-BR",
            "tags": ["noticias musicais", "musica brasileira"] + [s["artist"] for s in stories]}


def publish_verified(service, video: Path | None, snippet: dict | None, edition: str, state_file: Path) -> str:
    existing = edition_upload(recent_uploads(service), edition)
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    video_id = existing["id"] if existing else state.get("video_id")
    if not video_id:
        if video is None or snippet is None:
            raise RuntimeError("No video available to upload")
        media = MediaFileUpload(str(video), mimetype="video/mp4", resumable=True, chunksize=8 * 1024 * 1024)
        request = service.videos().insert(part="snippet,status", body={"snippet": snippet,
            "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False}}, media_body=media)
        if state.get("resumable_uri"):
            request.resumable_uri = state["resumable_uri"]
            request._in_error_state = True
        elif state.get("upload_started"):
            raise RuntimeError("Previous upload outcome is unknown; remote reconciliation required before another insert")
        state = {**state, "upload_started": True}
        save(state_file, state)
        os.chmod(state_file, 0o600)
        response = None
        while response is None:
            try:
                _, response = request.next_chunk(num_retries=3)
            finally:
                if request.resumable_uri:
                    state["resumable_uri"] = request.resumable_uri
                    save(state_file, state)
            if response:
                video_id = response["id"]
                save(state_file, {"video_id": video_id})
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        rows = service.videos().list(part="snippet,status,processingDetails", id=video_id).execute().get("items", [])
        if not rows:
            time.sleep(15)
            continue
        row = rows[0]
        if marker(edition) not in row["snippet"].get("description", ""):
            raise RuntimeError("Pending upload does not belong to this edition")
        status = row.get("processingDetails", {}).get("processingStatus")
        if status in {"failed", "terminated"} or row["status"].get("uploadStatus") in {"failed", "rejected"}:
            if state_file.exists():
                state_file.replace(state_file.with_name(f"{state_file.stem}-failed-{video_id}.json"))
            raise RuntimeError("YouTube rejected the staged daily video")
        if status == "succeeded" or row["status"].get("uploadStatus") == "processed":
            # Both runners stage privately. Only the earliest visible edition becomes public.
            winner = edition_upload(recent_uploads(service), edition)
            if winner is None:
                time.sleep(15)
                continue
            if winner["id"] != video_id:
                if winner["status"].get("privacyStatus") == "public" and processed(winner):
                    return winner["id"]
                video_id = winner["id"]
                continue
            if row["status"].get("privacyStatus") != "public":
                service.videos().update(part="status", body={"id": video_id,
                    "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False}}).execute()
            receipt = edition_upload(recent_uploads(service), edition)
            if receipt and receipt["id"] == video_id and receipt["status"].get("privacyStatus") == "public" and processed(receipt):
                return video_id
        time.sleep(15)
    raise RuntimeError("YouTube processing is still pending; next attempt will resume the same video")


def run_edition(store: Store, edition: str, folder: Path, publish: bool, preflight: bool = False) -> dict:
    if not settings.youtube_token_file.exists():
        raise RuntimeError("YouTube OAuth token is required; daily runners never open an interactive login")
    service = YouTubePublisher()._service()
    remote = recent_uploads(service)
    pending = edition_upload(remote, edition)
    # Resumable URIs are credentials: exclude them from the shared Actions data cache.
    state_file = settings.youtube_token_file.parent / f".daily-upload-{edition}.json"
    if pending and publish:
        video_id = publish_verified(service, None, None, edition, state_file)
        return {"status": "public", "video_id": video_id, "url": f"https://www.youtube.com/watch?v={video_id}", "reconciled": True}
    refresh_youtube_metrics(store)
    avoid, previous_news = previous_sources(remote, edition)
    avoid |= store.latest_daily_video_assets()
    candidates = candidates_for_day(collect_daily_music_news(), edition, store, previous_news)
    rejected_file = folder / "rejected-stories.json"
    rejected = set(json.loads(rejected_file.read_text()) if rejected_file.exists() else [])
    candidates = [item for item in candidates if item.content_hash() not in rejected]
    if preflight:
        return {"status": "preflight", "edition": edition, "music_candidates": len(candidates),
                "artists": [find_music_act_query(f"{i.title} {i.summary}") for i in candidates],
                "analytics_examples": len(store.analytics_examples(settings.analytics_history_limit)), "publish": False}
    package = folder / "package.json"
    if package.exists():
        stories = json.loads(package.read_text(encoding="utf-8"))["stories"]
    else:
        stories = prepare_stories(candidates, store, edition, folder, avoid)
        save(package, {"edition": edition, "stories": stories})
    prepare_voice(stories, folder)
    video = folder / f"radar-musical-{edition}-16x9.mp4"
    if not video.exists() or not (folder / "qa-report.json").exists():
        try:
            video = render(stories, edition, folder)
        except RuntimeError as exc:
            bad_artists = {s["artist"] for s in stories if s["artist"] in str(exc)}
            qa_path = folder / "qa-report.json"
            if qa_path.exists():
                failed = json.loads(qa_path.read_text())
                timeline = json.loads((folder / "timeline.json").read_text())
                for a, b in failed.get("black_intervals", []):
                    bad_artists.update(shot["artist"] for shot in timeline if shot["start"] < b and shot["start"] + shot["duration"] > a)
            if bad_artists:
                rejected.update(s["id"] for s in stories if s["artist"] in bad_artists)
                save(rejected_file, sorted(rejected))
                package.unlink(missing_ok=True)
            video.unlink(missing_ok=True)
            qa_path.unlink(missing_ok=True)
            raise
    qa = json.loads((folder / "qa-report.json").read_text())
    if qa.get("black_intervals") or qa.get("silences_over_2s") or not qa.get("full_decode_passed"):
        raise RuntimeError("Daily video did not pass review")
    if qa.get("video_sha256") != hashlib.sha256(video.read_bytes()).hexdigest():
        raise RuntimeError("Rendered video differs from the reviewed artifact")
    snippet = metadata(stories, edition, json.loads((folder / "chapters.json").read_text()))
    save(folder / "youtube-metadata.json", {"snippet": snippet})
    if not publish:
        return {"status": "dry_run", "video": str(video), "qa": qa}
    video_id = publish_verified(service, video, snippet, edition, state_file)
    asset_ids = [a["source_page"] for s in stories for a in s["assets"]]
    store.record_daily_video_assets(run_fingerprint=marker(edition), asset_ids=asset_ids, status="ok", remote_id=video_id)
    for story in stories:
        item = NewsItem(**story["item"])
        store.record_item_features(item)
        store.record_publication(item.fingerprint(), PLATFORM, video_id, "ok", content_hash=item.content_hash())
    return {"status": "public", "video_id": video_id, "url": f"https://www.youtube.com/watch?v={video_id}",
            "video_sha256": hashlib.sha256(video.read_bytes()).hexdigest(), "qa": qa}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-publish", action="store_true")
    parser.add_argument("--scheduled", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--attempts", type=int, default=5)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    now = datetime.now(TZ)
    if args.scheduled and not scheduled_due(now):
        print(json.dumps({"status": "not_due", "next_slot_brt": "15:00", "now_brt": now.isoformat()}))
        return
    edition = now.date().isoformat()
    store = Store(settings.db_path)
    if not args.no_publish and not args.preflight and store.is_seen(marker(edition)):
        print(json.dumps({"status": "already_public", "edition": edition}))
        return
    folder = (settings.output_dir / "daily_music_news" / edition).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    # Scheduler IgnoreNew / GitHub concurrency serialize each host; remote edition election covers fallback races.
    last_try = folder / "last-attempt.json"
    if args.scheduled and last_try.exists():
        age = datetime.now(timezone.utc).timestamp() - json.loads(last_try.read_text())["timestamp"]
        if age < 900:
            print(json.dumps({"status": "retry_cooldown", "retry_after_seconds": int(900 - age)}))
            return
    attempts = 1 if args.preflight or args.no_publish else max(1, min(args.attempts, 5))
    for attempt in range(1, attempts + 1):
        save(last_try, {"timestamp": datetime.now(timezone.utc).timestamp(), "attempt": attempt})
        try:
            result = run_edition(store, edition, folder, not args.no_publish and not args.preflight, args.preflight)
            save(folder / "publication-receipt.json", result)
            if result["status"] == "public":
                store.record_publication(marker(edition), PLATFORM, result["video_id"], "ok")
                store.mark_seen(marker(edition), "daily_music_news", result["url"], f"Radar Musical {edition}")
            print(json.dumps(result, ensure_ascii=False))
            return
        except Exception as exc:
            log.exception("Daily edition %s attempt %d failed", edition, attempt)
            notify_urgent(f"LCB daily 16:9 {edition}: attempt {attempt}/{attempts} failed. {str(exc)[:600]}")
            if attempt == attempts:
                raise
            time.sleep(settings.retry_delay_seconds)


if __name__ == "__main__":
    main()
