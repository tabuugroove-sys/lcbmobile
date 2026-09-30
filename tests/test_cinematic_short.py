from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx
from PIL import Image

from src.models import NewsItem, RewrittenPost
from src.video.commons_media import LicensedImage, _candidate, fetch_licensed_artist_images
from src.video.commons_video import LicensedVideo, fetch_licensed_artist_videos
from src.video.generator import (
    HEIGHT,
    WIDTH,
    build_short,
    _fit_cover,
    _make_hook_scene,
    _make_scene,
    _make_video_overlay,
    resolve_hook_media,
    resolve_visual_media,
    photo_media_ready,
    video_media_ready,
    visual_media_ready,
)
from src.video.source_media import (
    SOURCE_ARTICLE_LICENSE,
    fetch_source_article_image,
    fetch_source_article_images,
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

    def test_collects_distinct_article_images_and_skips_related_cards(self) -> None:
        def payload(color: tuple[int, int, int]) -> bytes:
            content = io.BytesIO()
            Image.new("RGB", (1200, 800), color).save(content, format="JPEG")
            return content.getvalue()

        html = """
        <html><head><meta property="og:image" content="https://cdn.example.com/hero.jpg"></head>
        <body><article><div class="entry-content">
          <figure><img src="https://cdn.example.com/context.jpg" alt="Público reage"></figure>
          <div class="leia-tambem"><img src="https://cdn.example.com/related.jpg"></div>
        </div></article></body></html>
        """
        item = NewsItem(
            source_id="source",
            source_name="Fonte Teste",
            category="music",
            url="https://example.com/story",
            title="Artista surpreende o público",
            image_url="https://cdn.example.com/hero.jpg",
        )

        class Client:
            def get(self, url: str, **kwargs: object) -> httpx.Response:
                request = httpx.Request("GET", url)
                if url == item.url:
                    return httpx.Response(200, request=request, text=html)
                colors = {
                    "https://cdn.example.com/hero.jpg": (25, 80, 160),
                    "https://cdn.example.com/context.jpg": (185, 60, 75),
                    "https://cdn.example.com/related.jpg": (40, 170, 90),
                }
                return httpx.Response(200, request=request, content=payload(colors[url]))

        with tempfile.TemporaryDirectory() as temp_dir:
            assets = fetch_source_article_images(
                item,
                Path(temp_dir),
                limit=4,
                client=Client(),  # type: ignore[arg-type]
            )

        self.assertEqual(len(assets), 2)
        self.assertEqual(assets[1].title, "Público reage")
        self.assertNotIn("related.jpg", [asset.source_url for asset in assets])

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

    def test_single_hook_photo_is_not_duplicated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            photo = root / "only.jpg"
            Image.new("RGB", (1200, 1600), (45, 115, 180)).save(photo)
            asset = LicensedImage(
                path=str(photo),
                title="Artista.jpg",
                creator="Example Photographer",
                license="CC BY 2.0",
                license_url="https://creativecommons.org/licenses/by/2.0",
                source_page="https://commons.wikimedia.org/example",
                source_url="https://upload.wikimedia.org/only.jpg",
                width=1200,
                height=1600,
            )
            output = root / "hook.jpg"
            news = type(
                "Item",
                (),
                {"title": "Artista revela mudança", "source_name": "Fonte Teste"},
            )()

            _make_hook_scene(
                item=news,  # type: ignore[arg-type]
                media=[asset, asset],
                credits="FOTO: Example Photographer / CC BY",
                output=output,
            )

            with Image.open(output) as rendered:
                self.assertNotEqual(
                    rendered.getpixel((280, 1050)),
                    rendered.getpixel((800, 1050)),
                )

    def test_hook_pair_uses_article_context_when_no_named_opponent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            def asset(name: str, color: tuple[int, int, int]) -> LicensedImage:
                path = root / name
                Image.new("RGB", (1200, 800), color).save(path)
                return LicensedImage(
                    path=str(path),
                    title=name,
                    creator="Fonte Teste",
                    license=SOURCE_ARTICLE_LICENSE,
                    license_url="https://example.com/story",
                    source_page="https://example.com/story",
                    source_url=f"https://cdn.example.com/{name}",
                    width=1200,
                    height=800,
                )

            hero = asset("hero.jpg", (40, 90, 170))
            context = asset("audience.jpg", (190, 65, 80))
            news = NewsItem(
                source_id="source",
                source_name="Fonte Teste",
                category="music",
                url="https://example.com/story",
                title="Cantor surpreende público durante show",
                image_url=hero.source_url,
            )
            with mock.patch(
                "src.video.generator.fetch_source_article_images",
                return_value=[hero, context],
            ):
                pair = resolve_hook_media(news, [hero], root / "hook")

        self.assertEqual([row.title for row in pair], ["hero.jpg", "audience.jpg"])

    def test_hook_pair_prefers_named_opponent_over_generic_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            def asset(name: str, color: tuple[int, int, int]) -> LicensedImage:
                path = root / name
                Image.new("RGB", (1200, 800), color).save(path)
                return LicensedImage(
                    path=str(path),
                    title=name,
                    creator="Example Photographer",
                    license="CC BY 2.0",
                    license_url="https://creativecommons.org/licenses/by/2.0",
                    source_page=f"https://commons.wikimedia.org/{name}",
                    source_url=f"https://upload.wikimedia.org/{name}",
                    width=1200,
                    height=800,
                )

            hero = asset("fiuk.jpg", (40, 90, 170))
            opponent = asset("fabio-jr.jpg", (190, 65, 80))
            context = asset("audience.jpg", (50, 160, 95))
            news = NewsItem(
                source_id="source",
                source_name="Fonte Teste",
                category="music",
                url="https://example.com/story",
                title="Fiuk responde a Fábio Jr após nova polêmica",
                summary="Os dois artistas falaram sobre o conflito.",
                image_url=hero.source_url,
            )
            with mock.patch(
                "src.video.generator.fetch_source_article_images",
                return_value=[hero, context],
            ), mock.patch(
                "src.video.generator.fetch_licensed_artist_images",
                return_value=[opponent],
            ) as fetch_secondary:
                pair = resolve_hook_media(news, [hero], root / "hook")

        self.assertEqual([row.title for row in pair], ["fiuk.jpg", "fabio-jr.jpg"])
        self.assertEqual(fetch_secondary.call_args.args[0], "fabio jr")

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
        ) as fetch_videos, mock.patch(
            "src.video.generator.fetch_source_article_images", return_value=[]
        ):
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
        media_settings = mock.Mock(
            min_visual_media_assets=1,
            min_video_media_assets=0,
            allow_source_article_image=True,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_photos = []
            for index, color in enumerate(((40, 90, 170), (190, 65, 80)), start=1):
                path = root / f"source-{index}.jpg"
                Image.new("RGB", (1200, 800), color).save(path)
                source_photos.append(
                    LicensedImage(
                        path=str(path),
                        title=path.name,
                        creator="Fonte Teste",
                        license=SOURCE_ARTICLE_LICENSE,
                        license_url=news.url,
                        source_page=news.url,
                        source_url=f"https://cdn.example.com/{path.name}",
                        width=1200,
                        height=800,
                    )
                )
            with mock.patch(
                "src.video.generator.fetch_licensed_artist_images", return_value=[]
            ), mock.patch(
                "src.video.generator.fetch_source_article_images",
                return_value=source_photos,
            ) as fetch_source, mock.patch(
                "src.video.generator.fetch_licensed_artist_videos", return_value=[]
            ), mock.patch("src.video.generator.settings", media_settings):
                _, photos, videos = resolve_visual_media(news, root)

        self.assertEqual(photos, source_photos)
        self.assertEqual(videos, [])
        fetch_source.assert_called_once()

    def test_visual_lookup_adds_distinct_images_from_related_articles(self) -> None:
        news = NewsItem(
            source_id="source",
            source_name="Fonte Teste",
            category="music",
            url="https://example.com/main",
            title="Cantor Rick vira tema de reportagem",
        )
        related = news.model_copy(
            update={
                "url": "https://example.com/related",
                "title": "Viúva de Rick presta homenagem",
            }
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            def asset(name: str, color: tuple[int, int, int], page: str) -> LicensedImage:
                path = root / name
                Image.new("RGB", (1200, 800), color).save(path)
                return LicensedImage(
                    path=str(path),
                    title=name,
                    creator="Fonte Teste",
                    license=SOURCE_ARTICLE_LICENSE,
                    license_url=page,
                    source_page=page,
                    source_url=f"https://cdn.example.com/{name}",
                    width=1200,
                    height=800,
                )

            hero = asset("hero.jpg", (35, 80, 160), news.url)
            context = asset("context.jpg", (190, 65, 85), related.url)

            def source_images(item, *_args, **_kwargs):
                return [hero] if item.url == news.url else [context]

            with mock.patch(
                "src.video.generator.fetch_licensed_artist_images",
                return_value=[],
            ), mock.patch(
                "src.video.generator.fetch_source_article_images",
                side_effect=source_images,
            ) as fetch_source, mock.patch(
                "src.video.generator.fetch_licensed_artist_videos",
                return_value=[],
            ), mock.patch(
                "src.video.generator.fetch_youtube_artist_videos",
                return_value=[],
            ):
                artist, photos, _ = resolve_visual_media(
                    news,
                    root,
                    related_items=[related],
                )

        self.assertEqual(artist, "rick e renner")
        self.assertEqual([photo.title for photo in photos], ["hero.jpg", "context.jpg"])
        self.assertEqual(fetch_source.call_count, 2)

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
            "src.video.generator.fetch_source_article_images",
            return_value=[],
        ), mock.patch(
            "src.video.generator.fetch_licensed_artist_videos", return_value=[]
        ) as fetch_videos, mock.patch(
            "src.video.generator.settings", media_settings
        ):
            artist, _, _ = resolve_visual_media(news, Path(temp_dir))

        self.assertEqual(artist, "fiuk")
        self.assertEqual(fetch_photos.call_args.args[0], "fiuk")
        self.assertEqual(fetch_videos.call_args.args[0], "fiuk")

    def test_cover_fit_fills_portrait_frame_and_respects_horizontal_focus(self) -> None:
        source = Image.new("RGB", (800, 450), "black")
        for x in range(800):
            color = (round(255 * x / 799), 20, 20)
            for y in range(450):
                source.putpixel((x, y), color)

        left = _fit_cover(source, (760, 1050), 0.34, 0.0)
        right = _fit_cover(source, (760, 1050), 0.34, 1.0)

        self.assertEqual(left.size, (760, 1050))
        self.assertEqual(right.size, (760, 1050))
        self.assertLess(left.getpixel((380, 525))[0], right.getpixel((380, 525))[0])

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
        mixed_settings = mock.Mock(
            require_visual_media=True,
            min_visual_media_assets=4,
            require_video_media=True,
            min_video_media_assets=1,
        )
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch(
            "src.video.generator.resolve_visual_media",
            return_value=(
                "shakira",
                [mock.sentinel.photo] * 4,
                [mock.sentinel.video],
            ),
        ), mock.patch("src.video.generator.settings", mixed_settings):
            self.assertTrue(video_media_ready(news, Path(temp_dir)))  # type: ignore[arg-type]

        with tempfile.TemporaryDirectory() as temp_dir, mock.patch(
            "src.video.generator.resolve_visual_media",
            return_value=("shakira", [mock.sentinel.photo] * 4, []),
        ), mock.patch("src.video.generator.settings", mixed_settings):
            self.assertFalse(video_media_ready(news, Path(temp_dir)))  # type: ignore[arg-type]

        with tempfile.TemporaryDirectory() as temp_dir, mock.patch(
            "src.video.generator.resolve_visual_media",
            return_value=(
                "shakira",
                [mock.sentinel.photo] * 3,
                [mock.sentinel.video],
            ),
        ), mock.patch("src.video.generator.settings", mixed_settings):
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

    def test_photo_fallback_accepts_one_usable_photo(self) -> None:
        news = type(
            "Item",
            (),
            {"title": "Cantor anuncia novidade", "summary": ""},
        )()
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch(
            "src.video.generator.resolve_visual_media",
            return_value=(None, [mock.sentinel.photo], []),
        ):
            self.assertTrue(photo_media_ready(news, Path(temp_dir)))  # type: ignore[arg-type]

    def test_single_photo_classic_render_keeps_photo_without_montage(self) -> None:
        news = NewsItem(
            source_id="source",
            source_name="Fonte Teste",
            category="music",
            url="https://example.com/story",
            title="Cantor anuncia novidade",
        )
        post = RewrittenPost(
            source_url=news.url,
            headline="Cantor anuncia novidade",
            short_caption="Novidade confirmada.",
            long_caption="Novidade confirmada pela fonte.",
            script_voiceover="O cantor confirmou a novidade.",
            on_screen_text=["NOVIDADE"],
            hashtags=["Musica"],
            category="music",
        )
        voice = mock.Mock(duration=12.0)
        voice.set_duration.return_value = voice

        with tempfile.TemporaryDirectory() as temp_dir:
            photo_path = Path(temp_dir) / "artist.jpg"
            Image.new("RGB", (1200, 1600), (35, 80, 140)).save(photo_path)
            photo = LicensedImage(
                path=str(photo_path),
                title="Cantor",
                creator="Fonte Teste",
                license=SOURCE_ARTICLE_LICENSE,
                license_url=news.url,
                source_page=news.url,
                source_url="https://cdn.example.com/artist.jpg",
                width=1200,
                height=1600,
            )
            with mock.patch(
                "src.video.generator.resolve_visual_media",
                return_value=("cantor", [photo], []),
            ), mock.patch(
                "src.video.generator._tts", return_value=Path(temp_dir) / "voice.mp3"
            ), mock.patch(
                "src.video.generator.AudioFileClip", return_value=voice
            ), mock.patch(
                "src.video.generator._mix_voice_with_background",
                return_value=mock.sentinel.audio,
            ), mock.patch(
                "src.video.generator._build_scene_images",
                side_effect=RuntimeError("scene-probe"),
            ) as build_scenes:
                with self.assertRaisesRegex(RuntimeError, "scene-probe"):
                    build_short(
                        news,
                        post,
                        Path(temp_dir),
                        enforce_media_requirements=False,
                    )

            self.assertEqual(build_scenes.call_args.args[2], [photo])
            self.assertEqual(build_scenes.call_args.kwargs["hook_media"], [photo])
            self.assertTrue(build_scenes.call_args.kwargs["repeat_single_media"])

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
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                request=request,
                json={"query": {"pages": []}},
            )

        with tempfile.TemporaryDirectory() as temp_dir, httpx.Client(
            transport=httpx.MockTransport(handler)
        ) as client:
            assets = fetch_licensed_artist_videos(
                "artista desconhecido",
                Path(temp_dir),
                client=client,
            )
            manifest = (Path(temp_dir) / "rights_manifest.json").read_text()
        self.assertEqual(assets, [])
        self.assertIn('"status": "no_verified_video"', manifest)

    def test_dynamic_commons_video_is_downloaded_with_verified_rights(self) -> None:
        query = "artista exemplo"
        media_url = "https://upload.wikimedia.org/example-480p.webm"
        page = {
            "title": "File:Artista Exemplo no palco.webm",
            "videoinfo": [
                {
                    "width": 1280,
                    "height": 720,
                    "duration": 45.0,
                    "descriptionurl": "https://commons.wikimedia.org/example",
                    "mediatype": "VIDEO",
                    "extmetadata": {
                        "ObjectName": {"value": "Artista Exemplo no palco"},
                        "ImageDescription": {"value": "Show do Artista Exemplo"},
                        "Artist": {"value": "Example Creator"},
                        "LicenseShortName": {"value": "CC BY 4.0"},
                        "LicenseUrl": {
                            "value": "https://creativecommons.org/licenses/by/4.0/"
                        },
                    },
                    "derivatives": [
                        {
                            "src": media_url,
                            "type": 'video/webm; codecs="vp9, opus"',
                            "width": 854,
                            "height": 480,
                            "bandwidth": 700_000,
                        }
                    ],
                }
            ],
        }

        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url).startswith("https://commons.wikimedia.org/w/api.php"):
                return httpx.Response(
                    200,
                    request=request,
                    json={"query": {"pages": [page]}},
                )
            self.assertEqual(str(request.url), media_url)
            return httpx.Response(200, request=request, content=b"x" * 100_001)

        with tempfile.TemporaryDirectory() as temp_dir, httpx.Client(
            transport=httpx.MockTransport(handler)
        ) as client:
            assets = fetch_licensed_artist_videos(
                query,
                Path(temp_dir),
                limit=1,
                client=client,
            )

        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0].license, "CC BY 4.0")
        self.assertEqual(assets[0].source_url, media_url)

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
