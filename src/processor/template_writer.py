"""Deterministic pt-BR rewrite used when a server has no working AI API."""
from __future__ import annotations

import html
import re

from ..models import NewsItem, RewrittenPost


_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_CATEGORIES = {"fofoca", "celebridades", "dj", "televisao", "geral"}


def _plain(value: str) -> str:
    return _SPACE_RE.sub(" ", _TAG_RE.sub(" ", html.unescape(value or ""))).strip()


def _clip_words(value: str, limit: int) -> str:
    words = value.split()
    if len(words) <= limit:
        return value
    return " ".join(words[:limit]).rstrip(".,;:") + "."


def rewrite_via_template(item: NewsItem) -> RewrittenPost:
    """Build a factual post strictly from title, summary and source metadata."""
    title = _plain(item.title).strip(" .") or "Noticia da musica"
    summary = _plain(item.summary)
    sentences = [part.strip() for part in _SENTENCE_RE.split(summary) if part.strip()]
    facts = " ".join(sentences[:2])

    intro = f"Atencao para esta noticia da musica: {title}."
    if facts and facts.casefold() not in title.casefold():
        script = f"{intro} {facts}"
    else:
        script = intro
    outro = (
        f"A informacao foi publicada por {item.source_name}. "
        "Acompanhe as proximas atualizacoes deste caso."
    )
    script = _clip_words(f"{script} {outro}", 88)

    headline = _clip_words(title, 11)[:70].rstrip()
    category = item.category if item.category in _CATEGORIES else "geral"
    hashtags = ["Musica", "Noticias", "Famosos", "Brasil", "Shorts"]
    short_caption = _clip_words(f"{headline} 🎵 Saiba o que aconteceu. #Musica #Noticias #Shorts", 30)
    return RewrittenPost(
        source_url=item.url,
        headline=headline,
        short_caption=short_caption[:220],
        long_caption=(
            f"{headline}\n\n{facts or 'Confira a atualizacao divulgada pela fonte.'}"
            f"\n\nFonte: {item.source_name}"
        ),
        script_voiceover=script,
        on_screen_text=[headline, "Noticia da musica", "Veja os detalhes", "Fonte confirmada"],
        hashtags=hashtags,
        category=category,
    )
