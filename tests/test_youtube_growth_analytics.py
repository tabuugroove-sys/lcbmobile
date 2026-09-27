from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.analytics.youtube_metrics import _analytics_rows
from src.models import NewsItem
from src.storage import Store


class YouTubeGrowthAnalyticsTests(unittest.TestCase):
    def test_parses_views_and_subscribers_by_video(self) -> None:
        rows = _analytics_rows(
            {
                "columnHeaders": [
                    {"name": "video"},
                    {"name": "views"},
                    {"name": "subscribersGained"},
                ],
                "rows": [["video-a", 40540, 127], ["video-b", 1200, 3]],
            }
        )

        self.assertEqual(
            rows,
            [
                {
                    "video_id": "video-a",
                    "view_count": 40540,
                    "subscribers_gained": 127,
                },
                {
                    "video_id": "video-b",
                    "view_count": 1200,
                    "subscribers_gained": 3,
                },
            ],
        )

    def test_public_refresh_preserves_private_growth_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.db")
            item = NewsItem(
                source_id="test",
                source_name="Test",
                category="musica",
                url="https://example.com/story",
                title="Anitta quebra o silencio apos polemica",
                summary="",
            )
            fingerprint = item.fingerprint()
            store.record_item_features(item)
            store.record_publication(
                fingerprint,
                "youtube",
                "video-a",
                "ok",
            )
            store.record_youtube_metrics(
                fingerprint=fingerprint,
                video_id="video-a",
                view_count=1000,
                like_count=20,
                comment_count=4,
            )
            store.record_youtube_growth_metrics(
                fingerprint=fingerprint,
                video_id="video-a",
                view_count=980,
                subscribers_gained=12,
            )
            store.record_youtube_metrics(
                fingerprint=fingerprint,
                video_id="video-a",
                view_count=1100,
                like_count=22,
                comment_count=5,
            )

            examples = store.analytics_examples(10)

        self.assertEqual(len(examples), 1)
        self.assertEqual(examples[0]["view_count"], 980)
        self.assertEqual(examples[0]["subscribers_gained"], 12)

    def test_channel_history_is_available_without_local_publication(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.db")
            store.record_youtube_growth_metrics(
                fingerprint="youtube:historic-video",
                video_id="historic-video",
                view_count=40_000,
                subscribers_gained=70,
                title="Cantora chora ao vivo apos revelacao",
            )

            examples = store.analytics_examples(10)

        self.assertEqual(len(examples), 1)
        self.assertEqual(examples[0]["title"], "Cantora chora ao vivo apos revelacao")
        self.assertEqual(examples[0]["view_count"], 40_000)
        self.assertEqual(examples[0]["subscribers_gained"], 70)


if __name__ == "__main__":
    unittest.main()
