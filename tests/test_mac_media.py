from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from http.cookiejar import Cookie
from pathlib import Path
from unittest import mock

import pytest
from yt_dlp.cookies import YoutubeDLCookieJar

from scripts import export_youtube_cookies, mac_media_worker
from src.video import mac_media


def stamp(seconds_ago=0):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


def heartbeat(root, *, seconds_ago=0, status="ready"):
    mac_media.write_json(root / "heartbeat.json", {"updated_at": stamp(seconds_ago), "status": status})


def manifest(root, *, artist="rihanna", assets=True, requested_at=""):
    folder = root / "assets" / mac_media.artist_key(artist)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "clip-01.mp4"
    path.write_bytes(b"test-video" * 20000)
    rows = [{
        "file": path.name, "title": "Rihanna interview", "creator": "Test source",
        "license": "YouTube standard license (reuse rights not verified)",
        "license_url": "https://example.com/terms", "source_page": "https://example.com/video",
        "source_url": "https://example.com/video", "width": 1280, "height": 720,
        "duration": 30.0, "seek_seconds": 0.0,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }] if assets else []
    data = {"artist": artist, "assets": rows, "updated_at": stamp(), "requested_at": requested_at}
    mac_media.write_json(folder / "manifest.json", data)
    return folder, data


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("MAC_MEDIA_ROOT", str(tmp_path))
    monkeypatch.setattr(mac_media, "_wait_spent", 0.0)


@pytest.mark.parametrize("seconds_ago,status", [(600, "ready"), (0, "unavailable"), (-60, "ready")])
def test_offline_mac_never_delays_cloud(tmp_path, seconds_ago, status):
    heartbeat(tmp_path, seconds_ago=seconds_ago, status=status)
    with mock.patch.object(mac_media.time, "sleep") as sleep:
        assert mac_media.fetch_mac_artist_videos("rihanna") == []
    sleep.assert_not_called()
    assert not (tmp_path / "requests").exists()


def test_cached_footage_remains_usable_when_mac_is_offline(tmp_path):
    manifest(tmp_path)
    videos = mac_media.fetch_mac_artist_videos("rihanna")
    assert len(videos) == 1
    assert Path(videos[0].path).exists()


def test_corrupt_cached_clip_is_rejected(tmp_path):
    folder, _ = manifest(tmp_path)
    (folder / "clip-01.mp4").write_bytes(b"corrupted" * 20000)
    assert mac_media.cached_mac_artist_videos("rihanna") == []


@pytest.mark.parametrize("rows", [42, None, {}, [None, "broken"]])
def test_malformed_cache_never_breaks_cloud(tmp_path, rows):
    folder, data = manifest(tmp_path)
    data["assets"] = rows
    mac_media.write_json(folder / "manifest.json", data)
    assert mac_media.fetch_mac_artist_videos("rihanna") == []


def test_ready_mac_response_supplies_real_asset(tmp_path):
    heartbeat(tmp_path)

    def complete(_delay):
        request = json.loads(next((tmp_path / "requests").glob("*.json")).read_text())
        manifest(tmp_path, requested_at=request["requested_at"])

    with mock.patch.object(mac_media.time, "sleep", side_effect=complete):
        videos = mac_media.fetch_mac_artist_videos("rihanna")
    assert len(videos) == 1
    assert mac_media._wait_spent > 0


def test_failed_worker_response_does_not_wait_for_timeout(tmp_path):
    heartbeat(tmp_path)

    def complete(_delay):
        request = json.loads(next((tmp_path / "requests").glob("*.json")).read_text())
        manifest(tmp_path, assets=False, requested_at=request["requested_at"])

    with mock.patch.object(mac_media.time, "sleep", side_effect=complete) as sleep:
        assert mac_media.fetch_mac_artist_videos("rihanna") == []
    assert sleep.call_count == 1


def test_total_wait_budget_is_enforced(monkeypatch, tmp_path):
    heartbeat(tmp_path)
    monkeypatch.setattr(mac_media, "_wait_spent", 120.0)
    assert mac_media.fetch_mac_artist_videos("rihanna") == []
    assert not (tmp_path / "requests").exists()


def test_individual_wait_expires(monkeypatch, tmp_path):
    heartbeat(tmp_path)
    monkeypatch.setenv("MAC_MEDIA_WAIT_SECONDS", "2")
    with mock.patch.object(mac_media.time, "monotonic", side_effect=[0, 0, 1, 3, 3]), mock.patch.object(
        mac_media.time, "sleep"
    ):
        assert mac_media.fetch_mac_artist_videos("rihanna") == []
    assert mac_media._wait_spent == 3


def test_worker_rejects_path_injection():
    with pytest.raises(ValueError):
        mac_media_worker.process_request({"artist": "rihanna", "key": "../../escape"}, mock.Mock())


def test_worker_uses_editorial_query_and_never_publishes_a_post(monkeypatch):
    download = mock.Mock(return_value=[mock.sentinel.video])
    monkeypatch.setattr(mac_media_worker, "fetch_youtube_artist_videos", download)
    transport = mock.Mock()
    request = {"artist": "rihanna", "key": mac_media.artist_key("rihanna"), "requested_at": stamp()}
    assert mac_media_worker.process_request(request, transport)
    assert download.call_args.kwargs["search_query"] == "rihanna red carpet interview"
    transport.publish.assert_called_once_with("rihanna", [mock.sentinel.video], requested_at=request["requested_at"])


def test_cookie_export_excludes_every_other_site(monkeypatch, tmp_path):
    cookies = YoutubeDLCookieJar()
    for domain in (".youtube.com", ".google.com", ".example.com", ".fake-youtube.com"):
        cookies.set_cookie(Cookie(
            0, "test", "dummy-value", None, False, domain, True, True,
            "/", True, True, int(datetime.now().timestamp()) + 3600, False, None, None, {},
        ))
    monkeypatch.setattr(export_youtube_cookies, "extract_cookies_from_browser", lambda *a, **k: cookies)
    output = tmp_path / "youtube_cookies.txt"
    assert export_youtube_cookies.export_youtube_cookies(output) == 1
    exported = YoutubeDLCookieJar(str(output))
    exported.load()
    assert {cookie.domain for cookie in exported} == {".youtube.com"}
    assert output.stat().st_mode & 0o777 == 0o600
