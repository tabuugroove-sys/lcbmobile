from __future__ import annotations

import unittest
from datetime import datetime, timezone

from src.analytics.scorer import (
    _cold_start_scores,
    _drama_score,
    select_best_candidates,
)
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

    def test_visual_eligibility_moves_to_next_ranked_story(self) -> None:
        class Store:
            def analytics_examples(self, limit: int) -> list[dict[str, object]]:
                return []

            def record_candidate_scores(self, **kwargs: object) -> None:
                self.recorded = kwargs

        no_visuals = item("Anitta chora após briga e separação")
        with_visuals = item("Shakira anuncia nova música")
        selected = select_best_candidates(
            [with_visuals, no_visuals],
            Store(),  # type: ignore[arg-type]
            limit=1,
            stage="test",
            eligibility=lambda candidate: candidate is with_visuals,
        )

        self.assertEqual(selected, [with_visuals])


if __name__ == "__main__":
    unittest.main()
