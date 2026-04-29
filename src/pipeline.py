"""End-to-end orchestrator: scrape -> dedupe -> rewrite -> render -> publish."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .config import ROOT, settings
from .models import GeneratedAssets, NewsItem, RewrittenPost
from .notify import notify, notify_error, notify_summary, notify_youtube_published
from .processor import rewrite
from .publisher import build_publishers, PublishResult
from .scraper import collect_news, load_sources
from .storage import Store
from .video import build_short

log = logging.getLogger(__name__)


@dataclass
class RunReport:
    fetched: int = 0
    new: int = 0
    processed: int = 0
    publish_results: list[PublishResult] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.publish_results is None:
            self.publish_results = []


def run(
    *,
    sources_path: Path | None = None,
    only_publishers: list[str] | None = None,
    limit: int | None = None,
    dry_run: bool | None = None,
) -> RunReport:
    sources_path = sources_path or (ROOT / "config" / "sources.yaml")
    limit = limit if limit is not None else settings.max_items_per_run
    dry_run = settings.dry_run if dry_run is None else dry_run

    store = Store(settings.db_path)
    sources = load_sources(sources_path)
    log.info("Loaded %d sources", len(sources))

    try:
        items = collect_news(sources)
    except Exception as exc:  # noqa: BLE001
        log.exception("RSS scrape failed")
        notify_error("scrape", exc)
        raise

    report = RunReport(fetched=len(items))

    fresh: list[NewsItem] = []
    for item in items:
        if store.is_seen(item.fingerprint()):
            continue
        fresh.append(item)
        if len(fresh) >= limit:
            break
    report.new = len(fresh)
    log.info("Fetched=%d new=%d (limit=%d)", report.fetched, report.new, limit)

    if not fresh:
        notify(
            f"ℹ️ Nada novo neste run.\nfetched={report.fetched} new=0 limit={limit}"
        )
        return report

    publishers = build_publishers(only_publishers)
    log.info("Active publishers: %s", [p.name for p in publishers])
    if not publishers:
        notify("⚠️ Nenhum publisher configurado.")
        return report

    for item in fresh:
        try:
            post: RewrittenPost = rewrite(item)
        except Exception as exc:  # noqa: BLE001
            log.exception("Rewrite failed for %s", item.url)
            notify_error("rewrite", exc, context=item.url)
            continue

        try:
            assets: GeneratedAssets = build_short(
                item, post, settings.output_dir, lang=settings.content_lang
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("Video render failed for %s", item.url)
            notify_error("render", exc, context=item.url)
            continue

        report.processed += 1
        log.info("Rendered %s (%.1fs)", assets.video_path, assets.duration_seconds)

        if dry_run:
            log.info("DRY_RUN=1, skipping publish for %s", item.url)
            continue

        any_ok = False
        for pub in publishers:
            if store.already_published(item.fingerprint(), pub.name):
                continue
            result = pub.publish(post, assets)
            report.publish_results.append(result)
            store.record_publication(
                item.fingerprint(),
                pub.name,
                result.remote_id,
                "ok" if result.ok else "error",
                error=result.error,
            )
            if result.ok:
                any_ok = True
                if pub.name == "youtube" and result.url:
                    notify_youtube_published(post.headline, result.url)
            else:
                notify_error(
                    f"publish:{pub.name}",
                    Exception(result.error or "unknown error"),
                    context=item.url,
                )
            log.info(
                "[%s] %s -> %s",
                pub.name,
                "OK" if result.ok else "FAIL",
                result.remote_id or result.error,
            )

        # Mark seen only after the item was actually distributed - keeps
        # failed items in the retry queue across runs.
        if any_ok:
            store.mark_seen(
                item.fingerprint(), item.source_id, item.url, item.title
            )

    notify_summary(report)
    return report
