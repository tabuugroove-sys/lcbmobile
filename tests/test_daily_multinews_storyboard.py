from __future__ import annotations

import unittest
from datetime import datetime, timezone

from scripts.run_daily_legal_multinews import _build_storyboard
from src.analytics.traffic_experiments import choose_traffic_profile
from src.models import NewsItem


def item(index: int, title: str) -> NewsItem:
    return NewsItem(
        source_id="test",
        source_name="Test",
        category="celebridades",
        url=f"https://example.com/news-{index}",
        title=title,
        summary="Resumo de teste para montagem horizontal.",
        published_at=datetime.now(timezone.utc),
    )


class DailyMultinewsStoryboardTests(unittest.TestCase):
    def test_storyboard_does_not_repeat_same_asset_back_to_back(self) -> None:
        profile = choose_traffic_profile("test", "fast_countdown")
        scenes, _ = _build_storyboard(
            [
                item(1, "Cantor aparece em festival"),
                item(2, "Atriz comenta bastidores de show"),
                item(3, "Banda prepara volta aos palcos"),
                item(4, "Famoso movimenta evento musical"),
                item(5, "Festival confirma nova data"),
            ],
            profile,
        )
        asset_ids = [str(scene["asset_id"]) for scene in scenes]
        for previous, current in zip(asset_ids, asset_ids[1:]):
            self.assertNotEqual(previous, current)
        self.assertGreaterEqual(len(set(asset_ids)), 5)


if __name__ == "__main__":
    unittest.main()
