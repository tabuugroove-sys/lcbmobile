from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from src.analytics.traffic_experiments import (
    choose_traffic_profile,
    order_items_for_profile,
)
from src.models import NewsItem


def item(title: str, summary: str = "") -> NewsItem:
    return NewsItem(
        source_id="test",
        source_name="Test",
        category="celebridades",
        url=f"https://example.com/{abs(hash(title))}",
        title=title,
        summary=summary,
        published_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )


class TrafficExperimentTests(unittest.TestCase):
    def test_auto_profile_is_stable_for_same_key(self) -> None:
        first = choose_traffic_profile("daily-legal-multinews:2026-06-09")
        second = choose_traffic_profile("daily-legal-multinews:2026-06-09")
        self.assertEqual(first.id, second.id)

    def test_unknown_override_falls_back_to_fast_countdown(self) -> None:
        profile = choose_traffic_profile("any-key", "does_not_exist")
        self.assertEqual(profile.id, "fast_countdown")

    def test_conflict_first_moves_drama_story_to_front(self) -> None:
        profile = choose_traffic_profile("any-key", "conflict_first")
        ordered = order_items_for_profile(
            [
                item("Show anuncia nova data"),
                item("Cantor passa mal e vai ao hospital", "estado grave"),
                item("Atriz aparece em festival"),
            ],
            profile,
        )
        self.assertIn("hospital", ordered[0].title.lower())

    def test_star_name_first_moves_known_entity_to_front(self) -> None:
        profile = choose_traffic_profile("any-key", "star_name_first")
        ordered = order_items_for_profile(
            [
                item("Cantor de forro critica cachê"),
                item("Shakira entra em evento global"),
                item("Festival confirma nova data"),
            ],
            profile,
        )
        self.assertIn("shakira", ordered[0].title.lower())


if __name__ == "__main__":
    unittest.main()
