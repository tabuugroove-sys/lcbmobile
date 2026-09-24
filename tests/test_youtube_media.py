"""Unit tests for YouTube ingestion — yt-dlp is fully mocked, no network."""
from __future__ import annotations

import hashlib
import json
import types
from dataclasses import replace
from pathlib import Path

import pytest

from src.models import NewsItem
from src.video import generator
from src.video.commons_video import LicensedVideo
from src.video.youtube_media import (
    YOUTUBE_LICENSE,
    YOUTUBE_LICENSE_URL,
    fetch_youtube_artist_videos,
)
from src.video import youtube_media


class FakeYoutubeDL:
    """Scriptable stand-in for yt_dlp.YoutubeDL.

    search_entries: entries returned for the flat ytsearch extraction.
    infos: {video_id_or_url: info dict} returned on full extraction.
    fail_on_search / fail_on_sections / fail_always: raise scripted errors.
    """

    def __init__(self, opts, script):
        self.opts = opts
        self.script = script
        script["ydl_opts_seen"].append(opts)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        if "download_ranges" in self.opts and self.script.get("fail_on_sections"):
            raise RuntimeError("sections not supported")
        if self.script.get("fail_always"):
            raise RuntimeError("Sign in to confirm you're not a bot")
        if not download:  # flat search
            if self.script.get("fail_on_search"):
                raise RuntimeError("Sign in to confirm you're not a bot")
            self.script["search_queries"].append(url)
            return {"entries": self.script.get("search_entries", [])}
        info = dict(self.script.get("infos", {}).get(url, {}))
        info.setdefault("id", url.rsplit("=", 1)[-1])
        outtmpl = self.opts.get("outtmpl")
        if outtmpl:
            path = Path(str(outtmpl).replace("%(ext)s", "mp4"))
            path.write_bytes(self.script.get("file_bytes", b"\x00" * 200_000))
            self.script["downloaded_urls"].append(url)
        return info


def _fake_module(script):
    def factory(opts):
        return FakeYoutubeDL(opts, script)

    return types.SimpleNamespace(
        YoutubeDL=factory,
        utils=types.SimpleNamespace(
            download_range_func=lambda chapters, ranges: ("ranges", tuple(ranges))
        ),
    )


def _script(entries, **kwargs):
    script = {
        "search_entries": entries,
        "search_queries": [],
        "downloaded_urls": [],
        "ydl_opts_seen": [],
    }
    script.update(kwargs)
    return script


def _entry(video_id, duration, **extra):
    entry = {
        "id": video_id,
        "title": f"Video {video_id}",
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "duration": duration,
    }
    entry.update(extra)
    return entry


def _info(video_id, **extra):
    info = {
        "id": video_id,
        "title": f"Full title {video_id}",
        "uploader": f"Channel {video_id}",
        "webpage_url": f"https://www.youtube.com/watch?v={video_id}",
        "duration": 240.0,
        "width": 1280,
        "height": 720,
    }
    info.update(extra)
    return info


def test_fetch_returns_honestly_licensed_videos(monkeypatch, tmp_path):
    entries = [_entry("aaa", 120.0), _entry("bbb", 300.0)]
    infos = {e["url"]: _info(e["id"]) for e in entries}
    script = _script(entries, infos=infos)
    monkeypatch.setattr(youtube_media, "yt_dlp", _fake_module(script))

    videos = fetch_youtube_artist_videos("some artist", tmp_path, max_videos=2)

    assert len(videos) == 2
    for video, entry in zip(videos, entries):
        path = Path(video.path)
        assert path.exists()
        assert video.license == YOUTUBE_LICENSE
        assert "not verified" in video.license
        assert video.license_url == YOUTUBE_LICENSE_URL
        assert video.creator == f"Channel {entry['id']}"
        assert video.source_page == entry["url"]
        assert video.title == f"Full title {entry['id']}"
        assert video.seek_seconds == 0.0
        assert video.duration == min(240.0, 30.0)  # partial 0-30s download
        assert video.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    # Partial download was attempted first (download_ranges via ffmpeg).
    download_opts = [o for o in script["ydl_opts_seen"] if o.get("outtmpl")]
    assert download_opts and "download_ranges" in download_opts[0]
    assert script["search_queries"] == ["ytsearch10:some artist"]

    manifest = json.loads((tmp_path / "rights_manifest.json").read_text())
    assert manifest["status"] == "verified"
    assert manifest["query"] == "some artist"
    assert len(manifest["assets"]) == 2


