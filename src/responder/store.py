"""Dedup store for the comment responder.

Kept in a dedicated SQLite file (separate from the publish pipeline's
state.db) so the two agents can be cached independently on GitHub Actions
without clobbering each other's data.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS comment_queue (
    comment_id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL,
    parent_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    author TEXT NOT NULL,
    text TEXT NOT NULL,
    context TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS replied_comments (
    comment_id  TEXT PRIMARY KEY,
    video_id    TEXT NOT NULL,
    status      TEXT NOT NULL,   -- 'replied' | 'skipped'
    reply_id    TEXT,
    reason      TEXT,
    handled_at  TEXT NOT NULL
);
"""

RETRYABLE_REASON_PREFIXES = (
    "minimax error:",
    "anthropic error:",
    "gemini error:",
    "no llm available",
)


class CommentStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            columns = {r[1] for r in conn.execute('PRAGMA table_info(comment_queue)')}
            if 'thread_id' not in columns:
                conn.execute("ALTER TABLE comment_queue ADD COLUMN thread_id TEXT NOT NULL DEFAULT ''")

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def is_handled(self, comment_id: str) -> bool:
        """True if we already replied to or deliberately skipped this comment."""
        if not comment_id:
            return True
        with self._conn() as conn:
            row = conn.execute(
                "SELECT status, reason FROM replied_comments WHERE comment_id = ?",
                (comment_id,),
            ).fetchone()
            if row is None:
                return False
            status, reason = str(row[0] or ""), str(row[1] or "").casefold()
            if status == "skipped" and reason.startswith(RETRYABLE_REASON_PREFIXES):
                return False
            return True

    def mark_handled(
        self,
        comment_id: str,
        video_id: str,
        status: str,
        *,
        reply_id: str | None = None,
        reason: str | None = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO replied_comments
                   (comment_id, video_id, status, reply_id, reason, handled_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    comment_id,
                    video_id,
                    status,
                    reply_id,
                    reason,
                    datetime.utcnow().isoformat(),
                ),
            )

    def replied_count_today(self) -> int:
        """How many real replies we posted since UTC midnight (quota guard)."""
        today = datetime.utcnow().date().isoformat()
        with self._conn() as conn:
            row = conn.execute(
                """SELECT COUNT(*) FROM replied_comments
                   WHERE status = 'replied' AND handled_at >= ?""",
                (today,),
            ).fetchone()
            return int(row[0]) if row else 0

    def enqueue(self, comment: dict) -> None:
        if self.is_handled(comment["comment_id"]):
            return
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO comment_queue (comment_id,video_id,parent_id,thread_id,author,text,context)
                   VALUES (:comment_id,:video_id,:parent_id,:thread_id,:author,:text,:context)
                   ON CONFLICT(comment_id) DO UPDATE SET text=excluded.text,
                   author=excluded.author,context=excluded.context,thread_id=excluded.thread_id""", comment,
            )

    def pending(self) -> list[dict]:
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM comment_queue ORDER BY rowid").fetchall()
        return [dict(r) for r in rows if not self.is_handled(r['comment_id'])]

    def dequeue(self, comment_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM comment_queue WHERE comment_id=?", (comment_id,))
