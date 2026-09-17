from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.config import load_settings


class MediaGateConfigTests(unittest.TestCase):
    def _load(self, root: Path, **overrides: str):
        env = {
            "DB_PATH": str(root / "state.db"),
            "OUTPUT_DIR": str(root / "out"),
            **overrides,
        }
        with mock.patch.dict(os.environ, env, clear=True):
            return load_settings()

    def test_media_gates_are_disabled_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self._load(Path(temp_dir))

        self.assertFalse(settings.require_visual_media)
        self.assertEqual(settings.min_visual_media_assets, 0)
        self.assertFalse(settings.require_video_media)
        self.assertEqual(settings.min_video_media_assets, 0)

    def test_strict_media_gate_can_be_explicitly_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self._load(
                Path(temp_dir),
                REQUIRE_VISUAL_MEDIA="true",
                MIN_VISUAL_MEDIA_ASSETS="3",
                REQUIRE_VIDEO_MEDIA="true",
                MIN_VIDEO_MEDIA_ASSETS="2",
            )

        self.assertTrue(settings.require_visual_media)
        self.assertEqual(settings.min_visual_media_assets, 3)
        self.assertTrue(settings.require_video_media)
        self.assertEqual(settings.min_video_media_assets, 2)


if __name__ == "__main__":
    unittest.main()
