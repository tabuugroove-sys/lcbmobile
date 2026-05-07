"""SQLite-backed deduplication and publish log."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator


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
