"""Read public tracks from a Suno playlist page.

Suno renders public playlist data into React Server Component payloads.  We
decode those JSON payloads instead of depending on a private API endpoint, so
the collector works from a clean GitHub Actions runner without Suno cookies.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from typing import Any, Iterator

import httpx


@dataclass(frozen=True)
class SunoTrack:
    song_id: str
    title: str
    audio_url: str
    image_url: str
    duration_seconds: float
    description: str = ""
    created_at: datetime | None = None

    @property
    def suno_url(self) -> str:
        return f"https://suno.com/song/{self.song_id}"


def _balanced_json(text: str, start: int) -> str:
    """Return one balanced JSON array/object beginning at *start*."""
    opening = text[start]
    closing = {"[": "]", "{": "}"}.get(opening)
    if closing is None:
        raise ValueError("JSON value must start with '[' or '{'")

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise ValueError("Unterminated JSON value")


class _ScriptCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_script = False
        self.current: list[str] = []
        self.scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "script":
            self.in_script = True
            self.current = []

    def handle_data(self, data: str) -> None:
        if self.in_script:
            self.current.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self.in_script:
            self.scripts.append("".join(self.current))
            self.current = []
            self.in_script = False


def _next_payloads(html: str) -> Iterator[str]:
    collector = _ScriptCollector()
    collector.feed(html)
    marker = "self.__next_f.push("
    for text in collector.scripts:
        cursor = 0
        while True:
            marker_at = text.find(marker, cursor)
            if marker_at < 0:
                break
            value_at = marker_at + len(marker)
            while value_at < len(text) and text[value_at].isspace():
                value_at += 1
            try:
                raw = _balanced_json(text, value_at)
                value = json.loads(raw)
            except (ValueError, json.JSONDecodeError):
                cursor = value_at + 1
                continue
            if isinstance(value, list) and len(value) > 1 and isinstance(value[1], str):
                yield value[1]
            cursor = value_at + len(raw)


def _playlist_object(payload: str) -> dict[str, Any] | None:
    marker = '{"playlist":'
    start = payload.find(marker)
    if start < 0:
        return None
    try:
        value = json.loads(_balanced_json(payload, start))
    except (ValueError, json.JSONDecodeError):
        return None
    playlist = value.get("playlist") if isinstance(value, dict) else None
    return playlist if isinstance(playlist, dict) else None


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_playlist_html(html: str) -> list[SunoTrack]:
    playlist: dict[str, Any] | None = None
    for payload in _next_payloads(html):
        playlist = _playlist_object(payload)
        if playlist is not None:
            break
    if playlist is None:
        raise ValueError("Suno playlist data was not found in the page")

    tracks: list[SunoTrack] = []
    seen: set[str] = set()
    for entry in playlist.get("playlist_clips", []):
        clip = entry.get("clip") if isinstance(entry, dict) else None
        if not isinstance(clip, dict):
            continue
        song_id = str(clip.get("id") or "").strip()
        audio_url = str(clip.get("audio_url") or "").strip()
        if (
            not song_id
            or song_id in seen
            or not audio_url.startswith("https://")
            or clip.get("status") != "complete"
        ):
            continue
        metadata = clip.get("metadata")
        description = ""
        if isinstance(metadata, dict):
            description = str(metadata.get("tags") or metadata.get("prompt") or "").strip()
        duration = clip.get("duration")
        if not duration and isinstance(metadata, dict):
            duration = metadata.get("duration")
        tracks.append(
            SunoTrack(
                song_id=song_id,
                title=str(clip.get("title") or "Untitled").strip() or "Untitled",
                audio_url=audio_url,
                image_url=str(
                    clip.get("image_large_url") or clip.get("image_url") or ""
                ).strip(),
                duration_seconds=float(duration or 0.0),
                description=description,
                created_at=_parse_datetime(clip.get("created_at")),
            )
        )
        seen.add(song_id)
    return tracks


def fetch_playlist(url: str, *, timeout_seconds: float = 30.0) -> list[SunoTrack]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "Chrome/127.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    with httpx.Client(timeout=timeout_seconds, follow_redirects=True, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
    tracks = parse_playlist_html(response.text)
    if not tracks:
        raise ValueError("Suno playlist contains no complete public tracks")
    return tracks
