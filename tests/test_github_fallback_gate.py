from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from scripts import github_fallback_gate
from scripts.github_fallback_gate import shorts_today, slot_day, target_for_schedule

SAO_PAULO = ZoneInfo("America/Sao_Paulo")


def _run_gate(mode: str, moment: datetime, shorts: int) -> tuple[int, str, list[date]]:
    """Run the 20:13 BRT fallback gate at `moment`; return exit code, outputs, days counted."""
    counted: list[date] = []

    def count(token_file, tz, day):
        counted.append(day)
        return shorts

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment.astimezone(tz)

    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "github_output"
        argv = ["github_fallback_gate", "--mode", mode, "--schedule", "13 23 * * *",
                "--github-output", str(output)]
        with patch.object(github_fallback_gate, "datetime", Clock), \
                patch.object(github_fallback_gate, "current_short_count", count), \
                patch.dict(os.environ, {"TIMEZONE": "America/Sao_Paulo"}), \
                patch("sys.argv", argv):
            code = github_fallback_gate.main()
        written = output.read_text(encoding="utf-8") if output.exists() else ""
    return code, written, counted


class GitHubFallbackGateTests(unittest.TestCase):
    def test_schedule_targets_match_cloud_fallback(self) -> None:
        self.assertEqual(target_for_schedule("13 13 * * *"), 1)
        self.assertEqual(target_for_schedule("13 18 * * *"), 2)
        self.assertEqual(target_for_schedule("13 23 * * *"), 3)
        self.assertEqual(target_for_schedule(""), 0)

    def test_counts_only_today_shorts_in_sao_paulo(self) -> None:
        rows = [
            {
                "snippet": {
                    "title": "Late upload #Shorts",
                    "description": "",
                    "publishedAt": "2026-09-17T02:30:00Z",
                }
            },
            {
                "snippet": {
                    "title": "Morning upload #Shorts",
                    "description": "",
                    "publishedAt": "2026-09-17T12:30:00Z",
                }
            },
            {
                "snippet": {
                    "title": "Horizontal video",
                    "description": "",
                    "publishedAt": "2026-09-17T12:30:00Z",
                }
            },
        ]
        tz = ZoneInfo("America/Sao_Paulo")
        self.assertEqual(shorts_today(rows, tz, date(2026, 9, 17)), 1)

    def test_late_runs_belong_to_their_slot_day(self) -> None:
        def at(day: int, hour: int, minute: int) -> datetime:
            return datetime(2026, 11, day, hour, minute, tzinfo=SAO_PAULO)

        self.assertEqual(slot_day("13 23 * * *", at(5, 20, 36), SAO_PAULO), date(2026, 11, 5))
        self.assertEqual(slot_day("13 23 * * *", at(6, 0, 26), SAO_PAULO), date(2026, 11, 5))
        self.assertEqual(slot_day("13 13 * * *", at(5, 17, 38), SAO_PAULO), date(2026, 11, 5))
        self.assertEqual(slot_day("13 13 * * *", at(6, 9, 0), SAO_PAULO), date(2026, 11, 5))

    def test_run_after_midnight_does_not_publish_into_the_new_day(self) -> None:
        # 2026-11-06 00:26 BRT: the 20:13 run uploaded a Short counted for 11-06.
        code, written, counted = _run_gate("gate", datetime(2026, 11, 6, 0, 26, tzinfo=SAO_PAULO), 3)

        self.assertEqual(code, 0)
        self.assertIn("should_run=false", written)
        self.assertEqual(counted, [date(2026, 11, 5)])

    def test_run_after_midnight_alerts_only_when_its_day_was_missed(self) -> None:
        code, written, _ = _run_gate("gate", datetime(2026, 11, 6, 0, 26, tzinfo=SAO_PAULO), 2)

        self.assertEqual(code, 1)
        self.assertIn("should_run=false", written)

    def test_run_before_midnight_still_fills_a_missed_slot(self) -> None:
        code, written, counted = _run_gate("gate", datetime(2026, 11, 5, 20, 36, tzinfo=SAO_PAULO), 2)

        self.assertEqual(code, 0)
        self.assertIn("should_run=true", written)
        self.assertEqual(counted, [date(2026, 11, 5)])

    def test_verify_after_midnight_counts_the_slot_day(self) -> None:
        code, _, counted = _run_gate("verify", datetime(2026, 11, 6, 0, 3, tzinfo=SAO_PAULO), 3)

        self.assertEqual(code, 0)
        self.assertEqual(counted, [date(2026, 11, 5)])
