"""CLI for the isolated LOOXX Suno -> YouTube workflow."""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.suno.pipeline import run  # noqa: E402


DEFAULT_PLAYLIST = "https://suno.com/playlist/344579d1-5a04-45f8-aa71-a48f9da326a3"


@click.command()
@click.option("--dry-run", is_flag=True, help="Render the next track without uploading it.")
@click.option("-v", "--verbose", is_flag=True)
def main(dry_run: bool, verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    report = run(
        playlist_url=os.getenv("SUNO_PLAYLIST_URL", DEFAULT_PLAYLIST),
        state_db=Path(os.getenv("SUNO_STATE_DB", "data/suno/state.db")),
        output_dir=Path(os.getenv("SUNO_OUTPUT_DIR", "out/looxx")),
        token_file=Path(os.getenv("YOUTUBE_TOKEN_FILE", "looxx_youtube_token.json")),
        timezone_name=os.getenv("TIMEZONE", "America/Sao_Paulo"),
        privacy_status=os.getenv("YOUTUBE_PRIVACY_STATUS", "public"),
        dry_run=dry_run,
    )
    click.echo(
        f"playlist_tracks={report.playlist_tracks} "
        f"selected={report.selected_song_id or '-'} "
        f"youtube={report.youtube_video_id or '-'}"
    )
    if report.video_path:
        click.echo(f"video={report.video_path}")
    if report.skipped_reason:
        click.echo(f"status={report.skipped_reason}")


if __name__ == "__main__":
    main()
