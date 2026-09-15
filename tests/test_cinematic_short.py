from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx
from PIL import Image

from src.video.commons_media import LicensedImage, _candidate, fetch_licensed_artist_images
from src.video.commons_video import LicensedVideo, fetch_licensed_artist_videos
from src.video.generator import (
    HEIGHT,
    WIDTH,
    _make_scene,
    _make_video_overlay,
    resolve_visual_media,
    visual_media_ready,
)


def commons_page(license_name: str) -> dict[str, object]:
    return {
        "title": "File:Shakira performing live.jpg",
        "imageinfo": [
            {
                "mime": "image/jpeg",
                "width": 1800,
                "height": 2400,
                "thumbwidth": 1200,
                "thumbheight": 1600,
                "url": "https://upload.wikimedia.org/example.jpg",
                "thumburl": "https://upload.wikimedia.org/thumb/example.jpg",
                "descriptionurl": "https://commons.wikimedia.org/wiki/File:Shakira_performing_live.jpg",
                "extmetadata": {
                    "LicenseShortName": {"value": license_name},
                    "LicenseUrl": {"value": "https://creativecommons.org/licenses/by/2.0"},
                    "Artist": {"value": "Example Photographer"},
                    "ImageDescription": {"value": "Shakira performing live"},
                },
            }
        ],
    }


class CommonsMediaTests(unittest.TestCase):
    def test_accepts_attribution_license_and_matching_identity(self) -> None:
        result = _candidate(commons_page("CC BY 2.0"), "shakira")
        self.assertIsNotNone(result)
        self.assertEqual(result["creator"], "Example Photographer")

    def test_rejects_share_alike_for_automatic_channel_video(self) -> None:
        self.assertIsNone(_candidate(commons_page("CC BY-SA 4.0"), "shakira"))

    def test_rejects_wrong_identity(self) -> None:
        self.assertIsNone(_candidate(commons_page("CC BY 2.0"), "anitta"))

    def test_rejects_another_artist_at_named_event(self) -> None:
        page = commons_page("CC BY 2.0")
        page["title"] = "File:Opening Act - 20 Years of Shakira.jpg"
        self.assertIsNone(_candidate(page, "shakira"))

    def test_rejects_signature_even_when_title_has_punctuation(self) -> None:
        page = commons_page("CC BY 2.0")
        page["title"] = "File:Shakira signature, Billboard letter.png"
        self.assertIsNone(_candidate(page, "shakira"))

    def test_retries_transient_api_rejection(self) -> None:
        class Client:
            def __init__(self) -> None:
                self.calls = 0

            def get(self, url: str, **kwargs: object) -> httpx.Response:
                self.calls += 1
                request = httpx.Request("GET", url)
                if self.calls == 1:
                    return httpx.Response(403, request=request)
                return httpx.Response(200, request=request, json={"query": {"pages": []}})

        client = Client()
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch(
            "src.video.commons_media.time.sleep"
        ):
            assets = fetch_licensed_artist_images(
                "shakira",
                Path(temp_dir),
                client=client,  # type: ignore[arg-type]
            )
        self.assertEqual(assets, [])
        self.assertEqual(client.calls, 2)


