from __future__ import annotations

import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from scripts.run_daily_legal_multinews import (
    _asset_ids_for_item,
    _build_storyboard,
    _is_today_item,
    _visual_support_key,
    _youtube_metadata,
)
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

    def test_visual_support_key_requires_direct_legal_video_bucket(self) -> None:
        self.assertEqual(_visual_support_key(item(1, "Ronaldinho lança álbum")), "ronaldinho")
        self.assertEqual(_visual_support_key(item(2, "Caetano Veloso participa de campanha")), "caetano")
        self.assertEqual(_visual_support_key(item(3, "México abre portas para a Copa do Mundo")), "mexico")
        self.assertEqual(_visual_support_key(item(4, "Madonna faz show surpresa")), "madonna")
        self.assertEqual(_visual_support_key(item(7, "Waka Waka volta ao radar da Copa")), "shakira")
        self.assertIsNone(_visual_support_key(item(4, "Atriz comenta bastidores sem video direto")))
        self.assertIsNone(_visual_support_key(item(5, "Gravacoes no Mexico desafiam apresentadora")))
        self.assertIsNone(_visual_support_key(item(6, "Anitta busca novo feat sem video direto")))

    def test_supported_story_starts_with_direct_asset(self) -> None:
        self.assertEqual(
            _asset_ids_for_item(item(1, "Caetano Veloso participa de campanha"))[0],
            "caetano_unicamp",
        )
        self.assertEqual(
            _asset_ids_for_item(item(2, "Ronaldinho Gaucho lanca album"))[0],
            "ronaldinho_embratur",
        )
        self.assertNotIn(
            "calvin_live_04",
            _asset_ids_for_item(item(2, "Ronaldinho Gaucho lanca album")),
        )
        self.assertEqual(
            _asset_ids_for_item(item(3, "Mexico abre portas para a Copa do Mundo"))[0],
            "mexico_olympic_stadium",
        )
        self.assertEqual(
            _asset_ids_for_item(item(5, "Waka Waka volta ao radar da Copa"))[0],
            "shakira_un_imagine",
        )
        self.assertEqual(
            _asset_ids_for_item(item(4, "Madonna faz show surpresa"))[0],
            "madonna_russia_speech",
        )

    def test_daily_package_requires_today_local_date(self) -> None:
        tz = ZoneInfo("America/Sao_Paulo")
        today = item(1, "Ronaldinho lanca album").model_copy(
            update={"published_at": datetime(2026, 6, 9, 12, 0, tzinfo=timezone.utc)}
        )
        yesterday = item(2, "Rock in Rio esgota ingressos").model_copy(
            update={"published_at": datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)}
        )
        unknown = item(3, "Sem data no RSS").model_copy(update={"published_at": None})
        self.assertTrue(_is_today_item(today, tz, "2026-06-09"))
        self.assertFalse(_is_today_item(yesterday, tz, "2026-06-09"))
        self.assertFalse(_is_today_item(unknown, tz, "2026-06-09"))

    def test_youtube_metadata_uses_actual_item_count(self) -> None:
        profile = choose_traffic_profile("test", "fast_countdown")
        title, description, _ = _youtube_metadata(
            [
                item(1, "Ronaldinho lança álbum"),
                item(2, "Caetano Veloso participa de campanha"),
                item(3, "México abre portas para a Copa do Mundo"),
            ],
            profile,
        )
        self.assertIn("Top 3", title)
        self.assertIn("Top 3", description)


if __name__ == "__main__":
    unittest.main()
