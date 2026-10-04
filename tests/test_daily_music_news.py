from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from scripts import run_daily_music_news as daily
from src.analytics.scorer import _topic_labels
from src.editorial.music_filter import find_music_act_query, is_music_news
from src.models import NewsItem
from src.publisher.youtube import YouTubePublisher
from src.scraper.music_daily import _article_schema, clean_title
from src.storage import Store
from src.video.horizontal_news import plan_shots, subtitle_cues
from bs4 import BeautifulSoup


def item(title="Anitta chora ao falar da filha", url="https://example.com/one", stamp="2026-10-04T02:00:00+00:00"):
    return NewsItem(source_id="test", source_name="Test", category="celebridades", url=url,
                    title=title, published_at=datetime.fromisoformat(stamp.replace("Z", "+00:00")))


def remote(video_id, *, privacy="private", edition="2026-10-04", published="2026-10-04T18:00:00Z"):
    return {"id": video_id, "snippet": {"title": "Radar Musical", "description": daily.marker(edition), "publishedAt": published},
            "status": {"privacyStatus": privacy, "uploadStatus": "processed"}, "processingDetails": {"processingStatus": "succeeded"}}


def test_brt_slot_ignores_windows_host_timezone():
    assert not daily.scheduled_due(datetime(2026, 10, 4, 17, 59, tzinfo=timezone.utc))
    assert daily.scheduled_due(datetime(2026, 10, 4, 18, 0, tzinfo=timezone.utc))
    assert daily.scheduled_due(datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc))
    assert not daily.scheduled_due(datetime(2026, 10, 5, 2, 0, tzinfo=timezone.utc))


def test_daily_keeps_short_seen_and_dedupes_daily_and_yesterday(tmp_path):
    store = Store(tmp_path / "state.db")
    one = item()
    store.mark_seen(one.fingerprint(), "test", one.url, one.title, one.content_hash())
    assert daily.candidates_for_day([one], "2026-10-04", store, set()) == [one]
    store.record_publication(one.fingerprint(), daily.PLATFORM, "video", "ok", content_hash=one.content_hash())
    assert not daily.candidates_for_day([one], "2026-10-04", store, set())
    old = item(url="https://example.com/old", stamp="2026-10-02T01:00:00Z")
    assert not daily.candidates_for_day([old], "2026-10-04", store, set())


def test_remote_election_public_first_then_earliest_private():
    later = remote("later", published="2026-10-04T18:02:00Z")
    first = remote("first")
    public = remote("already-public", privacy="public", published="2026-10-04T18:03:00Z")
    assert daily.edition_upload([later, first], "2026-10-04")["id"] == "first"
    assert daily.edition_upload([later, first, public], "2026-10-04")["id"] == "already-public"
    assert daily.edition_upload([remote("yesterday", edition="2026-10-03")], "2026-10-04") is None


def test_staged_video_resumes_without_second_insert(tmp_path):
    service = Mock()
    staged, public = remote("pending"), remote("pending", privacy="public")
    service.videos.return_value.list.return_value.execute.return_value = {"items": [staged]}
    with patch.object(daily, "recent_uploads", side_effect=[[staged], [staged], [public]]):
        assert daily.publish_verified(service, None, None, "2026-10-04", tmp_path / "upload.json") == "pending"
    service.videos.return_value.insert.assert_not_called()
    service.videos.return_value.update.assert_called_once()


def test_unknown_upload_never_blindly_inserts_again(tmp_path):
    state = tmp_path / "upload.json"
    state.write_text(json.dumps({"upload_started": True}))
    service = Mock()
    with patch.object(daily, "recent_uploads", return_value=[]), patch.object(daily, "MediaFileUpload"):
        with pytest.raises(RuntimeError, match="unknown"):
            daily.publish_verified(service, tmp_path / "video.mp4", {}, "2026-10-04", state)
    service.videos.return_value.insert.return_value.next_chunk.assert_not_called()


