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
    "maestro",
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
    "bloc party",
    "bruno mars",
    "caetano veloso",
    "calvin harris",
    "chris martin",
    "coldplay",
    "dua lipa",
    "drake",
    "dj topo",
    "ed sheeran",
    "fafa de belem",
    "fabio jr",
    "fiuk",
    "gilberto gil",
    "george henrique e rodrigo",
    "gusttavo lima",
    "harry styles",
    "ivete sangalo",
    "iza",
    "j balvin",
    "jota quest",
    "joao bosco",
    "joao gomes",
    "joelma",
    "justin bieber",
    "katy perry",
    "karina zeviani",
    "karol g",
    "lady gaga",
    "leonardo",
    "luan santana",
    "ludmilla",
    "madonna",
    "mc cabelinho",
    "maiara",
    "maraisa",
    "maroon 5",
    "maria bethania",
    "matheus aleixo",
    "mc daniel",
    "miley cyrus",
    "nattan",
    "ney matogrosso",
    "oliver tree",
    "pabllo vittar",
    "phil collins",
    "priscilla",
    "rihanna",
    "rick e renner",
    "roberto carlos",
    "sabrina carpenter",
    "shakira",
    "sidney magal",
    "taylor swift",
    "the weeknd",
    "tim maia",
    "wesley safadao",
    "xande de pilares",
    "ze felipe",
    "ze neto",
)

_NAME_TOKEN = r"[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ0-9'’-]*"
_ROLE_NAMED_ACT_RE = re.compile(
    rf"\b(?i:cantor(?:a)?|rapper|funkeir[oa]|dj|vocalista|m[uú]sico|"
    rf"sertanej[oa]|maestro|banda|dupla)\s+({_NAME_TOKEN}(?:\s+{_NAME_TOKEN}){{0,2}})"
)
_ROLE_ACT_ALIASES = {
    "rick": "rick e renner",
    "rick sollo": "rick e renner",
}

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


def find_known_music_acts(text: str) -> list[str]:
    """Return known music acts in editorial mention order."""
    plain = _plain(text)
    matches: list[tuple[int, int, str]] = []
    for name in _KNOWN_MUSIC_ACTS:
        match = re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", plain)
        if match:
            matches.append((match.start(), -len(name), name))
    return [name for _, _, name in sorted(matches)]


def find_known_music_act(text: str) -> str | None:
    """Return the first known music act named in editorial text.

    Headlines normally put their subject before relatives, collaborators or
    rivals. Preferring the first mention prevents a secondary person from
    supplying every visual in a story about the actual headline subject.
    """
    matches = find_known_music_acts(text)
    return matches[0] if matches else None


def find_music_act_query(text: str) -> str | None:
    """Return a useful media-search query for a named musician in a headline.

    The curated registry remains the safest first choice. The role pattern
    covers current artists that are absent from that list, such as ``cantor
    Rick`` or ``rapper Nome Sobrenome``.
    """
    known = find_known_music_act(text)
    if known:
        return known
    match = _ROLE_NAMED_ACT_RE.search(text or "")
    if not match:
        return None
    extracted = _plain(match.group(1)).strip()
    return _ROLE_ACT_ALIASES.get(extracted, extracted) or None


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
    has_known_act = find_known_music_act(text) is not None
    has_screen_subject = bool(tokens & (_SCREEN_TERMS - {"ator", "atores", "atriz", "atrizes", "elenco"})) or any(
        phrase in text for phrase in _SCREEN_PHRASES
    )

    # A musician appearing in a movie is still a cinema story. Keep it only
    # when a concrete music subject (song, album, concert, soundtrack) exists.
    if has_screen_subject and not has_music_subject:
        return False
    return has_role or has_music_subject or has_known_act
