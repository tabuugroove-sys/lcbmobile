from __future__ import annotations

import unittest
from datetime import date
from zoneinfo import ZoneInfo

from scripts.github_fallback_gate import shorts_today, target_for_schedule


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
