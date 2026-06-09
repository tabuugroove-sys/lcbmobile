"""CLI: post a single article URL through the pipeline (bypasses RSS).

Use when you want to push an ad-hoc story right now without waiting for it
to surface in the RSS feeds, e.g. a breaking event. Reuses the exact same
rewrite + render + publish stages so the output is identical to scheduled
runs.

    python -m scripts.post_url <URL> [--only youtube] [--dry-run]
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import click
import httpx
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings  # noqa: E402
from src.models import NewsItem  # noqa: E402
from src.notify import notify, notify_error  # noqa: E402
from src.processor import rewrite  # noqa: E402
from src.publisher import build_publishers  # noqa: E402
from src.video import build_short  # noqa: E402

log = logging.getLogger(__name__)


def fetch_article(url: str) -> NewsItem:
    """Download a public news URL and synthesize a NewsItem from its OG/meta tags."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        )
    }
    r = httpx.get(url, timeout=30.0, follow_redirects=True, headers=headers)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")

    def meta(prop: str, attr: str = "property") -> str:
        tag = soup.find("meta", {attr: prop})
        return (tag.get("content") or "").strip() if tag else ""

    title = meta("og:title") or (soup.title.string.strip() if soup.title and soup.title.string else "")
    summary = meta("og:description") or meta("description", attr="name")
    image_url = meta("og:image") or None

    if len(summary) < 200:
        article_root = soup.find("article") or soup.find("main") or soup
        paragraphs = [p.get_text(" ", strip=True) for p in article_root.find_all("p")[:8]]
        long_text = " ".join(p for p in paragraphs if len(p) > 30)
        if long_text:
            summary = (summary + " " + long_text).strip()[:1800]

    if not title:
        raise RuntimeError(f"Could not extract a title from {url}")

    return NewsItem(
        source_id="manual",
        source_name="Manual URL",
        category="celebridades",
        title=title[:400],
        summary=summary[:2000],
        url=url,
        image_url=image_url,
        published_at=datetime.now(timezone.utc),
    )


@click.command()
@click.argument("url")
@click.option(
    "--only",
    "only_publishers",
    multiple=True,
    help="Restrict to listed platforms (youtube, instagram, tiktok, twitter, telegram).",
)
@click.option("--dry-run", is_flag=True, default=False, help="Render but do not publish.")
@click.option("-v", "--verbose", is_flag=True, default=False)
def main(url: str, only_publishers: tuple[str, ...], dry_run: bool, verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    log.info("Fetching %s", url)
    try:
        item = fetch_article(url)
    except Exception as exc:  # noqa: BLE001
        log.exception("Fetch failed")
        notify_error("post_url:fetch", exc, context=url)
        sys.exit(1)
    log.info("Title: %s", item.title)

    try:
        post = rewrite(item)
    except Exception as exc:  # noqa: BLE001
        log.exception("Rewrite failed")
        notify_error("post_url:rewrite", exc, context=url)
        sys.exit(2)
    log.info("Headline: %s", post.headline)

    try:
        assets = build_short(
            item, post, settings.output_dir, lang=settings.content_lang
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("Render failed")
        notify_error("post_url:render", exc, context=url)
        sys.exit(3)
    log.info("Rendered %s (%.1fs)", assets.video_path, assets.duration_seconds)

    if dry_run:
        click.echo(f"DRY_RUN — rendered {assets.video_path}, skipped publish")
        return

    publishers = build_publishers(list(only_publishers) or None)
    log.info("Active publishers: %s", [p.name for p in publishers])
    if not publishers:
        notify("⚠️ post_url: nenhum publisher configurado.")
        sys.exit(4)

    optional_publishers = {
        name.strip().lower()
        for name in os.getenv("OPTIONAL_PUBLISHERS", "telegram").split(",")
        if name.strip()
    }
    any_required_failure = False
    for pub in publishers:
        result = pub.publish(post, assets)
        marker = "OK" if result.ok else "FAIL"
        click.echo(f"[{marker}] {pub.name} -> {result.remote_id or result.error}")
        if not result.ok:
            if pub.name in optional_publishers:
                log.warning(
                    "Optional publisher %s failed; continuing: %s",
                    pub.name,
                    result.error or "unknown error",
                )
                continue
            any_required_failure = True
            notify_error(
                f"post_url:publish:{pub.name}",
                Exception(result.error or "unknown"),
                context=url,
            )

    if any_required_failure:
        sys.exit(5)


if __name__ == "__main__":
    main()
