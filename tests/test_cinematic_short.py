from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx
from PIL import Image

from src.video.commons_media import LicensedImage, _candidate, fetch_licensed_artist_images
from src.video.generator import (
    HEIGHT,
    WIDTH,
    _make_scene,
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
            "src.video.generator.fetch_licensed_artist_images",
            return_value=[],
        ) as fetch:
            artist, media = resolve_visual_media(news, Path(temp_dir))  # type: ignore[arg-type]

        self.assertIsNone(artist)
        self.assertEqual(media, [])
        fetch.assert_called_once()
        self.assertIsNone(fetch.call_args.args[0])

    def test_reference_style_requires_multiple_verified_visuals(self) -> None:
        news = type(
            "Item",
            (),
            {"title": "Shakira anuncia novidade", "summary": ""},
        )()
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch(
            "src.video.generator.resolve_visual_media",
            return_value=("shakira", [mock.sentinel.asset] * 3),
        ):
            self.assertTrue(visual_media_ready(news, Path(temp_dir)))  # type: ignore[arg-type]

        with tempfile.TemporaryDirectory() as temp_dir, mock.patch(
            "src.video.generator.resolve_visual_media",
            return_value=(None, []),
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


if __name__ == "__main__":
    unittest.main()
