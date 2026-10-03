"""Bounded cloud-side requests to the optional, outbound-only Mac media worker."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .commons_video import LicensedVideo

log = logging.getLogger(__name__)
_wait_spent = 0.0


def artist_key(artist: str) -> str:
    return hashlib.sha256(artist.strip().casefold().encode()).hexdigest()[:24]


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=True), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _age(data: dict, field: str = "updated_at") -> float:
    try:
        stamp = datetime.fromisoformat(str(data[field]).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return float("inf")
        return (datetime.now(timezone.utc) - stamp).total_seconds()
    except (KeyError, ValueError, TypeError):
        return float("inf")


def _root() -> Path | None:
    value = os.getenv("MAC_MEDIA_ROOT", "").strip()
    return Path(value) if value else None


def mac_is_available(root: Path) -> bool:
    heartbeat = _read_json(root / "heartbeat.json")
    ttl = float(os.getenv("MAC_MEDIA_HEARTBEAT_TTL_SECONDS", "120"))
    return heartbeat.get("status") in {"ready", "busy"} and -10 <= _age(heartbeat) <= ttl


def cached_mac_artist_videos(artist: str | None, *, max_videos: int = 2) -> list[LicensedVideo]:
    root = _root()
    if root is None or not artist:
        return []
    folder = root / "assets" / artist_key(artist)
    manifest = _read_json(folder / "manifest.json")
    if manifest.get("artist") != artist or not -10 <= _age(manifest) <= 30 * 86400:
        return []
    rows = manifest.get("assets", [])
    if not isinstance(rows, list):
        return []
    assets = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            spec = dict(row)
            name = str(spec.pop("file"))
            if Path(name).name != name or "/" in name or "\\" in name:
                continue
            path = folder / name
            if not 100_000 <= path.stat().st_size <= 100 * 1024 * 1024:
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != spec.get("sha256"):
                continue
            asset = LicensedVideo(path=str(path), **spec)
            if asset.duration >= 8 and asset.width > 0 and asset.height > 0:
                assets.append(asset)
        except (OSError, KeyError, TypeError, ValueError):
            continue
        if len(assets) >= max_videos:
            break
    return assets


def fetch_mac_artist_videos(artist: str | None, *, max_videos: int = 2) -> list[LicensedVideo]:
    global _wait_spent
    cached = cached_mac_artist_videos(artist, max_videos=max_videos)
    if cached:
        return cached
    root = _root()
    if root is None or not artist or not mac_is_available(root):
        return []
    key = artist_key(artist)
    response_path = root / "assets" / key / "manifest.json"
    previous = _read_json(response_path)
    if previous.get("artist") == artist and not previous.get("assets") and 0 <= _age(previous) < 900:
        return []
    total_budget = float(os.getenv("MAC_MEDIA_TOTAL_WAIT_SECONDS", "120"))
    wait = min(float(os.getenv("MAC_MEDIA_WAIT_SECONDS", "90")), total_budget - _wait_spent)
    if wait <= 0:
        return []
    started = time.monotonic()
    requested_at = datetime.now(timezone.utc).isoformat()
    try:
        write_json(root / "requests" / f"{key}.json", {
            "artist": artist, "key": key, "max_videos": min(2, max(1, max_videos)),
            "requested_at": requested_at,
        })
        log.info("Requesting optional Mac footage for %r (wait <= %.0fs)", artist, wait)
        while time.monotonic() - started < wait:
            cached = cached_mac_artist_videos(artist, max_videos=max_videos)
            if cached:
                log.info("Received %d Mac-downloaded clip(s) for %r", len(cached), artist)
                return cached
            response = _read_json(response_path)
            if response.get("requested_at") == requested_at or not mac_is_available(root):
                break
            time.sleep(min(2.0, max(0.0, wait - (time.monotonic() - started))))
    except OSError as exc:
        log.warning("Optional Mac footage unavailable: %s", exc)
    finally:
        _wait_spent += time.monotonic() - started
    log.info("Continuing cloud-only after optional Mac footage was unavailable for %r", artist)
    return []
