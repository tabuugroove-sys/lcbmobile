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

CREATE TABLE IF NOT EXISTS youtube_comment_actions (
    comment_id        TEXT PRIMARY KEY,
    video_id          TEXT NOT NULL,
    author_channel_id TEXT,
    author_name       TEXT,
    comment_text      TEXT NOT NULL,
    reply_text        TEXT,
    status            TEXT NOT NULL,
    error             TEXT,
    action_at         TEXT NOT NULL
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

CREATE TABLE IF NOT EXISTS traffic_experiments (
    video_id    TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    platform    TEXT NOT NULL,
    profile_id  TEXT NOT NULL,
    hypothesis  TEXT NOT NULL,
    title       TEXT NOT NULL,
    item_count  INTEGER NOT NULL,
    assigned_at TEXT NOT NULL
);
"""


class Store:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Idempotent schema migrations for columns added after initial release."""
        for ddl in [
            "ALTER TABLE seen_items ADD COLUMN content_hash TEXT",
            "ALTER TABLE publications ADD COLUMN content_hash TEXT",
        ]:
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError:
                pass  # column already exists
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_seen_content_hash "
            "ON seen_items(content_hash) WHERE content_hash IS NOT NULL"
        )
        self._backfill_content_hash(conn)

    @staticmethod
    def _backfill_content_hash(conn: sqlite3.Connection) -> None:
        """One-shot fill of content_hash for rows written before the column existed.

        Uses the title text we already store. Skips rows that already have a
        hash so it's safe to run on every startup.
        """
        # Lazy import to avoid models <-> storage cycle at module load
        from ..models import _normalize_title
        import hashlib

        rows = conn.execute(
            "SELECT fingerprint, title FROM seen_items WHERE content_hash IS NULL "
            "AND title IS NOT NULL AND title != ''"
        ).fetchall()
        for fp, title in rows:
            norm = _normalize_title(title or "")
            if not norm:
                continue
            # Summary unknown for historical rows, so hash from title alone —
            # close enough to catch obvious dupes (same headline = same story).
            h = hashlib.sha1(f"{norm}|".encode("utf-8")).hexdigest()[:16]
            conn.execute(
                "UPDATE seen_items SET content_hash = ? WHERE fingerprint = ?",
                (h, fp),
            )

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

    def is_seen_by_content(self, content_hash: str) -> bool:
        """Check whether any previously-seen item had this exact content hash.

        Second layer of dedup — catches the case where the same story appears
        at two different URLs (mirror, redirect, RSS reposting with a new slug).
        """
        if not content_hash:
            return False
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM seen_items WHERE content_hash = ? LIMIT 1",
                (content_hash,),
            ).fetchone()
            return row is not None

    def already_published_by_content(self, content_hash: str, platform: str) -> bool:
        """Same as already_published() but matches by content_hash."""
        if not content_hash:
            return False
        with self._conn() as conn:
            row = conn.execute(
                """SELECT 1 FROM publications
                   WHERE content_hash = ? AND platform = ? AND status = 'ok'
                   LIMIT 1""",
                (content_hash, platform),
            ).fetchone()
            return row is not None

    def mark_seen(
        self,
        fingerprint: str,
        source_id: str,
        url: str,
        title: str,
        content_hash: str | None = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO seen_items
                   (fingerprint, source_id, url, title, seen_at, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    fingerprint,
                    source_id,
                    url,
                    title,
                    datetime.utcnow().isoformat(),
                    content_hash,
                ),
            )

    def record_publication(
        self,
        fingerprint: str,
        platform: str,
        remote_id: str | None,
        status: str,
        error: str | None = None,
        content_hash: str | None = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO publications
                   (fingerprint, platform, remote_id, status, error, posted_at,
                    content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    fingerprint,
                    platform,
                    remote_id,
                    status,
                    error,
                    datetime.utcnow().isoformat(),
                    content_hash,
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
                """SELECT MIN(p.fingerprint) AS fingerprint, p.remote_id
                   FROM publications p
                   LEFT JOIN youtube_metrics m ON m.video_id = p.remote_id
                   WHERE p.platform IN ('youtube', 'youtube_daily_multinews')
                     AND p.status = 'ok'
                     AND p.remote_id IS NOT NULL
                     AND p.remote_id != ''
                     AND (m.collected_at IS NULL OR m.collected_at < ?)
                   GROUP BY p.remote_id
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

    def youtube_comment_targets(self, limit: int = 20) -> list[tuple[str, str]]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT fingerprint, remote_id
                   FROM publications
                   WHERE platform = 'youtube'
                     AND status = 'ok'
                     AND remote_id IS NOT NULL
                     AND remote_id != ''
                   ORDER BY posted_at DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        return [(row[0], row[1]) for row in rows]

    def youtube_comment_was_processed(self, comment_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM youtube_comment_actions WHERE comment_id = ?",
                (comment_id,),
            ).fetchone()
        return row is not None

    def record_youtube_comment_action(
        self,
        *,
        comment_id: str,
        video_id: str,
        author_channel_id: str | None,
        author_name: str | None,
        comment_text: str,
        reply_text: str | None,
        status: str,
        error: str | None = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO youtube_comment_actions
                   (comment_id, video_id, author_channel_id, author_name,
                    comment_text, reply_text, status, error, action_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    comment_id,
                    video_id,
                    author_channel_id,
                    author_name,
                    comment_text,
                    reply_text,
                    status,
                    error,
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

    def record_traffic_experiment(
        self,
        *,
        video_id: str,
        fingerprint: str,
        platform: str,
        profile_id: str,
        hypothesis: str,
        title: str,
        item_count: int,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO traffic_experiments
                   (video_id, fingerprint, platform, profile_id, hypothesis,
                    title, item_count, assigned_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    video_id,
                    fingerprint,
                    platform,
                    profile_id,
                    hypothesis,
                    title,
                    item_count,
                    datetime.utcnow().isoformat(),
                ),
            )
