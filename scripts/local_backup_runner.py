"""Mac fallback scheduler for missed or failed GitHub Actions publishing slots."""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime, time as clock_time
from pathlib import Path
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models import _normalize_url  # noqa: E402
from src.storage import Store  # noqa: E402


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
STATE_FILE = DATA_DIR / "local_backup_state.json"
LOCK_FILE = DATA_DIR / "local_backup.lock"
LOG = logging.getLogger("local_backup")
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]
SOURCE_RE = re.compile(r"^Fonte:\s*(https?://\S+)", re.IGNORECASE | re.MULTILINE)

# Default Mac backup slots are 15 minutes after the primary server slots.
DEFAULT_SLOTS = (
    (clock_time(8, 28), 1),
    (clock_time(13, 28), 2),
    (clock_time(20, 28), 3),
)


def parse_publish_slots(raw: str | None) -> tuple[tuple[clock_time, int], ...]:
    """Parse ``HH:MM=count`` entries used by both Mac and Windows runners."""
    if not raw:
        return DEFAULT_SLOTS
    slots: list[tuple[clock_time, int]] = []
    for entry in raw.split(","):
        try:
            raw_time, raw_count = entry.strip().split("=", 1)
            hour, minute = (int(part) for part in raw_time.split(":", 1))
            count = int(raw_count)
            if not (0 <= hour <= 23 and 0 <= minute <= 59 and count >= 0):
                raise ValueError
        except ValueError as exc:
            raise ValueError(
                f"Invalid PUBLISH_SLOTS entry {entry!r}; expected HH:MM=count"
            ) from exc
        slots.append((clock_time(hour, minute), count))
    return tuple(sorted(slots))


def expected_posts(
    now: datetime, slots: tuple[tuple[clock_time, int], ...] | None = None
) -> int:
    current = now.timetz().replace(tzinfo=None)
    target = 0
    for slot, count in slots or parse_publish_slots(os.getenv("PUBLISH_SLOTS")):
        if current >= slot:
            target = count
    return target


def _lock_nonblocking(handle) -> bool:
    """Acquire a one-byte process lock on Unix or Windows."""
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        if not handle.read(1):
            handle.seek(0)
            handle.write("0")
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    import fcntl

    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def extract_source_url(description: str) -> str | None:
    match = SOURCE_RE.search(description or "")
    if not match:
        return None
    return match.group(1).rstrip(".,;)")


def _load_state() -> dict[str, object]:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_state(**updates: object) -> None:
    state = _load_state()
    state.update(updates)
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _cooldown_active(now: datetime) -> bool:
    raw = str(_load_state().get("last_attempt_at") or "")
    if not raw:
        return False
    try:
        last = datetime.fromisoformat(raw)
    except ValueError:
        return False
    cooldown = int(os.getenv("LOCAL_BACKUP_COOLDOWN_MINUTES", "15"))
    return (now - last).total_seconds() < cooldown * 60


def _youtube_service():
    token_file = Path(os.environ["YOUTUBE_TOKEN_FILE"])
    credentials = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    if not credentials.valid:
        if not credentials.refresh_token:
            raise RuntimeError("Local YouTube token has no refresh token")
        credentials.refresh(Request())
        token_file.write_text(credentials.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=credentials, cache_discovery=False)


