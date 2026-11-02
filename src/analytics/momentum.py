"""Let what just took off on the channel lift the next story about the same people.

A Short on this channel gets a median 86% of its 30-day views by the end of the
next day, so a hit is visible almost at once and its audience is still interested
for only a few days. A person's older popularity showed no predictive value, so
this signal is deliberately short-lived.

It only matches names and only ever adds to a score. Being a repeat of a subject
that did not take off was not worse than a new subject in the channel's history,
so nothing is penalised and new subjects keep their chance to become the next hit.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median
from typing import Iterable

from ..editorial import find_known_music_acts

HALF_LIFE_DAYS = 2.0
WINDOW_DAYS = 14
SHRINK = 1.0
# A word used across this share of older videos is a format ("Luto", "Globo"), not a subject.
MAX_SUBJECT_SHARE = 0.04
MIN_BASELINE_VIDEOS = 8
BASELINE_MIN_AGE_DAYS = 3
BASELINE_MAX_AGE_DAYS = 90
# A video this young may simply not have reached its audience yet.
TOO_YOUNG_TO_BE_COLD_DAYS = 2
MIN_OVERPERFORMANCE, MAX_OVERPERFORMANCE = -2.0, 4.0
# Score points per unit of heat. The cap keeps this below a confirmed drama or a
# known artist: at +1.0 the replay swapped the channel's biggest hit for a follow-up.
BONUS_PER_HEAT = 0.9
MAX_BONUS = 0.6
# Past this many same-subject videos in a day the next one earns no extra push, so
# one hot subject cannot fill all three daily slots on the strength of this signal.
MAX_SAME_SUBJECT_LAST_DAY = 1

_WORD_RE = re.compile(r"[\wÀ-ÖØ-öø-ÿ'’-]+")
_BREAK_RE = re.compile(r"[,:;!?.\"“”()\[\]–—|]")
_HASHTAG_RE = re.compile(r"#\w+")


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return decomposed.encode("ascii", "ignore").decode("ascii").lower().strip("'’-")


def _clean(text: str) -> str:
    return _HASHTAG_RE.sub(" ", text or "")


@dataclass(frozen=True)
class Heat:
    value: float = 0.0
    bonus: float = 0.0
    subjects: tuple[str, ...] = ()
    videos: int = 0
    last_day: int = 0


def _title_case(name: str) -> str:
    return " ".join(part.capitalize() for part in name.split())


def _views(row: dict) -> int:
    return max(int(row.get("view_count") or 0), int(row.get("public_view_count") or 0))


def _age_days(row: dict, now: datetime) -> float | None:
    try:
        stamp = datetime.fromisoformat(str(row["context"]["published_at"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        return None
    stamp = stamp.replace(tzinfo=stamp.tzinfo or timezone.utc)
    return (now - stamp.astimezone(timezone.utc)).total_seconds() / 86400


class MomentumProfile:
    """What is hot right now, computed only from data available at `now`."""

    def __init__(self, examples: Iterable[dict], *, now: datetime | None = None) -> None:
        self.now = now or datetime.now(timezone.utc)
        unique = {str(r["video_id"]): r for r in examples if r.get("video_id")}
        self._rows: list[tuple[dict, float, str]] = []
        for row in unique.values():
            if row.get("content_format") != "short":
                continue
            age = _age_days(row, self.now)
            if age is None or age < 0:
                continue
            self._rows.append((row, age, f"{_clean(row.get('title') or '')} . {row.get('rss_title') or ''}"))

        self._lower, self._capitalised = Counter(), Counter()
        for _, _, text in self._rows:
            for word in _WORD_RE.findall(text):
                (self._capitalised if word[0].isupper() else self._lower)[_plain(word)] += 1

        older = [text for _, age, text in self._rows if age > WINDOW_DAYS]
        self._document_frequency: Counter[str] = Counter()
        for text in older:
            self._document_frequency.update(self._raw_keys(text))
        self._subject_limit = max(2.0, MAX_SUBJECT_SHARE * len(older))

        peers = [
            math.log1p(_views(row))
            for row, age, _ in self._rows
            if BASELINE_MIN_AGE_DAYS <= age <= BASELINE_MAX_AGE_DAYS
        ]
        self.baseline = median(peers) if len(peers) >= MIN_BASELINE_VIDEOS else None

        self._recent: list[tuple[frozenset[str], float, float | None]] = []
        if self.baseline is None:
            return
        for row, age, text in self._rows:
            if age > WINDOW_DAYS:
                continue
            gap = math.log1p(_views(row)) - self.baseline
            performance = max(MIN_OVERPERFORMANCE, min(MAX_OVERPERFORMANCE, gap))
            if performance < 0 and age < TOO_YOUNG_TO_BE_COLD_DAYS:
                performance = None
            self._recent.append((frozenset(self.subjects(text)), age, performance))

    def _raw_keys(self, text: str) -> set[str]:
        keys = set(find_known_music_acts(text))
        for segment in _BREAK_RE.split(_clean(text)):
            run: list[str] = []
            for word in [*_WORD_RE.findall(segment), "~"]:
                plain = _plain(word)
                is_name = (
                    word[0].isupper()
                    and not word[0].isdigit()
                    and len(plain) >= 2
                    # A word the channel usually writes in lower case merely started a sentence.
                    and self._lower[plain] <= self._capitalised[plain] * 0.25
                )
                if is_name:
                    run.append(plain)
                else:
                    # One capitalised word is too often a place or a format ("Brasil", "Luto").
                    if len(run) >= 2:
                        keys.add(" ".join(run))
                    run = []
        return keys

    def subjects(self, text: str) -> set[str]:
        return {
            key
            for key in self._raw_keys(text)
            if self._document_frequency[key] <= self._subject_limit
        }

    def heat(self, text: str) -> Heat:
        wanted = self.subjects(text)
        if not wanted or not self._recent:
            return Heat()
        numerator = denominator = 0.0
        matched: set[str] = set()
        videos = last_day = 0
        for keys, age, performance in self._recent:
            shared = keys & wanted
            if not shared:
                continue
            last_day += age < 1
            if performance is None:
                continue
            weight = 0.5 ** (age / HALF_LIFE_DAYS)
            numerator += weight * performance
            denominator += weight
            videos += 1
            matched |= shared
        if not videos:
            return Heat(last_day=last_day)
        value = numerator / (denominator + SHRINK)
        bonus = 0.0
        if last_day <= MAX_SAME_SUBJECT_LAST_DAY:
            bonus = min(MAX_BONUS, BONUS_PER_HEAT * max(0.0, value))
        return Heat(value, bonus, tuple(sorted(matched)), videos, last_day)

    def hot_subjects(self, limit: int = 8) -> list[dict[str, object]]:
        """The subjects currently earning a bonus, strongest first."""
        names = {key for keys, _, performance in self._recent if performance is not None for key in keys}
        hot = []
        for name in names:
            heat = self.heat(_title_case(name))
            if heat.bonus > 0 and name in heat.subjects:
                hot.append({"subject": name, "heat": round(heat.value, 3),
                            "bonus": round(heat.bonus, 3), "videos": heat.videos})
        return sorted(hot, key=lambda row: -row["heat"])[:limit]
