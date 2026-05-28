"""CLI entry point for YouTube comment replies.

Runs after the posting pipeline in GitHub Actions, but can also be called
manually:

    python -m scripts.respond_youtube_comments -v
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engagement import respond_to_youtube_comments  # noqa: E402


@click.command()
@click.option("--video-limit", type=int, default=20, help="Recent videos to inspect.")
@click.option("--comment-limit", type=int, default=50, help="Comments per video.")
@click.option("--reply-limit", type=int, default=10, help="Max replies to send.")
@click.option("--dry-run", is_flag=True, default=False, help="Draft only, do not reply.")
@click.option("-v", "--verbose", is_flag=True, default=False)
def main(
    video_limit: int,
    comment_limit: int,
    reply_limit: int,
    dry_run: bool,
    verbose: bool,
) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    try:
        report = respond_to_youtube_comments(
            video_limit=video_limit,
            comment_limit=comment_limit,
            reply_limit=reply_limit,
            dry_run=dry_run,
        )
    except Exception as exc:  # noqa: BLE001
        click.echo(f"youtube_comments=error error={exc}")
        return

    click.echo(
        "youtube_comments="
        f"videos={report.videos_checked} "
        f"seen={report.comments_seen} "
        f"replied={report.replies_sent} "
        f"skipped={report.skipped} "
        f"errors={report.errors} "
        f"likes={report.likes_sent} "
        f"likes_unsupported={report.likes_unsupported}"
    )


if __name__ == "__main__":
    main()
