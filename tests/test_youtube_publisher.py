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


class _VideosResource:
    def __init__(self) -> None:
        self.body: dict[str, object] | None = None

    def insert(self, **kwargs: object) -> _UploadRequest:
        self.body = kwargs["body"]  # type: ignore[assignment]
        return _UploadRequest()


class _Service:
    def __init__(self) -> None:
        self.resource = _VideosResource()

    def videos(self) -> _VideosResource:
        return self.resource


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


if __name__ == "__main__":
    unittest.main()
