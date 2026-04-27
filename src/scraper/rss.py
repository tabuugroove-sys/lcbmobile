"""RSS collector with HTML fallback for the largest image / longer summary."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Iterable

import feedparser
import httpx
from bs4 import BeautifulSoup

from ..models import NewsItem
from .sources import Source

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (compatible; LCBMobileBot/1.0; +https://github.com/tabuugroove-sys/lcbmobile)"
)
TIMEOUT = httpx.Timeout(15.0, connect=10.0)


def _to_dt(struct_time) -> datetime | None:
    if not struct_time:
        return None
    try:
        return datetime(*struct_time[:6])
    except (TypeError, ValueError):
        return None


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", BeautifulSoup(text or "", "lxml").get_text(" ")).strip()


def _extract_image(entry) -> str | None:
    media = entry.get("media_content") or entry.get("media_thumbnail")
    if media and isinstance(media, list):
        url = media[0].get("url")
        if url:
            return url
    for link in entry.get("links", []) or []:
        if link.get("rel") == "enclosure" and (link.get("type") or "").startswith("image/"):
            return link.get("href")
    summary = entry.get("summary") or ""
    soup = BeautifulSoup(summary, "lxml")
    img = soup.find("img")
    if img and img.get("src"):
        return img["src"]
    return None


def _enrich_with_og(item: NewsItem, client: httpx.Client) -> NewsItem:
    """Best-effort: fetch the page and pull og:image / better description."""
    try:
        resp = client.get(item.url, headers={"User-Agent": USER_AGENT})
        if resp.status_code != 200:
            return item
        soup = BeautifulSoup(resp.text, "lxml")
        og_image = soup.find("meta", property="og:image")
        og_desc = soup.find("meta", property="og:description")
        if og_image and og_image.get("content") and not item.image_url:
            item = item.model_copy(update={"image_url": og_image["content"]})
        if og_desc and og_desc.get("content") and len(item.summary) < 80:
            item = item.model_copy(update={"summary": og_desc["content"].strip()})
    except httpx.HTTPError as exc:
        log.debug("og fetch failed for %s: %s", item.url, exc)
    return item


def collect_news(sources: Iterable[Source], enrich: bool = True) -> list[NewsItem]:
    items: list[NewsItem] = []
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        for src in sources:
            try:
                feed = feedparser.parse(src.url, agent=USER_AGENT)
            except Exception as exc:  # noqa: BLE001 - feedparser surfaces many
                log.warning("Failed to parse %s: %s", src.id, exc)
                continue

            for entry in feed.entries:
                url = entry.get("link")
                title = (entry.get("title") or "").strip()
                if not url or not title:
                    continue
                summary = _strip_html(entry.get("summary") or entry.get("description") or "")
                published = _to_dt(entry.get("published_parsed") or entry.get("updated_parsed"))
                image = _extract_image(entry)
                item = NewsItem(
                    source_id=src.id,
                    source_name=src.name,
                    category=src.category,
                    url=url,
                    title=title,
                    summary=summary[:600],
                    published_at=published,
                    image_url=image,
                )
                if enrich and (not item.image_url or len(item.summary) < 80):
                    item = _enrich_with_og(item, client)
                items.append(item)

    items.sort(
        key=lambda i: i.published_at or datetime.min,
        reverse=True,
    )
    return items
