"""CLI entry point: `python -m scripts.reply_comments -v`.

Reads recent comments on the channel's own uploads and posts pt-BR replies
in the channel voice. YouTube only. Autoposts immediately.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

# Make `src` importable when invoked directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.responder import run_comment_responder  # noqa: E402


@click.command()
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Read comments and generate replies but do NOT post them.",
)
@click.option("-v", "--verbose", is_flag=True, default=False)
def main(dry_run: bool, verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    stats = run_comment_responder(dry_run=dry_run)
    click.echo(
        f"videos={stats['videos']} scanned={stats['scanned']} "
        f"replied={stats['replied']} skipped={stats['skipped']} "
        f"errors={stats['errors']}"
    )


if __name__ == "__main__":
    main()
