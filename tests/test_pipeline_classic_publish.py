from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from src import pipeline
from src.models import GeneratedAssets, NewsItem, RewrittenPost
from src.publisher.base import PublishResult


class _SuccessfulYouTubePublisher:
    name = "youtube"

    def __init__(self) -> None:
        self.calls: list[tuple[RewrittenPost, GeneratedAssets]] = []

    def publish(
        self, post: RewrittenPost, assets: GeneratedAssets
    ) -> PublishResult:
        self.calls.append((post, assets))
        return PublishResult(
            platform=self.name,
            ok=True,
            remote_id="classic-without-media",
        )


class ClassicPublishPipelineTests(unittest.TestCase):
    def test_publishes_when_no_photo_or_video_is_available(self) -> None:
        item = NewsItem(
            source_id="test-feed",
            source_name="Test Feed",
            category="music",
            url="https://example.com/shakira-news",
            title="Shakira anuncia nova musica",
            summary="A cantora confirmou a novidade.",
        )
        post = RewrittenPost(
            source_url=item.url,
            headline="Shakira confirma novidade",
            short_caption="Shakira confirmou a novidade.",
            long_caption="Shakira confirmou a novidade. Fonte no link.",
            script_voiceover="Shakira confirmou uma novidade para os fas.",
            on_screen_text=["SHAKIRA", "NOVIDADE"],
            hashtags=["Shakira", "Musica"],
            category="music",
        )
        assets = GeneratedAssets(
            video_path="/tmp/classic-without-media.mp4",
            duration_seconds=30.0,
        )
        publisher = _SuccessfulYouTubePublisher()

        def choose(candidates, _store, *, limit, stage, eligibility=None):
            del stage
            eligible = [
                candidate
                for candidate in candidates
                if eligibility is None or eligibility(candidate)
            ]
            return eligible[:limit]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            test_settings = replace(
                pipeline.settings,
                db_path=root / "state.db",
                output_dir=root / "out",
                require_visual_media=False,
                min_visual_media_assets=0,
                require_video_media=False,
                min_video_media_assets=0,
                max_attempts_per_item=1,
                retry_delay_seconds=0,
            )
            with (
                mock.patch("src.pipeline.settings", test_settings),
                mock.patch("src.video.generator.settings", test_settings),
                mock.patch("src.pipeline.refresh_youtube_metrics"),
                mock.patch("src.pipeline.hours_since_latest_short", return_value=None),
                mock.patch("src.pipeline.load_sources", return_value=[]),
                mock.patch("src.pipeline.collect_news", return_value=[item]),
                mock.patch("src.pipeline.is_music_news", return_value=True),
                mock.patch("src.pipeline.select_best_candidates", side_effect=choose),
                mock.patch(
                    "src.video.generator.resolve_visual_media",
                    return_value=(None, [], []),
                ) as resolve_media,
                mock.patch("src.pipeline.rewrite", return_value=post),
                mock.patch("src.pipeline.build_short", return_value=assets) as build,
                mock.patch("src.pipeline.build_publishers", return_value=[publisher]),
                mock.patch("src.pipeline.notify"),
                mock.patch("src.pipeline.notify_error"),
                mock.patch("src.pipeline.notify_summary"),
            ):
                report = pipeline.run(
                    only_publishers=["youtube"],
                    limit=1,
                    dry_run=False,
                )

        self.assertEqual(report.processed, 1)
        self.assertEqual(len(report.publish_results), 1)
        self.assertTrue(report.publish_results[0].ok)
        self.assertEqual(len(publisher.calls), 1)
        build.assert_called_once()
        self.assertTrue(build.call_args.kwargs["enforce_media_requirements"])
        resolve_media.assert_not_called()


if __name__ == "__main__":
    unittest.main()
