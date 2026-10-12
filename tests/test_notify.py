from __future__ import annotations

import unittest
from unittest.mock import patch

from src.notify import _urgent_targets, notify_urgent


class NotifyTests(unittest.TestCase):
    def test_urgent_target_falls_back_to_notify_chat(self) -> None:
        env = {
            "LCBAND_URGENT_BOT_TOKEN": "urgent-token",
            "LCBAND_NOTIFY_CHAT_ID": "123",
        }
        with patch.dict("os.environ", env, clear=True):
            self.assertEqual(
                _urgent_targets(),
                [("urgent", "urgent-token", "123")],
            )

    @patch("src.notify._run")
    def test_urgent_send_falls_back_to_next_bot(self, run) -> None:
        outcomes = iter([False, True])

        def complete(coroutine):
            coroutine.close()
            return next(outcomes)

        run.side_effect = complete
        env = {
            "LCBAND_URGENT_BOT_TOKEN": "urgent-token",
            "LCBAND_URGENT_CHAT_ID": "123",
            "LCBAND_NOTIFY_BOT_TOKEN": "notify-token",
            "LCBAND_NOTIFY_CHAT_ID": "123",
        }
        with patch.dict("os.environ", env, clear=True):
            self.assertTrue(notify_urgent("posting stalled", kind="no_shorts_today"))
        self.assertEqual(run.call_count, 2)

    def test_duplicate_target_is_used_only_once(self) -> None:
        env = {
            "LCBAND_URGENT_BOT_TOKEN": "same-token",
            "LCBAND_URGENT_CHAT_ID": "123",
            "LCBAND_NOTIFY_BOT_TOKEN": "same-token",
            "LCBAND_NOTIFY_CHAT_ID": "123",
        }
        with patch.dict("os.environ", env, clear=True):
            self.assertEqual(len(_urgent_targets()), 1)

    @patch("src.notify._urgent_targets")
    def test_attempt_errors_and_unclassified_alerts_never_send(self, targets) -> None:
        self.assertFalse(notify_urgent("LCB daily attempt 1/5 failed"))
        self.assertFalse(notify_urgent("No face", kind="missing_face"))
        targets.assert_not_called()


if __name__ == "__main__":
    unittest.main()
