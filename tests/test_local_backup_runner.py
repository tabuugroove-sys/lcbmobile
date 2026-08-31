from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.local_backup_runner import expected_posts, extract_source_url


class LocalBackupRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tz = ZoneInfo("America/Sao_Paulo")

    def _at(self, hour: int, minute: int) -> datetime:
        return datetime(2026, 8, 31, hour, minute, tzinfo=self.tz)

    def test_expected_posts_tracks_backup_slots(self) -> None:
        self.assertEqual(expected_posts(self._at(8, 27)), 0)
        self.assertEqual(expected_posts(self._at(8, 28)), 1)
        self.assertEqual(expected_posts(self._at(13, 27)), 1)
        self.assertEqual(expected_posts(self._at(13, 28)), 2)
        self.assertEqual(expected_posts(self._at(20, 28)), 3)

    def test_extract_source_url(self) -> None:
        description = "Texto\n\nFonte: https://example.com/news?utm_source=x\n\n#Shorts"
        self.assertEqual(
            extract_source_url(description),
            "https://example.com/news?utm_source=x",
        )

    def test_missing_source_url(self) -> None:
        self.assertIsNone(extract_source_url("Sem link de fonte"))


if __name__ == "__main__":
    unittest.main()
