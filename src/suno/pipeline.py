"""One-track-per-day Suno playlist publisher for the LOOXX YouTube channel."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .playlist import SunoTrack, fetch_playlist
from .state import SunoState, next_unpublished_track
from .video import RenderedTrack, render_track
from .youtube import recent_suno_uploads, upload_track, youtube_service

log = logging.getLogger(__name__)


@dataclass
class SunoRunReport:
    playlist_tracks: int = 0
    selected_song_id: str | None = None
    selected_title: str | None = None
    video_path: Path | None = None
    youtube_video_id: str | None = None
    skipped_reason: str | None = None


def run(
    *,
    playlist_url: str,
    state_db: Path,
    output_dir: Path,
    token_file: Path,
    timezone_name: str = "America/Sao_Paulo",
    privacy_status: str = "public",
    dry_run: bool = False,
    now: datetime | None = None,
) -> SunoRunReport:
    now = now or datetime.now(timezone.utc)
    tracks = fetch_playlist(playlist_url)
    report = SunoRunReport(playlist_tracks=len(tracks))
    state = SunoState(state_db)
    track_by_id: dict[str, SunoTrack] = {track.song_id: track for track in tracks}

    service = None
    if not dry_run:
        service = youtube_service(token_file)
        # Repair a missing/stale Actions cache from the authoritative YouTube
        # uploads playlist before applying the one-per-day gate.
        for remote in recent_suno_uploads(service):
            source = track_by_id.get(remote.song_id)
            state.record_success(
                song_id=remote.song_id,
                title=source.title if source else remote.title,
                youtube_video_id=remote.video_id,
                posted_at=remote.published_at,
                timezone_name=timezone_name,
            )

        if state.has_success_today(timezone_name, now=now):
            report.skipped_reason = "one track has already been published today"
            log.info("Skipping: %s", report.skipped_reason)
            return report

    selected = next_unpublished_track(tracks, state.successful_song_ids())
    if selected is None:
        report.skipped_reason = "no unpublished tracks in the Suno playlist"
        log.info("Skipping: %s", report.skipped_reason)
        return report

    report.selected_song_id = selected.song_id
    report.selected_title = selected.title
    rendered: RenderedTrack = render_track(selected, output_dir)
    report.video_path = rendered.video_path
    log.info("Rendered %s -> %s", selected.title, rendered.video_path)

    if dry_run:
        report.skipped_reason = "dry run; upload was not requested"
        return report

    assert service is not None
    try:
        video_id = upload_track(
            service,
            selected,
            rendered.video_path,
            playlist_url,
            privacy_status=privacy_status,
        )
    except Exception as exc:
        state.record_failure(selected, str(exc))
        raise
    state.record_success(
        song_id=selected.song_id,
        title=selected.title,
        youtube_video_id=video_id,
        posted_at=now,
        timezone_name=timezone_name,
    )
    report.youtube_video_id = video_id
    log.info("Published https://www.youtube.com/watch?v=%s", video_id)
    return report
