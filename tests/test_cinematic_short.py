from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx
from PIL import Image

from src.models import NewsItem
from src.video.commons_media import LicensedImage, _candidate, fetch_licensed_artist_images
from src.video.commons_video import LicensedVideo, fetch_licensed_artist_videos
from src.video.generator import (
    HEIGHT,
    WIDTH,
    _make_hook_scene,
    _make_scene,
    _make_video_overlay,
    resolve_visual_media,
    video_media_ready,
    visual_media_ready,
)
from src.video.source_media import (
    SOURCE_ARTICLE_LICENSE,
    fetch_source_article_image,
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

    def test_accepts_smaller_photo_after_threshold_relaxation(self) -> None:
        page = commons_page("CC BY 2.0")
        page["imageinfo"][0]["thumbwidth"] = 500
        page["imageinfo"][0]["thumbheight"] = 900
        self.assertIsNotNone(_candidate(page, "shakira"))

    def test_rejects_photo_below_minimum_short_side(self) -> None:
        page = commons_page("CC BY 2.0")
        page["imageinfo"][0]["thumbwidth"] = 300
        page["imageinfo"][0]["thumbheight"] = 900
        self.assertIsNone(_candidate(page, "shakira"))

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


class SourceArticleMediaTests(unittest.TestCase):
    def test_downloads_rss_or_open_graph_image_with_unverified_rights(self) -> None:
        payload = io.BytesIO()
        Image.new("RGB", (1200, 800), (30, 80, 140)).save(payload, format="JPEG")
        item = type(
            "Item",
            (),
            {
                "image_url": "https://cdn.example.com/story.jpg",
                "url": "https://example.com/story",
                "title": "Artista anuncia novidade",
                "source_name": "Fonte Teste",
            },
        )()

        class Client:
            def get(self, url: str, **kwargs: object) -> httpx.Response:
                return httpx.Response(
                    200,
                    request=httpx.Request("GET", url),
                    content=payload.getvalue(),
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            asset = fetch_source_article_image(  # type: ignore[arg-type]
                item, Path(temp_dir), client=Client()  # type: ignore[arg-type]
            )

            self.assertIsNotNone(asset)
            assert asset is not None
            self.assertTrue(Path(asset.path).exists())
            self.assertEqual(asset.license, SOURCE_ARTICLE_LICENSE)
            self.assertEqual((asset.width, asset.height), (1200, 800))

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
    def test_first_frame_is_a_curiosity_collage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            assets = []
            for index, color in enumerate(((40, 110, 170), (190, 70, 90))):
                path = root / f"photo-{index}.jpg"
                Image.new("RGB", (1200, 1600), color).save(path)
                assets.append(
                    LicensedImage(
                        path=str(path),
                        title=f"Shakira {index}.jpg",
                        creator="Example Photographer",
                        license="CC BY 2.0",
                        license_url="https://creativecommons.org/licenses/by/2.0",
                        source_page="https://commons.wikimedia.org/example",
                        source_url=f"https://upload.wikimedia.org/example-{index}.jpg",
                        width=1200,
                        height=1600,
                    )
                )
            output = root / "hook.jpg"
            news = type(
                "Item",
                (),
                {"title": "Shakira quebra o silêncio", "source_name": "Fonte Teste"},
            )()

            _make_hook_scene(
                item=news,  # type: ignore[arg-type]
                media=assets,
                credits="FOTOS: Example Photographer / CC BY",
                output=output,
            )

            with Image.open(output) as rendered:
                self.assertEqual(rendered.size, (WIDTH, HEIGHT))
                self.assertNotEqual(rendered.getpixel((280, 850)), rendered.getpixel((800, 850)))

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

    def test_visual_lookup_falls_back_to_source_article_image(self) -> None:
        news = NewsItem(
            source_id="source",
            source_name="Fonte Teste",
            category="music",
            url="https://example.com/story",
            title="Artista anuncia novidade",
            image_url="https://cdn.example.com/story.jpg",
        )
        source_photo = mock.sentinel.source_photo
        media_settings = mock.Mock(
            min_visual_media_assets=1,
            min_video_media_assets=0,
            allow_source_article_image=True,
        )
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch(
            "src.video.generator.fetch_licensed_artist_images", return_value=[]
        ), mock.patch(
            "src.video.generator.fetch_source_article_image",
            return_value=source_photo,
        ) as fetch_source, mock.patch(
            "src.video.generator.fetch_licensed_artist_videos", return_value=[]
        ), mock.patch("src.video.generator.settings", media_settings):
            _, photos, videos = resolve_visual_media(news, Path(temp_dir))

        self.assertEqual(photos, [source_photo])
        self.assertEqual(videos, [])
        fetch_source.assert_called_once()

    def test_visual_lookup_uses_headline_subject_not_later_relative(self) -> None:
        news = NewsItem(
            source_id="source",
            source_name="TV Foco",
            category="music",
            url="https://example.com/fiuk",
            title="Fiuk encerra carreira como cantor; briga com Fábio Jr",
            image_url="https://cdn.example.com/fiuk.jpg",
        )
        media_settings = mock.Mock(
            min_visual_media_assets=1,
            min_video_media_assets=0,
            allow_source_article_image=True,
        )
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch(
            "src.video.generator.fetch_licensed_artist_images", return_value=[]
        ) as fetch_photos, mock.patch(
            "src.video.generator.fetch_source_article_image",
            return_value=mock.sentinel.source_photo,
        ), mock.patch(
            "src.video.generator.fetch_licensed_artist_videos", return_value=[]
        ) as fetch_videos, mock.patch(
            "src.video.generator.settings", media_settings
        ):
            artist, _, _ = resolve_visual_media(news, Path(temp_dir))

        self.assertEqual(artist, "fiuk")
        self.assertEqual(fetch_photos.call_args.args[0], "fiuk")
        self.assertEqual(fetch_videos.call_args.args[0], "fiuk")

    def test_reference_style_requires_multiple_verified_visuals(self) -> None:
        news = type(
            "Item",
            (),
            {"title": "Shakira anuncia novidade", "summary": ""},
        )()
        strict_settings = mock.Mock(
            require_visual_media=True,
            min_visual_media_assets=3,
            require_video_media=True,
            min_video_media_assets=2,
        )
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch(
            "src.video.generator.resolve_visual_media",
            return_value=(
                "shakira",
                [mock.sentinel.photo] * 3,
                [mock.sentinel.video] * 2,
            ),
        ), mock.patch("src.video.generator.settings", strict_settings):
            self.assertTrue(visual_media_ready(news, Path(temp_dir)))  # type: ignore[arg-type]

        with tempfile.TemporaryDirectory() as temp_dir, mock.patch(
            "src.video.generator.resolve_visual_media",
            return_value=(None, [], []),
        ), mock.patch("src.video.generator.settings", strict_settings):
            self.assertFalse(visual_media_ready(news, Path(temp_dir)))  # type: ignore[arg-type]

    def test_reference_style_rejects_photo_only_candidate(self) -> None:
        news = type(
            "Item",
            (),
            {"title": "Shakira anuncia novidade", "summary": ""},
        )()
        strict_settings = mock.Mock(
            require_visual_media=True,
            min_visual_media_assets=3,
            require_video_media=True,
            min_video_media_assets=2,
        )
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch(
            "src.video.generator.resolve_visual_media",
            return_value=("shakira", [mock.sentinel.photo] * 6, []),
        ), mock.patch("src.video.generator.settings", strict_settings):
            self.assertFalse(visual_media_ready(news, Path(temp_dir)))  # type: ignore[arg-type]

    def test_default_photo_gate_accepts_photo_without_video(self) -> None:
        news = type(
            "Item",
            (),
            {"title": "Shakira anuncia novidade", "summary": ""},
        )()
        photo_first_settings = mock.Mock(
            require_visual_media=True,
            min_visual_media_assets=1,
            require_video_media=False,
            min_video_media_assets=0,
        )
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch(
            "src.video.generator.resolve_visual_media",
            return_value=("shakira", [mock.sentinel.photo], []),
        ), mock.patch("src.video.generator.settings", photo_first_settings):
            self.assertTrue(visual_media_ready(news, Path(temp_dir)))  # type: ignore[arg-type]

    def test_video_priority_requires_both_photo_and_video(self) -> None:
        news = type(
            "Item",
            (),
            {"title": "Shakira anuncia novidade", "summary": ""},
        )()
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch(
            "src.video.generator.resolve_visual_media",
            return_value=(
                "shakira",
                [mock.sentinel.photo],
                [mock.sentinel.video],
            ),
        ):
            self.assertTrue(video_media_ready(news, Path(temp_dir)))  # type: ignore[arg-type]

        with tempfile.TemporaryDirectory() as temp_dir, mock.patch(
            "src.video.generator.resolve_visual_media",
            return_value=("shakira", [mock.sentinel.photo], []),
        ):
            self.assertFalse(video_media_ready(news, Path(temp_dir)))  # type: ignore[arg-type]

    def test_classic_fallback_accepts_candidate_without_visual_media(self) -> None:
        news = type(
            "Item",
            (),
            {"title": "Shakira anuncia novidade", "summary": ""},
        )()
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch(
            "src.video.generator.resolve_visual_media"
        ) as resolve:
            self.assertTrue(
                visual_media_ready(
                    news,  # type: ignore[arg-type]
                    Path(temp_dir),
                    enforce_requirements=False,
                )
            )
        resolve.assert_not_called()

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
