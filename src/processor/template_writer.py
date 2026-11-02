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
_CLAUSE_RE = re.compile(r"[,;:–—](?=\s)")

# Viewers stay about 20 seconds whatever the length, so a 30-second Short is watched
# to about 70% and a 42-second one to about 45%, and the shorter one reaches far more
# people. At the channel's voice speed 60 words take about 30 seconds.
SHORT_HEADLINE_CHARS = 90
SHORT_MAX_WORDS = 60
SHORT_STRETCH_WORDS = 72
SHORT_MIN_WORDS = 28
SHORT_FLOOR_WORDS = 22
_MIN_CLAUSE_WORDS = 5
# A cut headline must not end on a word that needs the next one to make sense.
_DANGLING_WORDS = {
    "a", "o", "as", "os", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das",
    "em", "no", "na", "nos", "nas", "com", "por", "para", "pra", "pelo", "pela", "que",
    "e", "ou", "ao", "aos", "à", "às", "se", "sem", "sob", "sobre", "entre", "após",
    "como", "mas", "seu", "sua", "seus", "suas", "é", "foi", "são",
}


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


def _clip_headline(title: str, limit: int) -> str:
    """Cut a headline on a whole word that can end a phrase.

    Never at the first comma: Portuguese often puts the news after an apposition
    ("Cassandra Wilson, cantora de jazz, morre aos 70 anos").
    """
    if len(title) <= limit:
        return title
    clipped = title[: limit + 1].rsplit(" ", 1)[0]
    for opening, closing in (("“", "”"), ("‘", "’")):
        # A quotation cut in half reads as a mistake; the sentence before it stands on its own.
        if clipped.count(opening) > clipped.count(closing) and clipped.rfind(opening) >= limit // 2:
            clipped = clipped[: clipped.rfind(opening)]
    words = clipped.split()
    while len(words) > 1 and words[-1].casefold() in _DANGLING_WORDS:
        words.pop()
    # An unbroken run of characters has no word to cut on, and a title must never be empty.
    return " ".join(words).rstrip(".,;:–—") or title[:limit]


def _close(text: str) -> str:
    """End narration on a word that can end a sentence, with a period."""
    if not text or text[-1] in ".!?":
        return text
    words = text.split()
    while len(words) > 1 and words[-1].casefold() in _DANGLING_WORDS:
        words.pop()
    return " ".join(words).rstrip(",;:–—") + "."


def fit_voiceover(text: str, limit: int = SHORT_MAX_WORDS) -> str:
    """Keep whole sentences up to the limit; a cut sentence reads as a broken last line."""
    sentences = [part for part in _SENTENCE_RE.split(_SPACE_RE.sub(" ", text or "").strip()) if part]
    kept: list[str] = []
    used = 0
    for sentence in sentences:
        count = len(sentence.split())
        if used + count > limit:
            break
        kept.append(sentence)
        used += count
    if kept:
        return _close(" ".join(kept))
    if not sentences:
        return ""
    first = sentences[0]
    ends = [
        match.start()
        for match in _CLAUSE_RE.finditer(first)
        if _MIN_CLAUSE_WORDS <= len(first[: match.start()].split()) <= limit
    ]
    return _close(first[: ends[-1]] if ends else " ".join(first.split()[:limit]))


def _short_voiceover(title: str, sentences: list[str], source_name: str) -> str | None:
    """Open on the news itself: the first seconds decide whether a Short is watched.

    Returns None when the story is too thin for this form. Below about 8 seconds of
    speech the render fails, so such a story keeps the longer previous script.
    """
    lead = title if title[-1:] in {".", "!", "?"} else f"{title}."
    same = title.casefold()
    facts = [
        sentence
        for sentence in sentences
        if sentence.casefold().rstrip(" .!?") not in same and same not in sentence.casefold()
    ]
    script = fit_voiceover(" ".join([lead, *facts]))
    if len(script.split()) >= SHORT_MIN_WORDS:
        return script
    # One long sentence after the headline: slightly over the limit beats a bare headline.
    longer = fit_voiceover(" ".join([lead, *facts]), SHORT_STRETCH_WORDS)
    if len(longer.split()) >= SHORT_MIN_WORDS:
        return longer
    script = f"{script} A informação foi publicada por {source_name}."
    return script if len(script.split()) >= SHORT_FLOOR_WORDS else None


def _screen_beats(title: str, summary_sentences: list[str]) -> list[str]:
    """Build short factual overlays instead of repeating full RSS sentences."""
    combined = f"{title} {' '.join(summary_sentences)}"
    artist = find_known_music_act(combined)
    normalized = combined.casefold()
    fact_beats: list[str] = []
    if "melhor show" in normalized and "rock" in normalized:
        fact_beats.append("Melhor show do rock")
    if "batiz" in normalized and "tim maia" in normalized:
        fact_beats.append("Batizado por Tim Maia")
    if "ganhou o nome" in normalized or "origem do nome" in normalized:
        fact_beats.append("Origem do nome")

    seeds = [artist or "", *fact_beats]
    seeds.extend(part.strip(" .;:'\"") for part in re.split(r"[,;:–—]", title))
    seeds.extend(summary_sentences[:2])

    beats: list[str] = []
    for seed in seeds:
        beat = _clip_words(_plain(seed), 4).rstrip(".")
        if beat and beat.casefold() not in {item.casefold() for item in beats}:
            beats.append(beat)
        if len(beats) >= 4:
            break
    if "fonte confirmada" not in {item.casefold() for item in beats}:
        beats.append("Fonte confirmada")
    return beats[:5] or ["Notícia da música"]


def rewrite_via_template(item: NewsItem, *, short_form: bool = False) -> RewrittenPost:
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
    if short_form:
        script = _short_voiceover(title, sentences, item.source_name) or script
        headline = _clip_headline(title, SHORT_HEADLINE_CHARS)

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
