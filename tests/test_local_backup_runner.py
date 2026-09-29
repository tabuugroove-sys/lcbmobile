from __future__ import annotations

import unittest
import subprocess
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zoneinfo import ZoneInfo

from scripts.local_backup_runner import (
    _alert_posting_gap,
    _run_pipeline,
    _shorts_today,
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
        self.assertEqual(expected_posts(self._at(9, 27)), 0)
        self.assertEqual(expected_posts(self._at(9, 28)), 1)
        self.assertEqual(expected_posts(self._at(14, 27)), 1)
        self.assertEqual(expected_posts(self._at(14, 28)), 2)
        self.assertEqual(expected_posts(self._at(19, 28)), 3)

    def test_primary_server_slots_are_configurable(self) -> None:
        slots = parse_publish_slots("09:13=1,14:13=2,19:13=3")
        self.assertEqual(expected_posts(self._at(9, 12), slots), 0)
        self.assertEqual(expected_posts(self._at(9, 13), slots), 1)
        self.assertEqual(expected_posts(self._at(19, 13), slots), 3)

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

    def test_shorts_today_counts_duplicate_source_url_once(self) -> None:
        uploads = [
            {
                "video_id": "first",
                "title": "Primeira versao #Shorts",
                "description": "Fonte: https://example.com/news",
                "published_at": "2026-08-31T12:30:00Z",
            },
            {
                "video_id": "duplicate",
                "title": "Outra manchete #Shorts",
                "description": (
                    "Fonte: http://www.example.com/news/?utm_source=backup"
                ),
                "published_at": "2026-08-31T12:31:00Z",
            },
            {
                "video_id": "other",
                "title": "Outra noticia #Shorts",
                "description": "Fonte: https://example.com/other",
                "published_at": "2026-08-31T12:32:00Z",
            },
        ]

        self.assertEqual(_shorts_today(uploads, self.tz, self._at(9, 40).date()), 2)

    @patch("scripts.local_backup_runner.subprocess.run")
    def test_pipeline_timeout_returns_standard_timeout_code(self, run) -> None:
        run.side_effect = subprocess.TimeoutExpired(["python", "pipeline"], 9)
        with patch.dict("os.environ", {"PIPELINE_TIMEOUT_SECONDS": "9"}):
            self.assertEqual(_run_pipeline(), 124)

    def test_posting_gap_alert_is_sent_once_per_quota_milestone(self) -> None:
        with TemporaryDirectory() as temp_dir, patch(
            "scripts.local_backup_runner.STATE_FILE",
            Path(temp_dir) / "state.json",
        ), patch(
            "scripts.local_backup_runner.notify_urgent",
            return_value=True,
        ) as notify:
            first = _alert_posting_gap(
                self._at(13, 45), current=1, target=2, return_code=3
            )
            second = _alert_posting_gap(
                self._at(13, 50), current=1, target=2, return_code=3
            )

        self.assertTrue(first)
        self.assertFalse(second)
        notify.assert_called_once()
        self.assertIn("YouTube Shorts today: 1/2", notify.call_args.args[0])

    def test_failed_alert_delivery_is_retried(self) -> None:
        with TemporaryDirectory() as temp_dir, patch(
            "scripts.local_backup_runner.STATE_FILE",
            Path(temp_dir) / "state.json",
        ), patch(
            "scripts.local_backup_runner.notify_urgent",
            side_effect=[False, True],
        ) as notify:
            first = _alert_posting_gap(
                self._at(20, 45), current=2, target=3, return_code=124
            )
            second = _alert_posting_gap(
                self._at(20, 50), current=2, target=3, return_code=124
            )

        self.assertFalse(first)
        self.assertTrue(second)
        self.assertEqual(notify.call_count, 2)


if __name__ == "__main__":
    unittest.main()
