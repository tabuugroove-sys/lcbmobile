from __future__ import annotations

import unittest
from unittest import mock

from src.models import NewsItem
from src.processor.ai_writer import rewrite
from src.processor.template_writer import rewrite_via_template


class TemplateWriterTests(unittest.TestCase):
    def test_rewrite_uses_template_when_anthropic_and_gemini_fail(self) -> None:
        item = NewsItem(
            source_id="rss",
            source_name="Portal Teste",
            category="dj",
            url="https://example.com/fallback",
            title="DJ anuncia novo show em Sao Paulo",
            summary="A apresentacao sera em setembro.",
        )

        with mock.patch.dict(
            "os.environ",
            {"REWRITE_PROVIDER": "", "LOCAL_CLAUDE_FALLBACK": ""},
        ), mock.patch(
            "src.processor.ai_writer._rewrite_via_anthropic",
            side_effect=RuntimeError("ANTHROPIC_API_KEY is not configured."),
        ), mock.patch(
            "src.processor.fallback_writer.is_configured", return_value=True
        ), mock.patch(
            "src.processor.fallback_writer.rewrite_via_gemini",
            side_effect=ValueError("invalid model JSON"),
        ):
            post = rewrite(item)

        self.assertEqual(post.headline, item.title)
        self.assertIn(item.source_name, post.script_voiceover)

    def test_uses_only_source_material_and_builds_pt_br_post(self) -> None:
        item = NewsItem(
            source_id="rss",
            source_name="Portal Teste",
            category="dj",
            url="https://example.com/noticia",
            title="DJ anuncia novo show em Sao Paulo",
            summary="A apresentacao sera em setembro. Os ingressos comecam a ser vendidos amanha.",
        )

        post = rewrite_via_template(item)

        self.assertEqual(post.category, "dj")
        self.assertIn("DJ anuncia novo show", post.script_voiceover)
        self.assertIn("Portal Teste", post.script_voiceover)
        self.assertLessEqual(len(post.headline), 70)
        self.assertLessEqual(len(post.short_caption), 220)
        self.assertEqual(post.source_url, item.url)

    def test_strips_html_from_summary(self) -> None:
        item = NewsItem(
            source_id="rss",
            source_name="Fonte",
            category="musica",
            url="https://example.com/noticia",
            title="Cantora prepara lancamento",
            summary="<p>O single chega nesta sexta-feira.</p>",
        )

        post = rewrite_via_template(item)

        self.assertNotIn("<p>", post.script_voiceover)
        self.assertEqual(post.category, "geral")

    def test_headline_is_shortened_at_a_word_boundary(self) -> None:
        item = NewsItem(
            source_id="rss",
            source_name="Fonte",
            category="celebridades",
            url="https://example.com/noticia",
            title=(
                "Cantora internacional revela detalhes emocionantes sobre o "
                "proximo album aguardadissimo"
            ),
        )

        post = rewrite_via_template(item)

        self.assertLessEqual(len(post.headline), 70)
        self.assertTrue(post.headline.endswith("..."))
        self.assertNotIn(" alb...", post.headline)

    def test_removes_source_video_cta_and_builds_short_visual_beats(self) -> None:
        item = NewsItem(
            source_id="rss",
            source_name="Fonte",
            category="musica",
            url="https://example.com/jota",
            title=(
                "Considerado melhor show do Rock in Rio, "
                "Jota Quest foi batizado por Tim Maia"
            ),
            summary=(
                "Tim Maia em festival no RS; veja VÍDEO do momento. "
                "A banda ganhou o nome naquela noite."
            ),
        )

        post = rewrite_via_template(item)

        self.assertNotIn("veja vídeo", post.script_voiceover.casefold())
        self.assertEqual(post.on_screen_text[0], "jota quest")
        self.assertEqual(
            post.on_screen_text,
            [
                "jota quest",
                "Melhor show do rock",
                "Batizado por Tim Maia",
                "Origem do nome",
                "Fonte confirmada",
            ],
        )
        self.assertTrue(all(len(beat.split()) <= 5 for beat in post.on_screen_text))


if __name__ == "__main__":
    unittest.main()
