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
from typing import Callable

from ..config import settings
from ..editorial import find_known_music_act, is_music_news
from ..models import NewsItem
from ..storage import Store
from .momentum import Heat, MomentumProfile

log = logging.getLogger(__name__)

# Hit follow-ups were validated on Shorts only; the long-form bulletins have no such evidence.
_MOMENTUM_STAGES = {"fresh", "fallback"}

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
    "acusacao",
    "acusado",
    "acusada",
    "barraco",
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
    "demissao",
    "divorcio",
    "doenca",
    "doente",
    "dor",
    "emergencia",
    "enterro",
    "escandalo",
    "falencia",
    "faliu",
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
    "processado",
    "processada",
    "revoltado",
    "revoltada",
    "separacao",
    "surto",
    "termino",
    "tragedia",
    "traicao",
    "treta",
    "vaiado",
    "vaiada",
}

_DRAMA_PHRASES = (
    "aos prantos",
    "climao",
    "estado grave",
    "fim do casamento",
    "foi preso",
    "foi presa",
    "foi internado",
    "foi internada",
    "passa mal",
    "passou mal",
    "quebra o silencio",
    "show cancelado",
    "troca de farpas",
    "perdeu tudo",
    "risco de morte",
)

# Broad topic buckets make the learning less brittle than exact headline
# tokens. A past winner containing "detona" can therefore help a new story
# containing "troca de farpas", even when those exact words never repeated.
_TOPIC_TERMS = {
    "public_conflict": {
        "acusa",
        "acusacao",
        "barraco",
        "briga",
        "criticou",
        "criticado",
        "criticada",
        "detona",
        "exposto",
        "exposta",
        "polemica",
        "polemico",
        "denunciado",
        "denunciada",
        "processo",
        "revoltado",
        "revoltada",
        "treta",
        "vaiado",
        "vaiada",
    },
    "shock_reveal": {
        "absurdo",
        "choca",
        "chocante",
        "chocou",
        "cresceu",
        "inacreditavel",
        "revela",
        "revelacao",
        "segredo",
        "surpreende",
        "surpreendeu",
        "transformacao",
    },
    "loss_mourning": {
        "despedida",
        "enterro",
        "falecimento",
        "funeral",
        "luto",
        "morre",
        "morreu",
        "morrer",
        "morte",
    },
    "health_crisis": {
        "colapso",
        "doenca",
        "doente",
        "emergencia",
        "grave",
        "hospital",
        "internado",
        "internada",
        "surto",
    },
    "relationship_drama": {
        "divorcio",
        "separacao",
        "termino",
        "traicao",
    },
    "family_reveal": {"filho", "filha", "gravidez", "bebe", "paternidade", "maternidade"},
    "rare_access": {"raro", "rara", "inedito", "inedita", "bastidores"},
    "transformation": {"cresceu", "transformacao", "irreconhecivel"},
}

_TOPIC_PHRASES = {
    "public_conflict": ("troca de farpas", "quebra o silencio"),
    "shock_reveal": ("antes e depois", "ninguem esperava", "perdeu tudo"),
    "loss_mourning": ("morre aos", "morreu aos"),
    "health_crisis": ("estado grave", "passa mal", "passou mal"),
    "relationship_drama": ("fim do casamento", "ex affair", "ex-affair", "reconciliacao", "relacao com", "estao voltando"),
    "transformation": ("antes e depois",),
}

# Cold-start priors mirror the channel evidence supplied by the owner: direct
# public conflict won most strongly, followed by shock/reveal and mourning.
# Once history exists, the learned lift below can move these priors up or down.
_TOPIC_PRIORS = {
    "public_conflict": 1.00,
    "shock_reveal": 0.82,
    "loss_mourning": 0.78,
    "health_crisis": 0.70,
    "relationship_drama": 0.68,
    "family_reveal": 0.65,
}


def _tokens(text: str) -> list[str]:
    return [
        token.lower()
        for token in _TOKEN_RE.findall(text)
        if len(token) > 2 and token.lower() not in _STOPWORDS
    ]


def _performance(row: dict[str, object]) -> float:
    views = int(row.get("view_count") or 0)
    subscribers = int(row.get("subscribers_gained") or 0)
    # The owner cares about two outcomes: reach and channel growth. Log scaling
    # keeps one outlier from owning the model forever, while the larger
    # subscriber coefficient rewards videos that convert viewers into followers.
    return math.log1p(views) + 1.75 * math.log1p(subscribers)


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


def _topic_labels(text: str) -> set[str]:
    """Map varied PT-BR wording into stable, learnable viral topic buckets."""
    plain = _plain_text(text)
    tokens = set(_tokens(plain))
    labels = {
        topic
        for topic, terms in _TOPIC_TERMS.items()
        if tokens & terms
    }
    labels.update(
        topic
        for topic, phrases in _TOPIC_PHRASES.items()
        if any(phrase in plain for phrase in phrases)
    )
    return labels


