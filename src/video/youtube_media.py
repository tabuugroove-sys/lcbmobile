"""Download arbitrary artist videos from YouTube via yt-dlp.

This adapter is a FALLBACK source: the curated Wikimedia Commons whitelist in
commons_video.py stays the primary, rights-verified supply. YouTube uploads are
recorded with honest metadata — the standard YouTube license does NOT grant
reuse rights, so nothing here is ever labelled as Creative Commons.
"""
from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from pathlib import Path

from .commons_video import LicensedVideo

try:  # yt-dlp is optional at import time so the pipeline can run without it.
    import yt_dlp
except ImportError:  # pragma: no cover
    yt_dlp = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

MANIFEST_POLICY_VERSION = 1

# Honest rights metadata: never pretend a random upload is CC-licensed.
YOUTUBE_LICENSE = "YouTube standard license (reuse rights not verified)"
YOUTUBE_LICENSE_URL = "https://www.youtube.com/static?template=terms"

MIN_DURATION_SECONDS = 15.0  # scenes need 5-13s segments from a real video
MAX_DURATION_SECONDS = 600.0
MIN_FILE_BYTES = 100_000
MAX_FILE_BYTES = 100 * 1024 * 1024
SECTION_SECONDS = 30.0  # downloading 0-30s covers any 5-13s segment at seek 0
SEARCH_LIMIT = 10

FORMAT_SELECTOR = (
    "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]"
    "/bestvideo[height<=720]+bestaudio"
    "/best[height<=720][ext=mp4]"
    "/best[height<=720]"
    "/best"
)

_LIVE_STATUSES = {"is_live", "is_upcoming", "post_live"}
_BLOCKED_AVAILABILITY = {"subscriber_only", "premium_only", "private", "needs_auth"}