def test_wrong_channel_stops_before_render_or_upload():
    service = Mock()
    service.channels.return_value.list.return_value.execute.return_value = {"items": [{"id": "wrong"}]}
    with pytest.raises(RuntimeError, match="wrong"):
        daily.recent_uploads(service)
    service.videos.assert_not_called()


def test_shot_plan_has_two_sources_and_never_repeats_ranges():
    assets = [{"source_page": source, "reviewed_ranges": [[0, 20], [30, 50]]} for source in ("one", "two")]
    shots = plan_shots(assets, 70)
    assert sum(s["duration"] for s in shots) == 70
    assert {s["asset"]["source_page"] for s in shots} == {"one", "two"}
    for source in ("one", "two"):
        ranges = [(s["source_start"], s["source_start"] + s["duration"]) for s in shots if s["asset"]["source_page"] == source]
        assert all(b <= c for (_, b), (c, _) in zip(ranges, ranges[1:]))
    with pytest.raises(RuntimeError, match="Not enough"):
        plan_shots(assets, 100)


def test_subtitles_use_real_character_timestamps():
    text = "Uma noticia real. Outra frase."
    data = {"characters": list(text), "character_start_times_seconds": [i * .1 for i in range(len(text))],
            "character_end_times_seconds": [(i + 1) * .1 for i in range(len(text))]}
    cues = subtitle_cues(data, 60)
    assert cues[0] == (60, 61.7, "Uma noticia real.")
    assert cues[1][0] == 61.8


def test_views_growth_history_excludes_long_and_preserves_format(tmp_path):
    store = Store(tmp_path / "state.db")
    for kind in ("short", "long"):
        store.record_youtube_growth_metrics(fingerprint=kind, video_id=kind, title="Anitta revela novidade",
            view_count=1000, subscribers_gained=5, content_format=kind)
    store.record_youtube_growth_metrics(fingerprint="long", video_id="long", view_count=1100, subscribers_gained=6)
    assert [r["fingerprint"] for r in store.analytics_examples(10)] == ["short"]


def test_album_review_not_conflict_and_family_is_a_learning_bucket():
    assert "public_conflict" not in _topic_labels("Critica do novo album de Pabllo Vittar")
    assert "family_reveal" in _topic_labels("Lucas Lima revela video raro do filho com Sandy")
    assert is_music_news(item("Phil Collins revela que a filha atriz temeu sua morte durante alcoolismo"))
    assert not is_music_news(item("Ney Matogrosso fala sobre filme nos cinemas"))
    assert find_music_act_query("Maestro Roberto Tibirica morre aos 72 anos") == "roberto tibirica"


def test_oauth_refresh_preserves_analytics_grants(tmp_path):
    token = tmp_path / "token.json"
    token.write_text("{}")
    credentials = Mock(valid=False, expired=True, refresh_token="dummy")
    credentials.to_json.return_value = '{"scopes":["youtube.upload","yt-analytics.readonly"]}'
    with patch("src.publisher.youtube.settings", SimpleNamespace(youtube_token_file=token)), \
         patch("src.publisher.youtube.Credentials.from_authorized_user_file", return_value=credentials) as load, \
         patch("src.publisher.youtube.Request"), patch("src.publisher.youtube.build"):
        YouTubePublisher()._service()
    load.assert_called_once_with(str(token))
    assert "yt-analytics.readonly" in token.read_text()


def test_primary_article_metadata_parsed_structurally():
    soup = BeautifulSoup('<script type="application/ld+json">{"@graph":[{"@type":"WebPage"},{"@type":"NewsArticle","datePublished":"2026-10-04T10:00:00Z"}]}</script>', "html.parser")
    assert _article_schema(soup)["datePublished"] == "2026-10-04T10:00:00Z"


def test_duplicate_rss_headline_is_not_narrated_twice():
    assert clean_title("MC Cabelinho revela novidade MC Cabelinho revela novidade") == "MC Cabelinho revela novidade"
