"""Traffic experiments for long-form YouTube videos.

The goal is not to guess the algorithm. We rotate a small set of visible
editorial formats, store the assigned variant, then compare YouTube metrics by
variant after uploads.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

from ..models import NewsItem
from .scorer import _drama_score, _freshness_score


@dataclass(frozen=True)
class TrafficProfile:
    id: str
    label: str
    hypothesis: str
    title_style: str
    opening_body: str


PROFILES: tuple[TrafficProfile, ...] = (
    TrafficProfile(
        id="conflict_first",
        label="Conflict first",
        hypothesis=(
            "Open with the highest-drama story so the first 15 seconds promise "
            "conflict, loss, health scare, scandal or urgent tension."
        ),
        title_style="lead with the strongest drama headline",
        opening_body="O ponto mais tenso vem primeiro, antes do resumo do dia.",
    ),
    TrafficProfile(
        id="star_name_first",
        label="Star name first",
        hypothesis=(
            "Put the most recognizable star or event in the first topic and in "
            "the title so Browse/Suggested gets a cleaner audience signal."
        ),
        title_style="lead with the strongest known entity",
        opening_body="A edicao abre pelo nome que o publico reconhece mais rapido.",
    ),
    TrafficProfile(
        id="fast_countdown",
        label="Fast countdown",
        hypothesis=(
            "Keep the Top 5 promise obvious and fast so viewers know there are "
            "multiple payoffs, not one slow generic compilation."
        ),
        title_style="clear Top 5 daily pop-news promise",
        opening_body="Cinco noticias em ritmo direto, sem introducao longa.",
    ),
)

PROFILE_BY_ID = {profile.id: profile for profile in PROFILES}

_KNOWN_ENTITY_PATTERNS = (
    "shakira",
    "dua lipa",
    "calvin harris",
    "maroon 5",
    "adam levine",
    "anitta",
    "madonna",
    "rock in rio",
)


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return decomposed.encode("ascii", "ignore").decode("ascii").lower()


def _known_entity_score(item: NewsItem) -> float:
    text = _plain(f"{item.title} {item.summary}")
    hits = sum(1 for entity in _KNOWN_ENTITY_PATTERNS if entity in text)
    return min(1.0, hits / 2.0)


def choose_traffic_profile(key: str, override: str = "auto") -> TrafficProfile:
    """Choose a stable profile for a run.

    `auto` rotates deterministically from the run key, so retries of the same
    daily video keep the same variant and do not pollute the test.
    """
    override = (override or "auto").strip().lower()
    if override and override != "auto":
        return PROFILE_BY_ID.get(override, PROFILE_BY_ID["fast_countdown"])
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    index = int(digest[:8], 16) % len(PROFILES)
    return PROFILES[index]


def order_items_for_profile(
    items: list[NewsItem],
    profile: TrafficProfile,
) -> list[NewsItem]:
    if profile.id == "conflict_first":
        return sorted(
            items,
            key=lambda item: (
                _drama_score(item),
                _freshness_score(item),
                _known_entity_score(item),
            ),
            reverse=True,
        )
    if profile.id == "star_name_first":
        return sorted(
            items,
            key=lambda item: (
                _known_entity_score(item),
                _drama_score(item),
                _freshness_score(item),
            ),
            reverse=True,
        )
    return list(items)


def headline_angle(item: NewsItem, profile: TrafficProfile) -> str:
    title = re.sub(r"\s+", " ", item.title).strip()
    if profile.id == "conflict_first":
        return f"O caso mais tenso: {title}"
    if profile.id == "star_name_first":
        return f"O nome do dia: {title}"
    return f"Noticia do dia: {title}"


def experiment_reason(items: list[NewsItem], profile: TrafficProfile) -> str:
    if not items:
        return f"profile={profile.id}"
    lead = items[0]
    return (
        f"profile={profile.id} drama={_drama_score(lead):.2f} "
        f"fresh={_freshness_score(lead):.2f} entity={_known_entity_score(lead):.2f}"
    )
