from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from src.suno.playlist import SunoTrack, parse_playlist_html
from src.suno.state import SunoState, next_unpublished_track
from src.suno.video import _audio_destination, _is_encrypted_suno_audio
from src.suno.youtube import video_body, video_description


PLAYLIST_URL = "https://suno.com/playlist/344579d1-5a04-45f8-aa71-a48f9da326a3"


def track(song_id: str, title: str) -> SunoTrack:
    return SunoTrack(
        song_id=song_id,
        title=title,
        audio_url=f"https://cdn1.suno.ai/{song_id}.mp3",
        image_url=f"https://cdn2.suno.ai/image_{song_id}.jpeg",
        duration_seconds=210.0,
        description="Warm vintage soul and funk.",
        created_at=datetime(2026, 8, 4, 16, 0, tzinfo=timezone.utc),
    )


class SunoAutopostTests(unittest.TestCase):
    def test_parser_extracts_complete_tracks_in_playlist_order(self) -> None:
        first = track("dec05dfb-0505-4236-9e8b-07a4b38eab81", "Log Out, Come Alive")
        second = track("a1dbc14c-999c-418f-9f63-a15a331395e7", "Dance It Back to Life")
        playlist = {
            "playlist": {
                "id": "playlist-id",
                "playlist_clips": [
                    {"clip": {
                        "id": first.song_id,
                        "status": "complete",
                        "title": first.title,
                        "audio_url": first.audio_url,
                        "image_large_url": first.image_url,
                        "created_at": "2026-08-04T16:00:00Z",
                        "metadata": {
                            "tags": first.description,
                            "duration": first.duration_seconds,
                        },
                    }},
                    {"clip": {
                        "id": second.song_id,
                        "status": "complete",
                        "title": second.title,
                        "audio_url": second.audio_url,
                        "image_url": second.image_url,
                        "duration": second.duration_seconds,
                        "metadata": {"tags": second.description},
                    }},
                ],
            }
        }
        rsc = "49:" + json.dumps(["$", "$L5b", None, playlist], separators=(",", ":"))
        html = "<script>self.__next_f.push(" + json.dumps([1, rsc]) + ")</script>"
        parsed = parse_playlist_html(html)
        self.assertEqual([item.song_id for item in parsed], [first.song_id, second.song_id])
        self.assertEqual(parsed[0].description, first.description)
        self.assertEqual(parsed[0].duration_seconds, first.duration_seconds)

    def test_parser_skips_translation_playlist_key_and_uses_media_url(self) -> None:
        playlist = {
            "playlist": {
                "id": "playlist-id",
                "playlist_clips": [{"clip": {
                    "id": "song-1",
                    "status": "complete",
                    "title": "Public Media",
                    "audio_url": "https://studio-api.prod.suno.com/api/forbidden",
                    "media_urls": [{
                        "url": "https://cdn.suno.ai/clip/song-1.m4a",
                        "content_type": "m4a-opus",
                    }, {
                        "url": "https://cdn.suno.ai/clip/song-1.mp3",
                        "content_type": "mp3",
                    }],
                }}],
            }
        }
        flight = (
            '1:{"translations":{"playlist":"Playlist"}}\\n'
            + "2:" + json.dumps(["$", "$L1", None, playlist], separators=(",", ":"))
        )
        html = "<script>self.__next_f.push(" + json.dumps([1, flight]) + ")</script>"

        parsed = parse_playlist_html(html)

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].audio_url, "https://cdn.suno.ai/clip/song-1.m4a")

    def test_renderer_keeps_suno_media_extension(self) -> None:
        m4a = SunoTrack(
            song_id="song-1",
            title="Media",
            audio_url="https://media.cloudfront.net/1/clip/song-1.m4a",
            image_url="",
            duration_seconds=1.0,
        )
        mp3 = track("song-2", "Legacy")
        self.assertEqual(_audio_destination(m4a, Path("out")), Path("out/track.m4a"))
        self.assertEqual(_audio_destination(mp3, Path("out")), Path("out/track.mp3"))
        self.assertTrue(_is_encrypted_suno_audio(m4a.audio_url))
        self.assertFalse(_is_encrypted_suno_audio(mp3.audio_url))

    def test_next_track_drains_existing_playlist_backlog_in_order(self) -> None:
        tracks = [
            track("dec05dfb-0505-4236-9e8b-07a4b38eab81", "First"),
            track("a1dbc14c-999c-418f-9f63-a15a331395e7", "Second"),
        ]
        selected = next_unpublished_track(tracks, {tracks[0].song_id})
        self.assertEqual(selected, tracks[1])

    def test_state_enforces_sao_paulo_calendar_day(self) -> None:
        with TemporaryDirectory() as tmpdir:
            state = SunoState(Path(tmpdir) / "state.db")
            state.record_success(
                song_id="dec05dfb-0505-4236-9e8b-07a4b38eab81",
                title="First",
                youtube_video_id="youtube-1",
                posted_at=datetime(2026, 8, 4, 2, 30, tzinfo=timezone.utc),
                timezone_name="America/Sao_Paulo",
            )
            self.assertTrue(
                state.has_success_today(
                    "America/Sao_Paulo",
                    now=datetime(2026, 8, 3, 23, 50, tzinfo=timezone.utc),
                )
            )
            self.assertFalse(
                state.has_success_today(
                    "America/Sao_Paulo",
                    now=datetime(2026, 8, 4, 3, 1, tzinfo=timezone.utc),
                )
            )

    def test_metadata_marks_ai_and_contains_remote_dedupe_receipt(self) -> None:
        item = track("1488e471-3ea6-400f-97c3-0eaa992a66dc", "Bad Luck Can't Drive Me")
        description = video_description(item, PLAYLIST_URL)
        self.assertIn(f"Suno track ID: {item.song_id}", description)
        body = video_body(item, PLAYLIST_URL, privacy_status="public")
        self.assertEqual(body["snippet"]["categoryId"], "10")
        self.assertTrue(body["status"]["containsSyntheticMedia"])
        self.assertFalse(body["status"]["selfDeclaredMadeForKids"])


if __name__ == "__main__":
    unittest.main()
