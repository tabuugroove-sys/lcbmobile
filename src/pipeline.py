"""End-to-end orchestrator: scrape -> dedupe -> rewrite -> render -> publish."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import time
from zoneinfo import ZoneInfo

from .analytics import refresh_youtube_metrics, select_best_candidates
from .config import ROOT, settings
from .models import GeneratedAssets, NewsItem, RewrittenPost
from .notify import notify, notify_error, notify_summary
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


def _retry_wait(item: NewsItem, attempt: int) -> None:
    if attempt >= settings.max_attempts_per_item:
        return
    delay = settings.retry_delay_seconds
    log.warning(
        "Retrying %s in %ds (attempt %d/%d)",
        item.url,
        delay,
        attempt + 1,
        settings.max_attempts_per_item,
    )
    time.sleep(delay)


def _yesterday_fallback_items(
    items: list[NewsItem], store: Store, limit: int
) -> list[NewsItem]:
    if not settings.fallback_to_yesterday:
        return []

    tz = ZoneInfo(settings.timezone)
    today = datetime.now(tz).date()
    yesterday = today - timedelta(days=1)
    fallback: list[NewsItem] = []

    for item in items:
        if not item.published_at:
            continue
        published = item.published_at
        if published.tzinfo is not None:
            published_date = published.astimezone(tz).date()
        else:
            published_date = published.date()
        if published_date != yesterday:
            continue

        dedupe_key = f"replay:{today.isoformat()}:{item.fingerprint()}"
        if store.is_seen(dedupe_key):
            continue
        fallback.append(item.model_copy(update={"dedupe_key": dedupe_key}))
        if len(fallback) >= settings.analytics_candidate_pool:
            break

    return select_best_candidates(fallback, store, limit=limit, stage="fallback")


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
    refresh_youtube_metrics(store)

    # Skip redundant cron triggers — we run the schedule twice per slot for
    # GHA-drop resilience (cron at :13 AND :43). If the previous twin already
    # posted, this run becomes a no-op. Configurable via env.
    import os as _os
    min_gap_h = float(_os.getenv("MIN_HOURS_BETWEEN_POSTS", "3.5"))
    last = store.hours_since_last_post()
    if last is not None and last < min_gap_h:
        # Silent skip — this is a redundant cron twin, completely expected.
        # No notify() because it would spam the public Telegram channel with
        # ~6 messages/day. Detail is still in the GHA logs.
        log.info(
            "Skipping run: last post was %.2fh ago, min gap is %.2fh "
            "(redundant cron trigger).",
            last,
            min_gap_h,
        )
        return RunReport()

    sources = load_sources(sources_path)
    log.info("Loaded %d sources", len(sources))

    try:
        items = collect_news(sources)
    except Exception as exc:  # noqa: BLE001
        log.exception("RSS scrape failed")
        notify_error("scrape", exc)
        raise

    report = RunReport(fetched=len(items))

    candidates: list[NewsItem] = []
    for item in items:
        if store.is_seen(item.fingerprint()):
            continue
        candidates.append(item)
        if len(candidates) >= settings.analytics_candidate_pool:
            break
    fresh = select_best_candidates(candidates, store, limit=limit, stage="fresh")

    if not fresh:
        fresh = _yesterday_fallback_items(items, store, limit)
        if fresh:
            log.info(
                "No fresh items; using %d yesterday fallback item(s).",
                len(fresh),
            )
            notify(
                f"ℹ️ Nada novo; usando notícia de ontem.\n"
                f"fallback={len(fresh)} limit={limit}"
            )

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
        store.record_item_features(item)
        for attempt in range(1, settings.max_attempts_per_item + 1):
            log.info(
                "Processing %s (attempt %d/%d)",
                item.url,
                attempt,
                settings.max_attempts_per_item,
            )
            try:
                post: RewrittenPost = rewrite(item)
            except Exception as exc:  # noqa: BLE001
                log.exception("Rewrite failed for %s", item.url)
                notify_error("rewrite", exc, context=item.url)
                _retry_wait(item, attempt)
                continue

            try:
                assets: GeneratedAssets = build_short(
                    item, post, settings.output_dir, lang=settings.content_lang
                )
            except Exception as exc:  # noqa: BLE001
                log.exception("Video render failed for %s", item.url)
                notify_error("render", exc, context=item.url)
                _retry_wait(item, attempt)
                continue

            report.processed += 1
            log.info("Rendered %s (%.1fs)", assets.video_path, assets.duration_seconds)

            if dry_run:
                log.info("DRY_RUN=1, skipping publish for %s", item.url)
                break

            any_ok = False
            all_ok = True
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
                else:
                    all_ok = False
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

            if all_ok and any_ok:
                # Mark seen only after the item was distributed everywhere we
                # intended to publish it. This keeps partial failures in the
                # retry queue for another attempt.
                store.mark_seen(
                    item.fingerprint(), item.source_id, item.url, item.title
                )
                break

            _retry_wait(item, attempt)

    notify_summary(report)
    return report
