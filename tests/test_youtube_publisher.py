from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from src.models import GeneratedAssets, RewrittenPost
from src.publisher.youtube import YouTubePublisher
from src.shorts_quota import TARGET_ENV


class _UploadRequest:
    def next_chunk(self) -> tuple[None, dict[str, str]]:
        return None, {"id": "video-123"}


class _ExecuteRequest:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response

    def execute(self) -> dict[str, object]:
        return self.response


class _VideosResource:
    def __init__(self, listed: list[dict[str, object]] | None = None) -> None:
        self.body: dict[str, object] | None = None
        self.listed = listed or []

    def insert(self, **kwargs: object) -> _UploadRequest:
        self.body = kwargs["body"]  # type: ignore[assignment]
        return _UploadRequest()

    def list(self, **kwargs: object) -> _ExecuteRequest:
        return _ExecuteRequest({"items": self.listed})


class _Service:
    def __init__(
        self,
        uploads: list[dict[str, object]] | None = None,
        listed: list[dict[str, object]] | None = None,
    ) -> None:
        self.resource = _VideosResource(listed)
        self.uploads = uploads or []

    def videos(self) -> _VideosResource:
        return self.resource

    def channels(self):
        resource = mock.Mock()
        resource.list.return_value = _ExecuteRequest(
            {
                "items": [
                    {
                        "id": "UC-TFUUc4YHleNoIFXBVaj7A",
                        "contentDetails": {
                            "relatedPlaylists": {"uploads": "uploads-playlist"}
                        }
                    }
                ]
            }
        )
        return resource

    def playlistItems(self):
        resource = mock.Mock()
        resource.list.return_value = _ExecuteRequest({"items": self.uploads})
        return resource


def _shorts_published_now(*sources: str) -> _Service:
    """A channel whose only uploads are public Shorts of other articles, made just now."""
    published = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    snippets = [
        {
            "title": f"Noticia {index} #Shorts",
            "description": f"Fonte: {source}",
            "publishedAt": published,
            "resourceId": {"videoId": f"video-{index}"},
        }
        for index, source in enumerate(sources)
    ]
    return _Service(
        uploads=[{"snippet": snippet} for snippet in snippets],
        listed=[
            {
                "id": snippet["resourceId"]["videoId"],
                "snippet": snippet,
                "status": {"privacyStatus": "public", "uploadStatus": "processed"},
            }
            for snippet in snippets
        ],
    )


class YouTubePublisherTests(unittest.TestCase):
    def _publish_with_target(self, service: _Service, target: int):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "short.mp4"
            video.write_bytes(b"video")
            assets = GeneratedAssets(video_path=str(video), duration_seconds=25.0)
            post = RewrittenPost(
                source_url="https://example.com/third-story",
                headline="Terceira noticia do dia",
                short_caption="Resumo",
                long_caption="Texto",
                script_voiceover="Narracao",
                hashtags=["Musica"],
            )
            publisher = YouTubePublisher()
            env = {
                TARGET_ENV: str(target),
                "TIMEZONE": "America/Sao_Paulo",
                "YOUTUBE_EXPECTED_CHANNEL_ID": "UC-TFUUc4YHleNoIFXBVaj7A",
            }
            with mock.patch.dict("os.environ", env), mock.patch.object(
                publisher, "_service", return_value=service
            ):
                return publisher.publish(post, assets)

    def test_slot_filled_during_render_blocks_the_upload(self) -> None:
        # 2026-11-01 19:13: the server and the Mac rendered different articles for the
        # third slot; only a count right before upload stops the second one.
        service = _shorts_published_now(
            "https://example.com/first", "https://example.com/second", "https://example.com/third"
        )
        result = self._publish_with_target(service, target=3)

        self.assertFalse(result.ok)
        self.assertTrue(result.slot_filled)
        self.assertIsNone(result.remote_id)
        self.assertIsNone(service.resource.body)

    def test_open_slot_still_uploads(self) -> None:
        service = _shorts_published_now("https://example.com/first", "https://example.com/second")
        result = self._publish_with_target(service, target=3)

        self.assertTrue(result.ok)
        self.assertFalse(result.slot_filled)
        self.assertEqual(result.remote_id, "video-123")
        self.assertIsNotNone(service.resource.body)

    def test_description_includes_generated_media_credits(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "short.mp4"
            video.write_bytes(b"video")
            (root / "media_credits.txt").write_text(
                "CRÉDITOS DE MÍDIA\nVídeo: Example\nLicença: CC BY 3.0\n",
                encoding="utf-8",
            )
            assets = GeneratedAssets(video_path=str(video), duration_seconds=25.0)
            post = RewrittenPost(
                source_url="https://example.com/news",
                headline="Notícia da música",
                short_caption="Resumo",
                long_caption="Texto da notícia",
                script_voiceover="Narração",
                hashtags=["Musica"],
            )
            service = _Service()
            publisher = YouTubePublisher()
            with mock.patch.object(publisher, "_service", return_value=service):
                result = publisher.publish(post, assets)

        self.assertTrue(result.ok)
        snippet = service.resource.body["snippet"]  # type: ignore[index]
        description = snippet["description"]  # type: ignore[index]
        self.assertIn("CRÉDITOS DE MÍDIA", description)
        self.assertIn("Licença: CC BY 3.0", description)
        self.assertIn("Fonte: https://example.com/news", description)

    def test_remote_source_url_dedupe_blocks_second_upload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "short.mp4"
            video.write_bytes(b"video")
            assets = GeneratedAssets(video_path=str(video), duration_seconds=25.0)
            post = RewrittenPost(
                source_url="https://example.com/news",
                headline="Outra manchete para a mesma noticia",
                short_caption="Resumo",
                long_caption="Texto reescrito",
                script_voiceover="Narracao",
                hashtags=["Musica"],
            )
            service = _Service(
                uploads=[
                    {
                        "snippet": {
                            "title": "Primeira versao #Shorts",
                            "description": (
                                "Fonte: Portal\n\n"
                                "Fonte: http://www.example.com/news/?utm_source=rss"
                            ),
                            "resourceId": {"videoId": "existing-video"},
                        }
                    }
                ]
            )
            publisher = YouTubePublisher()
            with mock.patch.object(publisher, "_service", return_value=service):
                result = publisher.publish(post, assets)

        self.assertTrue(result.ok)
        self.assertEqual(result.remote_id, "existing-video")
        self.assertEqual(result.url, "https://youtube.com/shorts/existing-video")
        self.assertIsNone(service.resource.body)


if __name__ == "__main__":
    unittest.main()