def _topic_prior(item: NewsItem) -> tuple[float, set[str]]:
    labels = _topic_labels(f"{item.title} {item.summary}")
    if not labels:
        return 0.0, labels
    strongest = max(_TOPIC_PRIORS.get(label, 0.0) for label in labels)
    return min(1.0, strongest + 0.05 * (len(labels) - 1)), labels


def _cold_start_scores(pool: list[NewsItem]) -> list[tuple[NewsItem, float, str]]:
    """Score candidates when YouTube history is absent or too small."""
    scored: list[tuple[NewsItem, float, str]] = []
    for idx, item in enumerate(pool):
        freshness = _freshness_score(item)
        drama = _drama_score(item)
        topic, topic_labels = _topic_prior(item)
        star = 1.0 if find_known_music_act(f"{item.title} {item.summary}") else 0.0
        rss_order = 1.0 - (idx / max(len(pool), 1))
        score = (
            0.60 * rss_order
            + 0.75 * freshness
            + settings.drama_signal_weight * drama
            + 0.85 * topic
            + 0.35 * star
        )
        reason = (
            f"rss={rss_order:.2f} fresh={freshness:.2f} "
            f"drama={drama:.2f} topic={topic:.2f} "
            f"topics={','.join(sorted(topic_labels)) or '-'} star={star:.2f}"
        )
        scored.append((item, score, reason))
    scored.sort(key=lambda row: row[1], reverse=True)
    return scored


def _momentum_profile(examples: list[dict[str, object]], stage: str) -> MomentumProfile | None:
    if stage.split(":")[0] not in _MOMENTUM_STAGES:
        return None
    try:
        profile = MomentumProfile(examples)
        log.info("Hot subjects right now: %s", profile.hot_subjects() or "none")
        return profile
    except Exception as exc:  # noqa: BLE001 - a ranking signal must never stop publishing
        log.warning("Momentum signal unavailable: %s", exc)
        return None


def _heat_of(momentum: MomentumProfile | None, item: NewsItem) -> Heat:
    if momentum is None:
        return Heat()
    try:
        return momentum.heat(item.title)
    except Exception as exc:  # noqa: BLE001 - a ranking signal must never stop publishing
        log.warning("Momentum failed for %s: %s", item.url, exc)
        return Heat()


def select_best_candidates(
    candidates: list[NewsItem],
    store: Store,
    *,
    limit: int,
    stage: str,
    eligibility: Callable[[NewsItem], bool] | None = None,
) -> list[NewsItem]:
    if not candidates:
        return []
    music_candidates = [item for item in candidates if is_music_news(item)]
    rejected = len(candidates) - len(music_candidates)
    if rejected:
        log.info("Editorial music filter rejected %d candidate(s)", rejected)
    pool = music_candidates[: max(settings.analytics_candidate_pool, limit)]
    if not pool:
        return []
    if not settings.analytics_enabled:
        selected = []
        for item in pool:
            if eligibility is None or eligibility(item):
                selected.append(item)
            if len(selected) >= limit:
                break
        return selected

    examples = store.analytics_examples(None)
    if len(examples) < 3:
        log.info(
            "Analytics has only %d examples; using cold-start drama scoring",
            len(examples),
        )
        scored = _cold_start_scores(pool)
        selected = []
        for item, _, _ in scored:
            if eligibility is None or eligibility(item):
                selected.append(item)
            if len(selected) >= limit:
                break
        store.record_candidate_scores(
            stage=stage,
            scores=scored[: min(len(scored), 50)],
            selected={item.fingerprint() for item in selected},
        )
        return selected

    scores = [_performance(row) for row in examples]
    baseline = mean(scores)
    from .winner_insights import build_insights, topic_bonus
    audience_profile = build_insights(examples if stage != 'daily_multinews' else [])
    momentum = _momentum_profile(examples, stage)

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
        topic_prior, topic_labels = _topic_prior(item)
        topic_lift = topic_bonus(audience_profile, topic_labels)
        star = 1.0 if find_known_music_act(f"{item.title} {item.summary}") else 0.0
        heat = _heat_of(momentum, item)

        score = (
            0.45 * source_part
            + 0.25 * category_part
            + 0.20 * token_part
            + 0.75 * freshness
            + settings.drama_signal_weight * drama
            + 0.90 * topic_prior
            + 0.80 * topic_lift
            + 0.35 * star
            + heat.bonus
        )
        reason = (
            f"source={source_part:.2f} category={category_part:.2f} "
            f"tokens={token_part:.2f} fresh={freshness:.2f} "
            f"drama={drama:.2f} topic={topic_prior:.2f} "
            f"topic_lift={topic_lift:.2f} "
            f"audience_n={audience_profile['training_count']} "
            f"topics={','.join(sorted(topic_labels)) or '-'} star={star:.2f} "
            f"heat={heat.value:.2f} momentum={heat.bonus:.2f} "
            f"subjects={','.join(s.replace(' ', '_') for s in heat.subjects) or '-'}"
        )
        scored.append((item, score, reason))

    scored.sort(key=lambda row: row[1], reverse=True)
    selected = []
    for item, _, _ in scored:
        if eligibility is None or eligibility(item):
            selected.append(item)
        if len(selected) >= limit:
            break
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
