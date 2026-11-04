from __future__ import annotations

import unittest
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, Mock
from zoneinfo import ZoneInfo

from click.testing import CliRunner

from scripts import local_backup_runner, run_pipeline
from scripts.local_backup_runner import (
    _alert_posting_gap,
    _run_pipeline,
    expected_posts,
    parse_publish_slots,
)
from src.pipeline import RunReport
from src.shorts_quota import (
    SLOT_FILLED_EXIT_CODE,
    TARGET_ENV,
    extract_source_url,
    recent_uploads as _recent_uploads,
    shorts_today as _shorts_today,
)


class LocalBackupRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tz = ZoneInfo("America/Sao_Paulo")

    def test_counts_only_public_processed_uploads(self) -> None:
        service = Mock()
        service.channels.return_value.list.return_value.execute.return_value = {"items": [{
            "id": "UC-TFUUc4YHleNoIFXBVaj7A", "contentDetails": {"relatedPlaylists": {"uploads": "playlist"}}
        }]}
        service.playlistItems.return_value.list.return_value.execute.return_value = {"items": [
            {"snippet": {"resourceId": {"videoId": str(i)}}} for i in range(3)
        ]}
        service.videos.return_value.list.return_value.execute.return_value = {"items": [
            {"id": "0", "snippet": {"title": "News #Shorts"}, "status": {"privacyStatus": "public", "uploadStatus": "processed"}},
            {"id": "1", "snippet": {}, "status": {"privacyStatus": "private", "uploadStatus": "processed"}},
            {"id": "2", "snippet": {}, "status": {"privacyStatus": "public", "uploadStatus": "uploaded"}},
        ]}
        self.assertEqual([r["video_id"] for r in _recent_uploads(service)], ["0"])

    def _at(self, hour: int, minute: int) -> datetime:
        return datetime(2026, 8, 31, hour, minute, tzinfo=self.tz)

    def test_expected_posts_tracks_backup_slots(self) -> None:
        with patch.dict("os.environ", {"PUBLISH_SLOTS": ""}):
            self.assertEqual(expected_posts(self._at(10, 4)), 0)
            self.assertEqual(expected_posts(self._at(10, 5)), 1)
            self.assertEqual(expected_posts(self._at(15, 4)), 1)
            self.assertEqual(expected_posts(self._at(15, 5)), 2)
            self.assertEqual(expected_posts(self._at(20, 5)), 3)

    def test_backup_waits_out_a_whole_server_attempt(self) -> None:
        # 2026-11-01 and 11-04: server runs uploaded 25-27 minutes after the slot, while
        # the old backup check 15 minutes after it had already started a render of its own.
        server_slots = parse_publish_slots("09:13=1,14:13=2,19:13=3")
        with patch.dict("os.environ", {"PUBLISH_SLOTS": ""}):
            for hour in (9, 14, 19):
                slot = self._at(hour, 13)
                target = expected_posts(slot, server_slots)
                # The server's latest five-minute poll, then its whole pipeline timeout.
                server_done = slot + timedelta(minutes=5, seconds=2700)
                self.assertEqual(expected_posts(server_done), target - 1)
                # The GitHub fallback checks one hour after the slot.
                self.assertEqual(expected_posts(slot + timedelta(minutes=59)), target)

    def test_primary_server_slots_are_configurable(self) -> None:
        slots = parse_publish_slots("09:13=1,14:13=2,19:13=3")
        self.assertEqual(expected_posts(self._at(9, 12), slots), 0)
        self.assertEqual(expected_posts(self._at(9, 13), slots), 1)
        self.assertEqual(expected_posts(self._at(19, 13), slots), 3)

    def test_invalid_slot_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_publish_slots("25:99=1")

    def test_extract_source_url(self) -> None:
        description = "Texto\n\nFonte: https://example.com/news?utm_source=x\n\n#Shorts"
        self.assertEqual(
            extract_source_url(description),
            "https://example.com/news?utm_source=x",
        )

    def test_missing_source_url(self) -> None:
        self.assertIsNone(extract_source_url("Sem link de fonte"))

    def test_shorts_today_counts_duplicate_source_url_once(self) -> None:
        uploads = [
            {
                "video_id": "first",
                "title": "Primeira versao #Shorts",
                "description": "Fonte: https://example.com/news",
                "published_at": "2026-08-31T12:30:00Z",
            },
            {
                "video_id": "duplicate",
                "title": "Outra manchete #Shorts",
                "description": (
                    "Fonte: http://www.example.com/news/?utm_source=backup"
                ),
                "published_at": "2026-08-31T12:31:00Z",
            },
            {
                "video_id": "other",
                "title": "Outra noticia #Shorts",
                "description": "Fonte: https://example.com/other",
                "published_at": "2026-08-31T12:32:00Z",
            },
        ]

        self.assertEqual(_shorts_today(uploads, self.tz, self._at(9, 40).date()), 2)

    @patch("scripts.local_backup_runner.subprocess.run")
    def test_pipeline_timeout_returns_standard_timeout_code(self, run) -> None:
        run.side_effect = subprocess.TimeoutExpired(["python", "pipeline"], 9)
        with patch.dict("os.environ", {"PIPELINE_TIMEOUT_SECONDS": "9"}):
            self.assertEqual(_run_pipeline(2), 124)

    @patch("scripts.local_backup_runner.subprocess.run")
    def test_pipeline_receives_the_slot_target(self, run) -> None:
        run.return_value = subprocess.CompletedProcess([], 0)
        self.assertEqual(_run_pipeline(3), 0)
        env = run.call_args.kwargs["env"]
        self.assertEqual(env[TARGET_ENV], "3")
        self.assertEqual(env["MIN_HOURS_BETWEEN_POSTS"], "0")

    def test_pipeline_cli_reports_a_slot_filled_during_render(self) -> None:
        with patch("scripts.run_pipeline.run", return_value=RunReport(new=1, processed=1, slot_filled=True)):
            result = CliRunner().invoke(run_pipeline.main, ["--only", "youtube", "--limit", "1"])
        self.assertEqual(result.exit_code, SLOT_FILLED_EXIT_CODE)
        self.assertIn("nothing uploaded", result.output)

    def test_slot_filled_during_render_is_not_a_failure(self) -> None:
        pipeline = Mock(return_value=SLOT_FILLED_EXIT_CODE)
        with TemporaryDirectory() as temp_dir, patch.multiple(
            local_backup_runner,
            DATA_DIR=Path(temp_dir),
            STATE_FILE=Path(temp_dir) / "state.json",
            LOCK_FILE=Mock(),
            _lock_nonblocking=Mock(return_value=True),
            expected_posts=Mock(return_value=2),
            _alert_posting_gap=Mock(return_value=False),
            _youtube_service=Mock(),
            recent_uploads=Mock(return_value=[]),
            shorts_today=Mock(return_value=1),
            Store=Mock(),
            _run_pipeline=pipeline,
        ), patch("scripts.local_backup_runner.time.sleep") as sleep:
            self.assertEqual(local_backup_runner.main(), 0)
            state = local_backup_runner._load_state()

        pipeline.assert_called_once_with(2)
        sleep.assert_not_called()
        self.assertEqual(state["last_result"], "filled_elsewhere")
        self.assertEqual(state["last_exit_code"], SLOT_FILLED_EXIT_CODE)

    def test_posting_gap_alert_is_sent_once_per_quota_milestone(self) -> None:
        with TemporaryDirectory() as temp_dir, patch(
            "scripts.local_backup_runner.STATE_FILE",
            Path(temp_dir) / "state.json",
        ), patch(
            "scripts.local_backup_runner.notify_urgent",
            return_value=True,
        ) as notify:
            first = _alert_posting_gap(
                self._at(23, 59), current=0, target=0, return_code=0
            )
            second = _alert_posting_gap(
                self._at(23, 59), current=0, target=0, return_code=0
            )

        self.assertTrue(first)
        self.assertFalse(second)
        notify.assert_called_once()
        self.assertIn("no YouTube Shorts", notify.call_args.args[0])
        self.assertEqual(notify.call_args.kwargs["kind"], "no_shorts_today")

    def test_failed_alert_delivery_is_retried(self) -> None:
        with TemporaryDirectory() as temp_dir, patch(
            "scripts.local_backup_runner.STATE_FILE",
            Path(temp_dir) / "state.json",
        ), patch(
            "scripts.local_backup_runner.notify_urgent",
            side_effect=[False, True],
        ) as notify:
            first = _alert_posting_gap(
                self._at(23, 59), current=0, target=0, return_code=0
            )
            second = _alert_posting_gap(
                self._at(23, 59), current=0, target=0, return_code=0
            )

        self.assertFalse(first)
        self.assertTrue(second)
        self.assertEqual(notify.call_count, 2)

    def test_quota_misses_and_incomplete_days_do_not_alert(self) -> None:
        with patch("scripts.local_backup_runner.notify_urgent") as notify:
            self.assertFalse(_alert_posting_gap(self._at(23, 59), current=1, target=3, return_code=3))
            self.assertFalse(_alert_posting_gap(self._at(19, 45), current=0, target=3, return_code=3))
        notify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
