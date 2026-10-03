"""Supply footage to the cloud over existing outbound SSH; never publish posts."""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import subprocess
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from scripts.export_youtube_cookies import export_youtube_cookies
from src.video.mac_media import artist_key, write_json
from src.video.youtube_media import fetch_youtube_artist_videos

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent


class CloudTransport:
    def __init__(self) -> None:
        self.host = os.getenv("MAC_MEDIA_SSH_HOST", "capytime")
        self.root = os.getenv("MAC_MEDIA_REMOTE_ROOT", "C:/lcbmobile-news/data/mac_media")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", self.host):
            raise ValueError("Invalid media-worker SSH alias")
        if not re.fullmatch(r"[A-Za-z0-9_:/.-]+", self.root):
            raise ValueError("Invalid media-worker cloud directory")

    def command(self, script: str) -> str:
        script = "$ErrorActionPreference = 'Stop'; [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); " + script
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        result = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", self.host,
             f"powershell -NoProfile -NonInteractive -EncodedCommand {encoded}"],
            capture_output=True, text=True, timeout=30, check=True,
        )
        return result.stdout.strip()

    def upload(self, local: Path, remote: str) -> None:
        subprocess.run(
            ["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
             str(local), f"{self.host}:{remote}"],
            capture_output=True, text=True, timeout=90, check=True,
        )

    def heartbeat(self, status: str = "ready") -> None:
        self.command(f"New-Item -ItemType Directory -Force '{self.root}/requests' | Out-Null")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "heartbeat.json"
            write_json(path, {"updated_at": datetime.now(timezone.utc).isoformat(), "status": status})
            self.upload(path, f"{self.root}/heartbeat.upload.json")
        self.command(f"Move-Item -Force '{self.root}/heartbeat.upload.json' '{self.root}/heartbeat.json'")

    def requests(self) -> list[dict]:
        raw = self.command(
            f"$rows = @(Get-ChildItem '{self.root}/requests' -Filter '*.json' | "
            "Sort-Object LastWriteTime | Select-Object -First 1 | "
            "ForEach-Object { Get-Content $_.FullName -Raw | ConvertFrom-Json }); "
            "ConvertTo-Json -InputObject $rows -Depth 5 -Compress"
        )
        rows = json.loads(raw or "[]")
        return rows if isinstance(rows, list) else []

    def publish(self, artist: str, videos: list, *, requested_at: str = "") -> None:
        key = artist_key(artist)
        folder = f"{self.root}/assets/{key}"
        self.command(f"New-Item -ItemType Directory -Force '{folder}' | Out-Null")
        rows = []
        for index, video in enumerate(videos, 1):
            path = Path(video.path)
            name = f"clip-{index:02d}{path.suffix}"
            self.upload(path, f"{folder}/{name}.upload")
            self.command(f"Move-Item -Force '{folder}/{name}.upload' '{folder}/{name}'")
            row = asdict(video)
            row.pop("path")
            row["file"] = name
            rows.append(row)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            write_json(path, {
                "artist": artist, "updated_at": datetime.now(timezone.utc).isoformat(),
                "requested_at": requested_at, "status": "ready" if rows else "unavailable",
                "downloaded_on": "mac", "assets": rows,
            })
            self.upload(path, f"{folder}/manifest.upload.json")
        self.command(f"Move-Item -Force '{folder}/manifest.upload.json' '{folder}/manifest.json'")
        self.command(f"Remove-Item -Force '{self.root}/requests/{key}.json' -ErrorAction SilentlyContinue")


def process_request(request: dict, transport: CloudTransport) -> bool:
    artist = str(request.get("artist") or "").strip()
    if not artist or len(artist) > 120 or request.get("key") != artist_key(artist):
        raise ValueError("Invalid media request")
    stamp = datetime.fromisoformat(str(request["requested_at"]).replace("Z", "+00:00"))
    if stamp.tzinfo is None or not -10 <= (datetime.now(timezone.utc) - stamp).total_seconds() <= 900:
        transport.publish(artist, [], requested_at=str(request["requested_at"]))
        return False
    transport.heartbeat("busy")
    videos = fetch_youtube_artist_videos(
        artist, ROOT / "data" / "mac_media_worker" / artist_key(artist),
        max_videos=1,
        search_query=f"{artist} red carpet interview",
    )
    transport.publish(artist, videos, requested_at=str(request["requested_at"]))
    transport.heartbeat()
    log.info("Supplied %d clip(s) to the cloud for %r", len(videos), artist)
    return bool(videos)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    lock = ROOT / "data" / "mac_media_worker.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a+") as handle:
        import fcntl
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        transport = CloudTransport()
        try:
            cookies = Path(os.environ["YOUTUBE_COOKIES_FILE"])
            if not cookies.exists() or datetime.now().timestamp() - cookies.stat().st_mtime > 21600:
                export_youtube_cookies(cookies, os.getenv("MAC_MEDIA_CHROME_PROFILE", "Profile 1"))
            transport.heartbeat()
            for request in transport.requests():
                process_request(request, transport)
            return 0
        except Exception as exc:
            log.error("Optional Mac media worker failed: %s", type(exc).__name__)
            try:
                transport.heartbeat("unavailable")
            except Exception:
                pass
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