def _write_manifest(
    path: Path,
    query: str | None,
    status: str,
    assets: list[LicensedVideo],
) -> None:
    path.write_text(
        json.dumps(
            {
                "policy_version": MANIFEST_POLICY_VERSION,
                "query": query,
                "status": status,
                "assets": [asset.as_manifest() for asset in assets],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _candidate_ok(
    entry: dict,
    *,
    min_duration: float,
    max_duration: float,
) -> bool:
    duration = entry.get("duration")
    if duration is None or not (min_duration <= float(duration) <= max_duration):
        return False
    if entry.get("is_live") or entry.get("live_status") in _LIVE_STATUSES:
        return False
    if entry.get("availability") in _BLOCKED_AVAILABILITY:
        return False
    return True


def _search_opts() -> dict[str, object]:
    return {
        "extract_flat": True,
        "skip_download": True,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
    }


def _download_opts(outtmpl: str, *, section_seconds: float | None) -> dict[str, object]:
    opts: dict[str, object] = {
        "format": FORMAT_SELECTOR,
        "merge_output_format": "mp4",
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 2,
        "fragment_retries": 2,
        "socket_timeout": 30,
    }
    if section_seconds is not None:
        # Requires ffmpeg (already present for moviepy): fetch only the head
        # of the video instead of the whole file. Modern yt-dlp implements
        # sections via the download_ranges callback (download_sections is gone).
        opts["download_ranges"] = yt_dlp.utils.download_range_func(
            None, [(0, section_seconds)]
        )
    return opts


def _locate_download(output_dir: Path, index: int) -> Path | None:
    expected = output_dir / f"artist-video-{index:02d}.mp4"
    if expected.exists():
        return expected
    candidates = sorted(
        path
        for path in output_dir.glob(f"artist-video-{index:02d}.*")
        if path.suffix not in {".part", ".ytdl"}
    )
    return candidates[0] if candidates else None


def _probe_duration(path: Path) -> float | None:
    """Actual on-disk duration — the only honest value after range downloads."""
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover
        return None
    try:
        return float((proc.stdout or "").strip())
    except ValueError:
        return None


def _download_candidate(
    candidate: dict,
    output_dir: Path,
    index: int,
    *,
    section_seconds: float | None,
) -> LicensedVideo | None:
    """Download one candidate, preferring a partial 0-Ns fetch via ffmpeg."""
    video_id = candidate.get("id") or ""
    url = (
        candidate.get("webpage_url")
        or candidate.get("url")
        or f"https://www.youtube.com/watch?v={video_id}"
    )
    outtmpl = str(output_dir / f"artist-video-{index:02d}.%(ext)s")

    info: dict | None = None
    partial = section_seconds is not None
    attempts = [section_seconds] if partial else []
    attempts.append(None)  # final fallback: full download
    for attempt_sections in attempts:
        opts = _download_opts(outtmpl, section_seconds=attempt_sections)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
            partial = attempt_sections is not None
            break
        except Exception as exc:  # noqa: BLE001
            if attempt_sections is not None:
                log.warning(
                    "Partial YouTube download failed (%s), retrying full file: %s",
                    url,
                    exc,
                )
            else:
                log.warning("Cannot download YouTube video %s: %s", url, exc)
                return None

    path = _locate_download(output_dir, index)
    if path is None:
        log.warning("YouTube download produced no file for %s", url)
        return None
    size = path.stat().st_size
    if size < MIN_FILE_BYTES:
        log.warning("YouTube download unexpectedly small (%d bytes): %s", size, url)
        path.unlink(missing_ok=True)
        return None
    if size > MAX_FILE_BYTES:
        log.warning("YouTube download exceeds size cap (%d bytes): %s", size, url)
        path.unlink(missing_ok=True)
        return None

    info = info or {}
    probed = _probe_duration(path)
    full_duration = float(info.get("duration") or candidate.get("duration") or 0.0)
    if probed is not None:
        duration = probed
        if partial and probed > (section_seconds or 0) + 5.0:
            log.warning(
                "Range download ignored by extractor for %s: file is %.1fs, "
                "expected ~%.0fs; recording actual duration",
                url,
                probed,
                section_seconds or 0,
            )
    else:
        duration = min(full_duration, section_seconds) if partial else full_duration
    return LicensedVideo(
        path=str(path),
        title=str(info.get("title") or candidate.get("title") or "YouTube video"),
        creator=str(info.get("uploader") or info.get("channel") or "unknown uploader"),
        license=YOUTUBE_LICENSE,
        license_url=YOUTUBE_LICENSE_URL,
        source_page=str(info.get("webpage_url") or url),
        source_url=str(info.get("webpage_url") or url),
        width=int(info.get("width") or 0),
        height=int(info.get("height") or 0),
        duration=duration,
        seek_seconds=0.0,
        sha256=_sha256(path),
    )


def fetch_youtube_artist_videos(
    artist: str | None,
    output_dir: Path,
    *,
    max_videos: int = 2,
    search_limit: int = SEARCH_LIMIT,
    min_duration: float = MIN_DURATION_SECONDS,
    max_duration: float = MAX_DURATION_SECONDS,
    section_seconds: float | None = SECTION_SECONDS,
) -> list[LicensedVideo]:
    """Search YouTube for the artist and download up to ``max_videos`` clips.

    Mirrors fetch_licensed_artist_videos() semantics: returns LicensedVideo
    objects with honest rights metadata and writes youtube_video/
    rights_manifest.json. Any YouTube/yt-dlp failure (bot checks, network,
    missing binary) is logged and degrades to [] so the pipeline can fall
    back to the photo/classic path instead of crashing.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "rights_manifest.json"
    if not artist:
        _write_manifest(manifest_path, artist, "no_query", [])
        return []

    if manifest_path.exists():
        try:
            cached = json.loads(manifest_path.read_text(encoding="utf-8"))
            assets = [LicensedVideo(**row) for row in cached.get("assets", [])]
            if (
                cached.get("query") == artist
                and cached.get("policy_version") == MANIFEST_POLICY_VERSION
                and cached.get("status") == "verified"
                and len(assets) >= max_videos
                and all(Path(asset.path).exists() for asset in assets)
            ):
                return assets[:max_videos]
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            log.warning("Ignoring unusable YouTube rights manifest: %s", manifest_path)

    if yt_dlp is None:
        log.warning("yt-dlp is not installed; YouTube ingestion unavailable")
        _write_manifest(manifest_path, artist, "unavailable", [])
        return []

    try:
        with yt_dlp.YoutubeDL(_search_opts()) as ydl:
            result = ydl.extract_info(f"ytsearch{search_limit}:{artist}", download=False)
    except Exception as exc:  # noqa: BLE001 — bot checks, network, extractor drift
        log.warning("YouTube search failed for %r: %s", artist, exc)
        _write_manifest(manifest_path, artist, "error", [])
        return []

    entries = (result or {}).get("entries") or []
    candidates = [
        entry
        for entry in entries
        if entry
        and _candidate_ok(
            entry, min_duration=min_duration, max_duration=max_duration
        )
    ]
    log.info(
        "YouTube search for %r: %d result(s), %d usable candidate(s)",
        artist,
        len(entries),
        len(candidates),
    )

    assets: list[LicensedVideo] = []
    for index, candidate in enumerate(candidates[:max_videos], start=1):
        asset = _download_candidate(
            candidate, output_dir, index, section_seconds=section_seconds
        )
        if asset is not None:
            assets.append(asset)

    wanted = min(max_videos, len(candidates))
    if wanted and len(assets) >= wanted:
        status = "verified"
    elif assets:
        status = "incomplete"
    else:
        status = "no_suitable_video"
    _write_manifest(manifest_path, artist, status, assets)
    log.info("YouTube video resolver: artist=%r verified=%d", artist, len(assets))
    return assets
