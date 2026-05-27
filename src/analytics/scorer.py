"""Score RSS candidates from historical YouTube reactions.

This is intentionally lightweight: a transparent heuristic works better here
than pretending we have enough data for a heavy model. It learns which sources,
categories and headline words have historically produced more YouTube views.
"""
from __future__ import annotations

import logging
import math
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean

from ..config import settings
from ..models import NewsItem
from ..storage import Store

log = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ]+")
_STOPWORDS = {
    "a",
    "ao",
    "aos",
    "as",
    "com",
    "da",
    "das",
    "de",
    "do",
    "dos",
    "e",
    "em",
    "na",
    "nas",
    "no",
    "nos",
    "o",
    "os",
    "para",
    "por",
    "que",
    "se",
    "um",
    "uma",
}

_DRAMA_TERMS = {
    "acidente",
    "afastado",
    "afastada",
    "ameaca",
    "ameacado",
    "ameacada",
    "briga",
    "cancelado",
    "cancelada",
    "chora",
    "chorando",
    "chorou",
    "colapso",
    "confusao",
    "crise",
    "desaba",
    "desabafa",
    "desespero",
    "doenca",
    "doente",
    "dor",
    "emergencia",
    "enterro",
    "escandalo",
    "exposto",
    "exposta",
    "grave",
    "hospital",
    "internado",
    "internada",
    "investigado",
    "investigada",
    "luto",
    "morre",
    "morreu",
    "morte",
    "perde",
    "perdeu",
    "policia",
    "preso",
    "presa",
    "processo",
    "revoltado",
    "revoltada",
    "separacao",
    "termino",
    "tragedia",
    "traicao",
    "treta",
}

_DRAMA_PHRASES = (
    "aos prantos",
    "climao",
    "estado grave",
    "foi preso",
    "foi presa",
    "foi internado",
    "foi internada",
    "passa mal",
    "passou mal",
    "perdeu tudo",
    "risco de morte",
)


def _tokens(text: str) -> list[str]:
    return [
        token.lower()
        for token in _TOKEN_RE.findall(text)
        if len(token) > 2 and token.lower() not in _STOPWORDS
    ]


def _performance(row: dict[str, object]) -> float:
    views = int(row.get("view_count") or 0)
    likes = int(row.get("like_count") or 0)
    comments = int(row.get("comment_count") or 0)
    return math.log1p(views) + 0.25 * math.log1p(likes) + 0.35 * math.log1p(comments)


def _avg(values: list[float], fallback: float) -> float:
    return mean(values) if values else fallback


def _freshness_score(item: NewsItem) -> float:
    if not item.published_at:
        return 0.0
    published = item.published_at
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    age_hours = max(
        0.0,
        (datetime.now(timezone.utc) - published.astimezone(timezone.utc)).total_seconds()
        / 3600.0,
    )
    return max(0.0, 1.0 - age_hours / 36.0)


def _plain_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return decomposed.encode("ascii", "ignore").decode("ascii").lower()


def _drama_score(item: NewsItem) -> float:
    """Boost stories with conflict, loss, health scares or public breakdowns."""
    text = _plain_text(f"{item.title} {item.summary}")
    tokens = set(_tokens(text))
    term_hits = len(tokens & _DRAMA_TERMS)
    phrase_hits = sum(1 for phrase in _DRAMA_PHRASES if phrase in text)
    raw = term_hits + 1.5 * phrase_hits
    return min(1.0, raw / 3.0)


def select_best_candidates(
    candidates: list[NewsItem],
    store: Store,
    *,
    limit: int,
    stage: str,
) -> list[NewsItem]:
    if not candidates:
        return []
    pool = candidates[: max(settings.analytics_candidate_pool, limit)]
    if not settings.analytics_enabled:
        return pool[:limit]

    examples = store.analytics_examples(settings.analytics_history_limit)
    if len(examples) < 3:
        log.info("Analytics has only %d examples; keeping RSS order", len(examples))
        selected = pool[:limit]
        store.record_candidate_scores(
            stage=stage,
            scores=[(item, float(len(pool) - idx), "rss_order") for idx, item in enumerate(pool)],
            selected={item.fingerprint() for item in selected},
        )
        return selected

    scores = [_performance(row) for row in examples]
    baseline = mean(scores)

    source_scores: dict[str, list[float]] = defaultdict(list)
    category_scores: dict[str, list[float]] = defaultdict(list)
    token_scores: dict[str, list[float]] = defaultdict(list)

    for row, perf in zip(examples, scores):
        source = str(row.get("source_id") or "")
        category = str(row.get("category") or "")
        if source:
            source_scores[source].append(perf)
        if category:
            category_scores[category].append(perf)
        for token in set(_tokens(str(row.get("title") or ""))):
            token_scores[token].append(perf)

    scored: list[tuple[NewsItem, float, str]] = []
    for item in pool:
        title_tokens = _tokens(item.title)
        token_values = [
            _avg(token_scores[token], baseline)
            for token in set(title_tokens)
            if len(token_scores[token]) >= 2
        ]
        source_part = _avg(source_scores[item.source_id], baseline)
        category_part = _avg(category_scores[item.category], baseline)
        token_part = _avg(token_values, baseline)
        freshness = _freshness_score(item)
        drama = _drama_score(item)

        score = (
            0.45 * source_part
            + 0.25 * category_part
            + 0.20 * token_part
            + 0.75 * freshness
            + settings.drama_signal_weight * drama
        )
        reason = (
            f"source={source_part:.2f} category={category_part:.2f} "
            f"tokens={token_part:.2f} fresh={freshness:.2f} drama={drama:.2f}"
        )
        scored.append((item, score, reason))

    scored.sort(key=lambda row: row[1], reverse=True)
    selected = [item for item, _, _ in scored[:limit]]
    store.record_candidate_scores(
        stage=stage,
        scores=scored[: min(len(scored), 50)],
        selected={item.fingerprint() for item in selected},
    )

    top = "; ".join(
        f"{item.source_id}:{score:.2f}:{item.title[:55]}"
        for item, score, _ in scored[: min(3, len(scored))]
    )
    log.info("Analytics selected %d/%d candidate(s): %s", len(selected), len(pool), top)
    return selected