def _recent_uploads(service) -> list[dict[str, str]]:
    channel_response = service.channels().list(
        part="contentDetails", mine=True
    ).execute()
    channels = channel_response.get("items") or []
    if not channels:
        raise RuntimeError("Authenticated Google account has no YouTube channel")
    playlist_id = channels[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    response = service.playlistItems().list(
        part="snippet", playlistId=playlist_id, maxResults=50
    ).execute()
    uploads: list[dict[str, str]] = []
    for row in response.get("items") or []:
        snippet = row.get("snippet") or {}
        uploads.append(
            {
                "video_id": str((snippet.get("resourceId") or {}).get("videoId") or ""),
                "title": str(snippet.get("title") or ""),
                "description": str(snippet.get("description") or ""),
                "published_at": str(snippet.get("publishedAt") or ""),
            }
        )
    return uploads


def _sync_remote_sources(uploads: list[dict[str, str]], store: Store) -> None:
    for upload in uploads:
        source_url = extract_source_url(upload["description"])
        if not source_url:
            continue
        store.mark_seen(
            _normalize_url(source_url),
            "youtube-remote-sync",
            source_url,
            upload["title"],
        )


def _shorts_today(uploads: list[dict[str, str]], tz: ZoneInfo, today) -> int:
    count = 0
    for upload in uploads:
        text = f"{upload['title']} {upload['description']}".lower()
        if "#shorts" not in text:
            continue
        try:
            published = datetime.fromisoformat(upload["published_at"].replace("Z", "+00:00"))
        except ValueError:
            continue
        if published.astimezone(tz).date() == today:
            count += 1
    return count


def _run_pipeline() -> int:
    python = os.getenv("LOCAL_BACKUP_PYTHON", sys.executable)
    command = [
        python,
        "-m",
        "scripts.run_pipeline",
        "--only",
        "youtube",
        "--limit",
        "1",
        "-v",
    ]
    env = os.environ.copy()
    env["MIN_HOURS_BETWEEN_POSTS"] = "0"
    timeout = int(os.getenv("PIPELINE_TIMEOUT_SECONDS", "2700"))
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        LOG.error("Publishing pipeline exceeded %ds and was terminated", timeout)
        return 124
    return completed.returncode


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    lock_handle = LOCK_FILE.open("a+")
    if not _lock_nonblocking(lock_handle):
        LOG.info("Another local backup run is active; skipping")
        return 0

    tz = ZoneInfo(os.getenv("TIMEZONE", "America/Sao_Paulo"))
    now = datetime.now(tz)
    target = expected_posts(now)
    if target == 0:
        LOG.info("No publishing slot is due yet")
        return 0
    if _cooldown_active(now):
        LOG.info("Local retry cooldown is active")
        return 0

    try:
        service = _youtube_service()
        uploads = _recent_uploads(service)
    except Exception as exc:  # noqa: BLE001
        LOG.exception("Cannot inspect the YouTube channel: %s", exc)
        _save_state(last_check_at=now.isoformat(), last_error=str(exc))
        return 2

    store = Store(Path(os.getenv("DB_PATH", str(DATA_DIR / "state.db"))))
    _sync_remote_sources(uploads, store)
    current = _shorts_today(uploads, tz, now.date())
    if current >= target:
        LOG.info("YouTube already has %d/%d expected Shorts today", current, target)
        _save_state(
            last_check_at=now.isoformat(),
            last_result="not_needed",
            youtube_shorts_today=current,
            target=target,
        )
        return 0

    LOG.warning("YouTube has %d/%d expected Shorts; starting local fallback", current, target)
    _save_state(
        last_attempt_at=now.isoformat(),
        last_result="running",
        youtube_shorts_today=current,
        target=target,
    )
    return_code = _run_pipeline()

    # The uploads playlist can lag briefly after a successful API upload.
    verified = current
    if return_code == 0:
        for _ in range(6):
            time.sleep(5)
            try:
                verified = _shorts_today(_recent_uploads(service), tz, now.date())
            except Exception:  # noqa: BLE001
                continue
            if verified > current:
                break

    success = return_code == 0 and verified > current
    _save_state(
        last_finished_at=datetime.now(tz).isoformat(),
        last_result="published" if success else "failed",
        last_exit_code=return_code,
        youtube_shorts_today=verified,
        target=target,
    )
    if success:
        LOG.info("Local fallback publication verified on YouTube (%d/%d)", verified, target)
        return 0
    LOG.error("Local fallback did not produce a verified YouTube Short")
    return return_code or 3


if __name__ == "__main__":
    raise SystemExit(main())
