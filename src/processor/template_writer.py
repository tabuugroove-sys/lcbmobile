"""Deterministic pt-BR rewrite used when a server has no working AI API."""
from __future__ import annotations

import html
import re

from ..editorial import find_known_music_act
from ..models import NewsItem, RewrittenPost


_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_CATEGORIES = {"fofoca", "celebridades", "dj", "televisao", "geral"}
_DRAMA_RE = re.compile(
    r"\b(acidente|acusad[oa]|barraco|briga|cancelad[oa]|chora|chorou|crise|"
    r"desabafa|divorcio|escandalo|grave|hospital|internad[oa]|luto|morreu|"
    r"morte|pres[oa]|processad[oa]|separacao|surto|termino|traicao|treta)\b",
    re.IGNORECASE,
)
_SITE_CTA_RE = re.compile(
    r"\b(?:veja|assista)(?:\s+o)?\s+v[ií]deo(?:\s+do\s+momento)?[.!;:]?",
    re.IGNORECASE,
)


def _plain(value: str) -> str:
    plain = _SPACE_RE.sub(" ", _TAG_RE.sub(" ", html.unescape(value or ""))).strip()
    return _SPACE_RE.sub(" ", _SITE_CTA_RE.sub(" ", plain)).strip(" .;:")


def _clip_words(value: str, limit: int) -> str:
    words = value.split()
    if len(words) <= limit:
        return value
    return " ".join(words[:limit]).rstrip(".,;:") + "."


def _clip_chars(value: str, limit: int) -> str:
    """Shorten text without leaving a partial word at the boundary."""
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    candidate = value[: limit - 3].rstrip()
    if " " in candidate:
        candidate = candidate.rsplit(" ", 1)[0]
    return candidate.rstrip(".,;:") + "..."


def _screen_beats(title: str, summary_sentences: list[str]) -> list[str]:
    """Build short factual overlays instead of repeating full RSS sentences."""
    artist = find_known_music_act(f"{title} {' '.join(summary_sentences)}")
    seeds = [artist or ""]
    seeds.extend(part.strip(" .;:'\"") for part in re.split(r"[,;:–—]", title))
    seeds.extend(summary_sentences[:2])
    seeds.append("Fonte confirmada")

    beats: list[str] = []
    for seed in seeds:
        beat = _clip_words(_plain(seed), 4).rstrip(".")
        if beat and beat.casefold() not in {item.casefold() for item in beats}:
            beats.append(beat)
        if len(beats) >= 5:
            break
    return beats or ["Notícia da música"]


def rewrite_via_template(item: NewsItem) -> RewrittenPost:
    """Build a factual post strictly from title, summary and source metadata."""
    title = _plain(item.title).strip(" .") or "Noticia da musica"
    summary = _plain(item.summary)
    sentences = [part.strip() for part in _SENTENCE_RE.split(summary) if part.strip()]
    facts = " ".join(sentences[:2])

    is_drama = bool(_DRAMA_RE.search(f"{title} {summary}"))
    intro = (
        f"O mundo da musica parou com esta noticia: {title}."
        if is_drama
        else f"Atencao para esta noticia da musica: {title}."
    )
    if facts and facts.casefold() not in title.casefold():
        script = f"{intro} {facts}"
    else:
        script = intro
    outro = (
        f"A informacao foi publicada por {item.source_name}. "
        "Acompanhe as proximas atualizacoes deste caso."
    )
    script = _clip_words(f"{script} {outro}", 88)

    headline = _clip_chars(_clip_words(title, 11), 70)
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
        on_screen_text=_screen_beats(title, sentences),
        hashtags=hashtags,
        category=category,
    )
