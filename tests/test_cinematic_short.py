from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from src.video.commons_media import LicensedImage, _candidate
from src.video.generator import HEIGHT, WIDTH, _make_scene


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


class SceneRenderTests(unittest.TestCase):
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
