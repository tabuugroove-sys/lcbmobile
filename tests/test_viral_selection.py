from __future__ import annotations

import unittest
from datetime import datetime, timezone

from src.analytics.scorer import (
    _cold_start_scores,
    _drama_score,
    _topic_labels,
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
    def test_groups_winning_headlines_into_stable_topics(self) -> None:
        self.assertIn("public_conflict", _topic_labels("Ex-colega detona cantora na TV"))
        self.assertIn("shock_reveal", _topic_labels("Ele cresceu e está absurdo"))
        self.assertIn("loss_mourning", _topic_labels("Luto: morre cantor aos 54 anos"))

    def test_confirmed_drama_signal_beats_neutral_release(self) -> None:
        dramatic = item("Anitta quebra o silêncio após briga e separação")
        neutral = item("Cantora anuncia nova música")
        self.assertGreater(_drama_score(dramatic), _drama_score(neutral))

        scored = _cold_start_scores([neutral, dramatic])
        self.assertIs(scored[0][0], dramatic)
        self.assertIn("drama=", scored[0][2])
        self.assertIn("star=", scored[0][2])

    def test_channel_topic_history_boosts_similar_new_story(self) -> None:
        class Store:
            def analytics_examples(self, limit: int) -> list[dict[str, object]]:
                return [
                    {
                        "source_id": "test",
                        "category": "celebridades",
                        "title": "Ex-colega detona cantora na TV",
                        "summary": "",
                        "view_count": 28300,
                        "like_count": 900,
                        "comment_count": 180,
                    },
                    {
                        "source_id": "test",
                        "category": "celebridades",
                        "title": "Cantor anuncia agenda da semana",
                        "summary": "",
                        "view_count": 300,
                        "like_count": 8,
                        "comment_count": 1,
                    },
                    {
                        "source_id": "test",
                        "category": "celebridades",
                        "title": "Artista mostra bastidores do show",
                        "summary": "",
                        "view_count": 250,
                        "like_count": 7,
                        "comment_count": 0,
                    },
                ]

            def record_candidate_scores(self, **kwargs: object) -> None:
                self.recorded = kwargs

        neutral = item("Shakira anuncia nova música")
        conflict = item("Anitta detona ex-colega após polêmica")
        selected = select_best_candidates(
            [neutral, conflict],
            Store(),  # type: ignore[arg-type]
            limit=1,
            stage="test",
        )

        self.assertEqual(selected, [conflict])

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
