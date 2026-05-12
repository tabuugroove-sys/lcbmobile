"""SQLite-backed deduplication and publish log."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

from ..models import NewsItem


SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_items (
    fingerprint TEXT PRIMARY KEY,
    source_id   TEXT NOT NULL,
    url         TEXT NOT NULL,
    title       TEXT NOT NULL,
    seen_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS publications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL,
    platform    TEXT NOT NULL,
    remote_id   TEXT,
    status      TEXT NOT NULL,
    error       TEXT,
    posted_at   TEXT NOT NULL,
    UNIQUE(fingerprint, platform)
);

CREATE TABLE IF NOT EXISTS item_features (
    fingerprint  TEXT PRIMARY KEY,
    source_id    TEXT NOT NULL,
    source_name  TEXT NOT NULL,
    category     TEXT NOT NULL,
    url          TEXT NOT NULL,
    title        TEXT NOT NULL,
    summary      TEXT,
    published_at TEXT,
    recorded_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS youtube_metrics (
    video_id      TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    view_count    INTEGER NOT NULL DEFAULT 0,
    like_count    INTEGER NOT NULL DEFAULT 0,
    comment_count INTEGER NOT NULL DEFAULT 0,
    collected_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS candidate_scores (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at      TEXT NOT NULL,
    stage       TEXT NOT NULL,
    rank        INTEGER NOT NULL,
    fingerprint TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    category    TEXT NOT NULL,
    title       TEXT NOT NULL,
    score       REAL NOT NULL,
    reason      TEXT NOT NULL,
    selected    INTEGER NOT NULL
);
"""


class Store:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def is_seen(self, fingerprint: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM seen_items WHERE fingerprint = ?", (fingerprint,)
            ).fetchone()
            return row is not None

    def mark_seen(self, fingerprint: str, source_id: str, url: str, title: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO seen_items
                   (fingerprint, source_id, url, title, seen_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (fingerprint, source_id, url, title, datetime.utcnow().isoformat()),
            )

    def record_publication(
        self,
        fingerprint: str,
        platform: str,
        remote_id: str | None,
        status: str,
        error: str | None = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO publications
                   (fingerprint, platform, remote_id, status, error, posted_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    fingerprint,
                    platform,
                    remote_id,
                    status,
                    error,
                    datetime.utcnow().isoformat(),
                ),
            )

    def record_item_features(self, item: NewsItem) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO item_features
                   (fingerprint, source_id, source_name, category, url, title,
                    summary, published_at, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item.fingerprint(),
                    item.source_id,
                    item.source_name,
                    item.category,
                    item.url,
                    item.title,
                    item.summary,
                    item.published_at.isoformat() if item.published_at else None,
                    datetime.utcnow().isoformat(),
                ),
            )

    def already_published(self, fingerprint: str, platform: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT 1 FROM publications
                   WHERE fingerprint = ? AND platform = ? AND status = 'ok'""",
                (fingerprint, platform),
            ).fetchone()
            return row is not None

    def hours_since_last_post(self) -> float | None:
        """Hours since the last successful publication on any platform.

        Returns None if there are no successful posts on record. Used to
        deduplicate redundant cron triggers — we now run the schedule twice
        per slot (e.g. :13 and :43) for resilience against GHA dropping
        scheduled workflow runs under load.
        """
        with self._conn() as conn:
            row = conn.execute(
                """SELECT posted_at FROM publications
                   WHERE status = 'ok'
                   ORDER BY posted_at DESC LIMIT 1"""
            ).fetchone()
        if not row or not row[0]:
            return None
        try:
            from datetime import datetime, timezone
            last = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            return (now - last).total_seconds() / 3600.0
        except (ValueError, TypeError):
            return None

    def youtube_metric_targets(
        self, *, stale_after_hours: int, limit: int = 50
    ) -> list[tuple[str, str]]:
        cutoff = (datetime.utcnow() - timedelta(hours=stale_after_hours)).isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT p.fingerprint, p.remote_id
                   FROM publications p
                   LEFT JOIN youtube_metrics m ON m.video_id = p.remote_id
                   WHERE p.platform = 'youtube'
                     AND p.status = 'ok'
                     AND p.remote_id IS NOT NULL
                     AND p.remote_id != ''
                     AND (m.collected_at IS NULL OR m.collected_at < ?)
                   ORDER BY p.posted_at DESC
                   LIMIT ?""",
                (cutoff, limit),
            ).fetchall()
        return [(row[0], row[1]) for row in rows]

    def record_youtube_metrics(
        self,
        *,
        fingerprint: str,
        video_id: str,
        view_count: int,
        like_count: int,
        comment_count: int,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO youtube_metrics
                   (video_id, fingerprint, view_count, like_count,
                    comment_count, collected_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    video_id,
                    fingerprint,
                    view_count,
                    like_count,
                    comment_count,
                    datetime.utcnow().isoformat(),
                ),
            )

    def analytics_examples(self, limit: int) -> list[dict[str, object]]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT
                       m.fingerprint,
                       COALESCE(f.source_id, s.source_id, '') AS source_id,
                       COALESCE(f.category, '') AS category,
                       COALESCE(f.title, s.title, '') AS title,
                       COALESCE(f.summary, '') AS summary,
                       m.view_count,
                       m.like_count,
                       m.comment_count
                   FROM youtube_metrics m
                   JOIN publications p
                     ON p.platform = 'youtube' AND p.remote_id = m.video_id
                   LEFT JOIN item_features f ON f.fingerprint = m.fingerprint
                   LEFT JOIN seen_items s ON s.fingerprint = m.fingerprint
                   WHERE p.status = 'ok'
                   ORDER BY p.posted_at DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        return [
            {
                "fingerprint": row[0],
                "source_id": row[1],
                "category": row[2],
                "title": row[3],
                "summary": row[4],
                "view_count": row[5],
                "like_count": row[6],
                "comment_count": row[7],
            }
            for row in rows
        ]

    def record_candidate_scores(
        self,
        *,
        stage: str,
        scores: list[tuple[NewsItem, float, str]],
        selected: set[str],
    ) -> None:
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            conn.executemany(
                """INSERT INTO candidate_scores
                   (run_at, stage, rank, fingerprint, source_id, category,
                    title, score, reason, selected)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        now,
                        stage,
                        rank,
                        item.fingerprint(),
                        item.source_id,
                        item.category,
                        item.title,
                        score,
                        reason,
                        1 if item.fingerprint() in selected else 0,
                    )
                    for rank, (item, score, reason) in enumerate(scores, start=1)
                ],
            )