class SceneRenderTests(unittest.TestCase):
    def test_visual_lookup_requires_artist_in_headline(self) -> None:
        news = type(
            "Item",
            (),
            {
                "title": "Shows ao vivo: programação e ingressos",
                "summary": "A programação inclui Calvin Harris neste fim de semana.",
                "fingerprint": lambda self: "https://example.com/festival",
            },
        )()
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch(
            "src.video.generator.fetch_licensed_artist_images", return_value=[]
        ) as fetch_photos, mock.patch(
            "src.video.generator.fetch_licensed_artist_videos", return_value=[]
        ) as fetch_videos:
            artist, photos, videos = resolve_visual_media(news, Path(temp_dir))  # type: ignore[arg-type]

        self.assertIsNone(artist)
        self.assertEqual(photos, [])
        self.assertEqual(videos, [])
        fetch_photos.assert_called_once()
        fetch_videos.assert_called_once()
        self.assertIsNone(fetch_photos.call_args.args[0])
        self.assertIsNone(fetch_videos.call_args.args[0])

    def test_reference_style_requires_multiple_verified_visuals(self) -> None:
        news = type(
            "Item",
            (),
            {"title": "Shakira anuncia novidade", "summary": ""},
        )()
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch(
            "src.video.generator.resolve_visual_media",
            return_value=(
                "shakira",
                [mock.sentinel.photo] * 3,
                [mock.sentinel.video] * 2,
            ),
        ):
            self.assertTrue(visual_media_ready(news, Path(temp_dir)))  # type: ignore[arg-type]

        with tempfile.TemporaryDirectory() as temp_dir, mock.patch(
            "src.video.generator.resolve_visual_media",
            return_value=(None, [], []),
        ):
            self.assertFalse(visual_media_ready(news, Path(temp_dir)))  # type: ignore[arg-type]

    def test_reference_style_rejects_photo_only_candidate(self) -> None:
        news = type(
            "Item",
            (),
            {"title": "Shakira anuncia novidade", "summary": ""},
        )()
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch(
            "src.video.generator.resolve_visual_media",
            return_value=("shakira", [mock.sentinel.photo] * 6, []),
        ):
            self.assertFalse(visual_media_ready(news, Path(temp_dir)))  # type: ignore[arg-type]

    def test_scene_is_vertical_and_contains_safe_editorial_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            photo = root / "photo.jpg"
            Image.new("RGB", (1200, 1600), (42, 96, 140)).save(photo)
            media = LicensedImage(
                path=str(photo),
                title="Shakira live.jpg",
                creator="Example Photographer",
                license="CC BY 2.0",
                license_url="https://creativecommons.org/licenses/by/2.0",
                source_page="https://commons.wikimedia.org/example",
                source_url="https://upload.wikimedia.org/example.jpg",
                width=1200,
                height=1600,
            )
            output = root / "scene.jpg"

            _make_scene(
                index=4,
                count=5,
                headline="Cantora quebra o silêncio",
                subtitle="A artista falou sobre o caso nesta sexta-feira.",
                source_name="Fonte Teste",
                media=media,
                cutout=None,
                credits="FOTOS: Example Photographer / CC BY",
                output=output,
            )

            with Image.open(output) as rendered:
                self.assertEqual(rendered.size, (WIDTH, HEIGHT))

    def test_video_overlay_is_vertical_and_keeps_video_window_transparent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "overlay.png"
            _make_video_overlay(
                index=1,
                count=5,
                headline="Lady Gaga vira mãe",
                subtitle="A cantora não confirmou publicamente a informação.",
                source_name="G1",
                credits="VÍDEO: SMP ENTERTAINMENT / CC BY 3.0",
                output=output,
            )

            with Image.open(output) as rendered:
                self.assertEqual(rendered.size, (WIDTH, HEIGHT))
                self.assertEqual(rendered.mode, "RGBA")
                self.assertEqual(rendered.getpixel((WIDTH // 2, 900))[3], 0)


class CommonsVideoTests(unittest.TestCase):
    def test_unknown_artist_is_not_downloaded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            assets = fetch_licensed_artist_videos("artista desconhecido", Path(temp_dir))
            manifest = (Path(temp_dir) / "rights_manifest.json").read_text()
        self.assertEqual(assets, [])
        self.assertIn('"status": "no_curated_video"', manifest)

    def test_reuses_verified_cached_video(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "artist-video-01.webm"
            path.write_bytes(b"x" * 100_001)
            asset = LicensedVideo(
                path=str(path),
                title="Cached.webm",
                creator="Example",
                license="CC BY 3.0",
                license_url="https://creativecommons.org/licenses/by/3.0/",
                source_page="https://commons.wikimedia.org/example",
                source_url="https://upload.wikimedia.org/example.webm",
                width=1280,
                height=720,
                duration=30.0,
                seek_seconds=2.0,
                sha256="abc",
            )
            from src.video import commons_video

            commons_video._write_manifest(root / "rights_manifest.json", "lady gaga", "verified", [asset])
            assets = fetch_licensed_artist_videos("lady gaga", root, limit=1)

        self.assertEqual(assets, [asset])


if __name__ == "__main__":
    unittest.main()
