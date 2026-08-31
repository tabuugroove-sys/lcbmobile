from __future__ import annotations

import unittest

from src.models import NewsItem
from src.processor.template_writer import rewrite_via_template


class TemplateWriterTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
