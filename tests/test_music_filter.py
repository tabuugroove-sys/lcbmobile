from __future__ import annotations

import unittest

from src.editorial import find_known_music_act, find_known_music_acts, is_music_news
from src.models import NewsItem


def item(title: str, summary: str = "", category: str = "celebridades") -> NewsItem:
    return NewsItem(
        source_id="test",
        source_name="Test",
        category=category,
        url=f"https://example.com/{abs(hash((title, summary)))}",
        title=title,
        summary=summary,
    )


class MusicFilterTests(unittest.TestCase):
    def test_keeps_music_release_and_concert_news(self) -> None:
        self.assertTrue(is_music_news(item("Cantora lança novo álbum")))
        self.assertTrue(is_music_news(item("Festival confirma show surpresa")))
        self.assertTrue(is_music_news(item("DJ passa mal antes de apresentação", category="dj")))

    def test_keeps_personal_drama_around_musicians(self) -> None:
        self.assertTrue(is_music_news(item("Anitta desabafa e chora após separação")))
        self.assertTrue(is_music_news(item("Zé Felipe expõe presente da ex-mulher")))
        self.assertTrue(is_music_news(item("Boletim atualiza saúde de Sidney Magal")))
        self.assertTrue(
            is_music_news(item("Artista é internado", "O cantor cancelou seus compromissos"))
        )

    def test_rejects_movies_series_and_actor_news(self) -> None:
        self.assertFalse(is_music_news(item("Atriz revela bastidores de nova novela")))
        self.assertFalse(is_music_news(item("Novo filme domina bilheteria do cinema")))
        self.assertFalse(is_music_news(item("Festival de cinema anuncia novo elenco")))
        self.assertFalse(is_music_news(item("Taylor Swift negocia papel em novo filme")))

    def test_generic_festival_is_not_enough_to_pass(self) -> None:
        self.assertFalse(is_music_news(item("Festival gastronômico confirma nova edição")))

    def test_allows_music_that_is_connected_to_a_movie(self) -> None:
        self.assertTrue(is_music_news(item("Lady Gaga lança música para novo filme")))

    def test_finds_primary_known_music_act_for_media_search(self) -> None:
        self.assertEqual(
            find_known_music_act("Adam Levine fala sobre o Maroon 5"),
            "adam levine",
        )
        self.assertEqual(find_known_music_act("Bloc Party lança disco"), "bloc party")
        self.assertEqual(
            find_known_music_act("Jota Quest é batizado por Tim Maia"),
            "jota quest",
        )
        self.assertIsNone(find_known_music_act("Festival será batizado nesta sexta"))
        self.assertIsNone(find_known_music_act("Artista independente lança single"))

    def test_headline_subject_wins_over_later_relative(self) -> None:
        self.assertEqual(
            find_known_music_act(
                "Fiuk encerra carreira como cantor; briga com Fábio Jr chama atenção"
            ),
            "fiuk",
        )
        self.assertEqual(
            find_known_music_act("Fábio Jr comenta decisão de Fiuk"),
            "fabio jr",
        )

    def test_returns_all_named_acts_in_mention_order(self) -> None:
        self.assertEqual(
            find_known_music_acts(
                "Fiuk encerra carreira; Fábio Jr e Cleo comentam a decisão"
            ),
            ["fiuk", "fabio jr"],
        )


if __name__ == "__main__":
    unittest.main()
