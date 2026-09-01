from __future__ import annotations

import unittest
import subprocess
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from scripts.local_backup_runner import (
    _run_pipeline,
    expected_posts,
    extract_source_url,
    parse_publish_slots,
)


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

    def test_primary_server_slots_are_configurable(self) -> None:
        slots = parse_publish_slots("08:13=1,13:13=2,20:13=3")
        self.assertEqual(expected_posts(self._at(8, 12), slots), 0)
        self.assertEqual(expected_posts(self._at(8, 13), slots), 1)
        self.assertEqual(expected_posts(self._at(20, 13), slots), 3)

    def test_invalid_slot_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_publish_slots("25:99=1")

    def test_extract_source_url(self) -> None:
        description = "Texto\n\nFonte: https://example.com/news?utm_source=x\n\n#Shorts"
        self.assertEqual(
            extract_source_url(description),
            "https://example.com/news?utm_source=x",
        )

    def test_missing_source_url(self) -> None:
        self.assertIsNone(extract_source_url("Sem link de fonte"))

    @patch("scripts.local_backup_runner.subprocess.run")
    def test_pipeline_timeout_returns_standard_timeout_code(self, run) -> None:
        run.side_effect = subprocess.TimeoutExpired(["python", "pipeline"], 9)
        with patch.dict("os.environ", {"PIPELINE_TIMEOUT_SECONDS": "9"}):
            self.assertEqual(_run_pipeline(), 124)


if __name__ == "__main__":
    unittest.main()
