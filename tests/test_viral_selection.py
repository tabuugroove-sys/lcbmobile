from __future__ import annotations

import unittest
from datetime import datetime, timezone

from src.analytics.scorer import _cold_start_scores, _drama_score
from src.models import NewsItem


def item(title: str, summary: str = "") -> NewsItem:
    return NewsItem(
        source_id="test",
        source_name="Test",
        category="celebridades",
        url=f"https://example.com/{abs(hash((title, summary)))}",
        title=title,
        summary=summary,
        published_at=datetime.now(timezone.utc),
    )


class ViralSelectionTests(unittest.TestCase):
    def test_confirmed_drama_signal_beats_neutral_release(self) -> None:
        dramatic = item("Anitta quebra o silêncio após briga e separação")
        neutral = item("Cantora anuncia nova música")
        self.assertGreater(_drama_score(dramatic), _drama_score(neutral))

        scored = _cold_start_scores([neutral, dramatic])
        self.assertIs(scored[0][0], dramatic)
        self.assertIn("drama=", scored[0][2])
        self.assertIn("star=", scored[0][2])


if __name__ == "__main__":
    unittest.main()
