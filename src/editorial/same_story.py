"""Recognise one event told twice, so several gossip feeds do not publish it twice.

The headlines must name the same person and use mostly the same words. Without a
shared name nothing is decided: anonymous headlines such as "Luto: cantor morre aos
76" look alike while being different people. A new development about someone is a
different story and is told apart by its words, and by the short time window the
caller applies. A one-word artist name needs more shared words, since "Anitta chora
em show" and "Anitta cancela show" are different news.
"""
from __future__ import annotations

import re
import unicodedata

from .music_filter import find_known_music_acts

_WORD_RE = re.compile(r"[\wÀ-ÖØ-öø-ÿ'’-]+")
_BREAK_RE = re.compile(r"[,:;!?.\"“”()\[\]–—|]")
_HASHTAG_RE = re.compile(r"#\w+")
_MIN_WORD_LENGTH = 4
_MIN_SHARED_NAME_WORDS = 2
_MIN_OVERLAP = 0.5
_MIN_SHARED_WORDS_BESIDES_ARTIST = 2


def _plain(word: str) -> str:
    decomposed = unicodedata.normalize("NFKD", word)
    return decomposed.encode("ascii", "ignore").decode("ascii").lower().strip("'’-")


def _name_words(title: str) -> set[str]:
    """Capitalised words, except one that only opens a sentence ("Luto: Cantor morre")."""
    names: set[str] = set()
    for segment in _BREAK_RE.split(_HASHTAG_RE.sub(" ", title or "")):
        words = _WORD_RE.findall(segment)
        for index, word in enumerate(words):
            if not word[0].isupper() or len(word) < 2:
                continue
            follows_name = index + 1 < len(words) and words[index + 1][0].isupper()
            if index > 0 or follows_name:
                names.add(_plain(word))
    return names


def _words(title: str) -> set[str]:
    words = (_plain(word) for word in _WORD_RE.findall(_HASHTAG_RE.sub(" ", title or "")))
    return {word for word in words if len(word) >= _MIN_WORD_LENGTH}


def same_story(first: str, second: str) -> bool:
    a, b = _words(first), _words(second)
    if not a or not b or len(a & b) / min(len(a), len(b)) < _MIN_OVERLAP:
        return False
    if len(_name_words(first) & _name_words(second)) >= _MIN_SHARED_NAME_WORDS:
        return True
    artists = set(find_known_music_acts(first)) & set(find_known_music_acts(second))
    artist_words = {word for artist in artists for word in artist.split()}
    return bool(artists) and len((a & b) - artist_words) >= _MIN_SHARED_WORDS_BESIDES_ARTIST
