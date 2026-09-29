from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.models import GeneratedAssets, RewrittenPost
from src.publisher.youtube import YouTubePublisher


class _UploadRequest:
    def next_chunk(self) -> tuple[None, dict[str, str]]:
        return None, {"id": "video-123"}


class _ExecuteRequest:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response

    def execute(self) -> dict[str, object]:
        return self.response


class _VideosResource:
    def __init__(self) -> None:
        self.body: dict[str, object] | None = None

    def insert(self, **kwargs: object) -> _UploadRequest:
        self.body = kwargs["body"]  # type: ignore[assignment]
        return _UploadRequest()


class _Service:
    def __init__(self, uploads: list[dict[str, object]] | None = None) -> None:
        self.resource = _VideosResource()
        self.uploads = uploads or []

    def videos(self) -> _VideosResource:
        return self.resource

    def channels(self):
        resource = mock.Mock()
        resource.list.return_value = _ExecuteRequest(
            {
                "items": [
                    {
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


class YouTubePublisherTests(unittest.TestCase):
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