def test_fetch_filters_duration_live_and_availability(monkeypatch, tmp_path):
    entries = [
        _entry("short", 5.0),                                # too short
        _entry("long", 900.0),                               # too long
        _entry("live", 120.0, live_status="is_live"),        # live now
        _entry("upcoming", 120.0, live_status="is_upcoming"),
        _entry("paywall", 120.0, availability="premium_only"),
        _entry("good1", 120.0),
        _entry("good2", 200.0, availability="public"),
        _entry("good3", 300.0),                              # beyond max_videos
    ]
    infos = {e["url"]: _info(e["id"]) for e in entries}
    script = _script(entries, infos=infos)
    monkeypatch.setattr(youtube_media, "yt_dlp", _fake_module(script))

    videos = fetch_youtube_artist_videos("some artist", tmp_path, max_videos=2)

    assert [v.title for v in videos] == ["Full title good1", "Full title good2"]
    assert script["downloaded_urls"] == [
        "https://www.youtube.com/watch?v=good1",
        "https://www.youtube.com/watch?v=good2",
    ]


def test_fetch_returns_empty_list_on_youtube_error(monkeypatch, tmp_path):
    script = _script([], fail_on_search=True)
    monkeypatch.setattr(youtube_media, "yt_dlp", _fake_module(script))

    videos = fetch_youtube_artist_videos("some artist", tmp_path)

    assert videos == []
    manifest = json.loads((tmp_path / "rights_manifest.json").read_text())
    assert manifest["status"] == "error"


def test_fetch_falls_back_to_full_download(monkeypatch, tmp_path):
    entries = [_entry("ccc", 240.0)]
    script = _script(entries, infos={entries[0]["url"]: _info("ccc")},
                     fail_on_sections=True)
    monkeypatch.setattr(youtube_media, "yt_dlp", _fake_module(script))

    videos = fetch_youtube_artist_videos("some artist", tmp_path, max_videos=1)

    assert len(videos) == 1
    assert videos[0].duration == 240.0  # full file, not the 30s section
    assert script["downloaded_urls"] == ["https://www.youtube.com/watch?v=ccc"]


def _item() -> NewsItem:
    return NewsItem(
        source_id="feed",
        source_name="Test Feed",
        category="music",
        url="https://example.com/story",
        title="Some Artist drops a surprise single",
    )


def _fake_video(path: Path, name: str) -> LicensedVideo:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * 150_000)
    return LicensedVideo(
        path=str(path),
        title=name,
        creator="creator",
        license="CC BY 3.0",
        license_url="https://creativecommons.org/licenses/by/3.0/",
        source_page="https://example.com/page",
        source_url="https://example.com/video.webm",
        width=1280,
        height=720,
        duration=60.0,
        seek_seconds=0.0,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def _patch_common(monkeypatch, tmp_path, *, enabled, mode="fallback", curated=()):
    calls = {"youtube": 0}

    monkeypatch.setattr(generator, "find_known_music_act", lambda title: "some artist")
    monkeypatch.setattr(
        generator, "fetch_licensed_artist_images", lambda *a, **k: []
    )
    monkeypatch.setattr(
        generator,
        "fetch_licensed_artist_videos",
        lambda *a, **k: list(curated),
    )

    def fake_youtube(*a, **k):
        calls["youtube"] += 1
        return [_fake_video(tmp_path / "youtube_video" / "yt.mp4", "yt")]

    monkeypatch.setattr(generator, "fetch_youtube_artist_videos", fake_youtube)
    new_settings = replace(
        generator.settings,
        youtube_video_enabled=enabled,
        youtube_video_mode=mode,
        allow_source_article_image=False,
        min_visual_media_assets=0,
        min_video_media_assets=0,
    )
    monkeypatch.setattr(generator, "settings", new_settings)
    return calls


def test_resolve_visual_media_skips_youtube_when_disabled(monkeypatch, tmp_path):
    calls = _patch_common(monkeypatch, tmp_path, enabled=False)

    _, _, videos = generator.resolve_visual_media(_item(), tmp_path)

    assert videos == []
    assert calls["youtube"] == 0


def test_resolve_visual_media_uses_youtube_when_curated_empty(monkeypatch, tmp_path):
    calls = _patch_common(monkeypatch, tmp_path, enabled=True)

    _, _, videos = generator.resolve_visual_media(_item(), tmp_path)

    assert calls["youtube"] == 1
    assert len(videos) == 1
    assert videos[0].title == "yt"


def test_resolve_visual_media_prefers_curated_over_youtube(monkeypatch, tmp_path):
    curated = [_fake_video(tmp_path / "licensed_video" / "curated.webm", "curated")]
    calls = _patch_common(monkeypatch, tmp_path, enabled=True, curated=curated)

    _, _, videos = generator.resolve_visual_media(_item(), tmp_path)

    assert calls["youtube"] == 0
    assert videos == curated


def test_resolve_visual_media_mode_off_suppresses_youtube(monkeypatch, tmp_path):
    calls = _patch_common(monkeypatch, tmp_path, enabled=True, mode="off")

    _, _, videos = generator.resolve_visual_media(_item(), tmp_path)

    assert videos == []
    assert calls["youtube"] == 0
