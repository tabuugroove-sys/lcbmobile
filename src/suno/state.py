"""Durable one-per-day publication state for LOOXX Suno tracks."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from zoneinfo import ZoneInfo

from .playlist import SunoTrack


SCHEMA = """
CREATE TABLE IF NOT EXISTS suno_publications (
    song_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    youtube_video_id TEXT,
    status TEXT NOT NULL,
    posted_at TEXT,
    posted_local_date TEXT,
    error TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_suno_publications_day
ON suno_publications(posted_local_date, status);
"""


class SunoState:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def successful_song_ids(self) -> set[str]:
        with self._conn() as connection:
            rows = connection.execute(
                "SELECT song_id FROM suno_publications WHERE status = 'ok'"
            ).fetchall()
        return {str(song_id) for (song_id,) in rows}

    def has_success_today(
        self,
        timezone_name: str,
        *,
        now: datetime | None = None,
    ) -> bool:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        local_date = now.astimezone(ZoneInfo(timezone_name)).date().isoformat()
        with self._conn() as connection:
            row = connection.execute(
                """SELECT 1 FROM suno_publications
                   WHERE status = 'ok' AND posted_local_date = ? LIMIT 1""",
                (local_date,),
            ).fetchone()
        return row is not None

    def record_success(
        self,
        *,
        song_id: str,
        title: str,
        youtube_video_id: str,
        posted_at: datetime,
        timezone_name: str,
    ) -> None:
        if posted_at.tzinfo is None:
            posted_at = posted_at.replace(tzinfo=timezone.utc)
        posted_at = posted_at.astimezone(timezone.utc)
        local_date = posted_at.astimezone(ZoneInfo(timezone_name)).date().isoformat()
        updated_at = datetime.now(timezone.utc).isoformat()
        with self._conn() as connection:
            connection.execute(
                """INSERT INTO suno_publications
                   (song_id, title, youtube_video_id, status, posted_at,
                    posted_local_date, error, updated_at)
                   VALUES (?, ?, ?, 'ok', ?, ?, NULL, ?)
                   ON CONFLICT(song_id) DO UPDATE SET
                     title=excluded.title,
                     youtube_video_id=excluded.youtube_video_id,
                     status='ok',
                     posted_at=excluded.posted_at,
                     posted_local_date=excluded.posted_local_date,
                     error=NULL,
                     updated_at=excluded.updated_at""",
                (
                    song_id,
                    title,
                    youtube_video_id,
                    posted_at.isoformat(),
                    local_date,
                    updated_at,
                ),
            )

    def record_failure(self, track: SunoTrack, error: str) -> None:
        updated_at = datetime.now(timezone.utc).isoformat()
        with self._conn() as connection:
            connection.execute(
                """INSERT INTO suno_publications
                   (song_id, title, status, error, updated_at)
                   VALUES (?, ?, 'error', ?, ?)
                   ON CONFLICT(song_id) DO UPDATE SET
                     title=excluded.title,
                     status=CASE WHEN suno_publications.status = 'ok'
                                 THEN 'ok' ELSE 'error' END,
                     error=CASE WHEN suno_publications.status = 'ok'
                                THEN suno_publications.error ELSE excluded.error END,
                     updated_at=excluded.updated_at""",
                (track.song_id, track.title, error[:2000], updated_at),
            )


def next_unpublished_track(
    tracks: list[SunoTrack], published_song_ids: set[str]
) -> SunoTrack | None:
    """Keep playlist order so an existing backlog drains predictably."""
    return next((track for track in tracks if track.song_id not in published_song_ids), None)
