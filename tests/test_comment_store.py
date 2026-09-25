from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.responder.store import CommentStore


class CommentStoreTests(unittest.TestCase):
    def test_generation_failure_is_retryable_but_policy_skip_is_handled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CommentStore(Path(temp_dir) / "comments.db")
            store.mark_handled(
                "retry-me",
                "video",
                "skipped",
                reason="gemini error: truncated JSON",
            )
            store.mark_handled(
                "leave-closed",
                "video",
                "skipped",
                reason="hate or harassment",
            )

            self.assertFalse(store.is_handled("retry-me"))
            self.assertTrue(store.is_handled("leave-closed"))

    def test_replied_comment_is_always_handled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CommentStore(Path(temp_dir) / "comments.db")
            store.mark_handled(
                "done",
                "video",
                "replied",
                reply_id="reply",
                reason="gemini error: text happens to mention this phrase",
            )

            self.assertTrue(store.is_handled("done"))


if __name__ == "__main__":
    unittest.main()
