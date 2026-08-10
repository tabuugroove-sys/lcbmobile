"""Keep candidate selection focused on music and people who make music."""
from __future__ import annotations

import re
import unicodedata

from ..models import NewsItem


_MUSIC_ROLES = {
    "banda",
    "cantor",
    "cantora",
    "compositor",
    "compositora",
    "dj",
    "funkeiro",
    "funkeira",
    "musico",
    "musica",
    "rapper",
    "sertanejo",
    "sertaneja",
    "vocalista",
}

_MUSIC_SUBJECTS = {
    "album",
    "billboard",
    "cache",
    "clipe",
    "concerto",
    "discografia",
    "funk",
    "grammy",
    "musica",
    "palco",
    "playlist",
    "rock",
    "sertanejo",
    "show",
    "single",
    "spotify",
    "turne",
}

_MUSIC_PHRASES = (
    "carreira musical",
    "lanca album",
    "lanca clipe",
    "lanca musica",
    "lanca single",
    "novo album",
    "nova musica",
    "novo single",
    "rock in rio",
    "subiu ao palco",
)

# Names are a fallback for terse headlines whose RSS summary omits the person's
# profession. Role/context terms remain the main signal and cover new artists.
_KNOWN_MUSIC_ACTS = (
    "adam levine",
    "adele",
    "ana castela",
    "anitta",
    "ariana grande",
    "bad bunny",
    "belo",
    "beyonce",
    "billie eilish",
    "bruno mars",
    "caetano veloso",
    "calvin harris",
    "chris martin",
    "coldplay",
    "dua lipa",
    "ed sheeran",
    "fafa de belem",
    "fabio jr",
    "gilberto gil",
    "gusttavo lima",
    "harry styles",
    "ivete sangalo",
    "iza",
    "j balvin",
    "joao gomes",
    "justin bieber",
    "katy perry",
    "lady gaga",
    "leonardo",
    "luan santana",
    "ludmilla",
    "madonna",
    "maiara",
    "maraisa",
    "maroon 5",
    "maria bethania",
    "mc daniel",
    "miley cyrus",
    "nattan",
    "ney matogrosso",
    "oliver tree",
    "pabllo vittar",
    "rihanna",
    "roberto carlos",
    "sabrina carpenter",
    "shakira",
    "sidney magal",
    "taylor swift",
    "the weeknd",
    "wesley safadao",
    "ze felipe",
    "ze neto",
)

_SCREEN_TERMS = {
    "ator",
    "atores",
    "atriz",
    "atrizes",
    "cinema",
    "cineasta",
    "elenco",
    "filme",
    "filmes",
    "novela",
    "novelas",
    "serie",
    "series",
}

_SCREEN_PHRASES = (
    "estreia nos cinemas",
    "festival de cinema",
    "papel no filme",
    "papel na novela",
    "papel na serie",
)


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return decomposed.encode("ascii", "ignore").decode("ascii").lower()


def is_music_news(item: NewsItem) -> bool:
    """Return whether a story belongs in a music-focused news feed.

    Personal stories and drama around musicians are allowed. Screen-industry
    stories are rejected unless the actual subject is explicitly music.
    """
    text = _plain(f"{item.title} {item.summary} {item.category}")
    tokens = set(re.findall(r"[a-z0-9]+", text))
    has_role = bool(tokens & _MUSIC_ROLES) or item.category.lower() == "dj"
    has_music_subject = bool(tokens & _MUSIC_SUBJECTS) or any(
        phrase in text for phrase in _MUSIC_PHRASES
    )
    has_known_act = any(name in text for name in _KNOWN_MUSIC_ACTS)
    has_screen_subject = bool(tokens & _SCREEN_TERMS) or any(
        phrase in text for phrase in _SCREEN_PHRASES
    )

    # A musician appearing in a movie is still a cinema story. Keep it only
    # when a concrete music subject (song, album, concert, soundtrack) exists.
    if has_screen_subject and not has_music_subject:
        return False
    return has_role or has_music_subject or has_known_act
