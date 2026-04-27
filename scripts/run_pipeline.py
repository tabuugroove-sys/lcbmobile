"""CLI entry point: `python -m scripts.run_pipeline --dry-run`."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

# Make `src` importable when invoked directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pipeline import run  # noqa: E402


@click.command()
@click.option(
    "--limit", type=int, default=None, help="Max items to process this run."
)
@click.option(
    "--only",
    "only_publishers",
    multiple=True,
    help="Only publish to the listed platforms (youtube, instagram, tiktok, twitter, telegram).",
)
@click.option("--dry-run", is_flag=True, default=False, help="Render but do not publish.")
@click.option("-v", "--verbose", is_flag=True, default=False)
def main(limit: int | None, only_publishers: tuple[str, ...], dry_run: bool, verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    report = run(
        only_publishers=list(only_publishers) or None,
        limit=limit,
        dry_run=dry_run or None,
    )
    click.echo(
        f"fetched={report.fetched} new={report.new} processed={report.processed}"
    )
    for result in report.publish_results:
        marker = "OK" if result.ok else "FAIL"
        click.echo(f"  [{marker}] {result.platform} -> {result.remote_id or result.error}")


if __name__ == "__main__":
    main()
